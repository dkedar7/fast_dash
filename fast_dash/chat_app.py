"""Native chat-mode app for Fast Dash (RFC #133).

The transport- and UI-*independent* chat core (frame grammar, history, turn
runner) lives in :mod:`fast_dash.chat`. This module holds the Dash-facing
**chat application** — layout, clientside/server callbacks, the streaming turn
driver, rich-frame rendering, HITL, and the assistant-driven canvas — as a mixin
that :class:`fast_dash.FastDash` inherits. It is split out to keep
``fast_dash.py`` focused on the general app; behavior is unchanged.
"""

import inspect
import json
import threading
import time
import warnings

from plotly.io.json import to_json_plotly

from .Components import AppLayout, _infer_input_components
from .utils import (
    _assign_ids_to_inputs,
    _get_error_notification_component,
    _make_input_groups,
)

# Idle sessions are evicted after this long; sweeps are throttled to run at most
# once per interval so eviction is O(sessions) amortized, not per-turn.
_SESSION_TTL_SECONDS = 6 * 3600
_SESSION_SWEEP_INTERVAL = 60


class ChatAppMixin:
    """Chat-mode methods mixed into :class:`FastDash` (RFC #133)."""

    def _init_chat(self, callback_fn, inputs):
        """Initialize a native chat-mode app (RFC #133 Phase 1).

        The composer binds to the ``query`` parameter, ``history`` is injected
        when declared, and every *other* parameter renders in the sidebar as a
        setting via the normal type-hint inference path. There are no output
        components — the transcript is the main area.
        """
        from .chat import ChatHistory

        self.state_counter = 0
        self.chat_history = ChatHistory(size=self.chat_history_size)
        # One ChatSession per browser session holds all per-session state (the
        # in-flight/cancel guard, ASGI transcript, HITL pending turn, canvas
        # specs), guarded by a single lock; idle sessions are evicted (see
        # _session). Replaces five parallel per-sid dicts.
        self._sessions = {}
        self._sessions_lock = threading.Lock()
        self._last_sweep = 0.0

        sig = inspect.signature(callback_fn)
        setting_params = [
            p for name, p in sig.parameters.items()
            if name not in ("query", "history", "ctx")
            and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        self._chat_setting_names = [p.name for p in setting_params]

        if inputs is not None:
            self.inputs = inputs if isinstance(inputs, list) else [inputs]
            self.inputs_with_ids = _assign_ids_to_inputs(self.inputs, callback_fn)
        elif setting_params:
            settings_fn = self._make_user_params_fn(
                [(p.name, p) for p in setting_params]
            )
            self.inputs = _infer_input_components(settings_fn)
            self.inputs_with_ids = _assign_ids_to_inputs(self.inputs, settings_fn)
        else:
            self.inputs = []
            self.inputs_with_ids = []

        self.input_tags = [inp.tag for inp in self.inputs]
        self.ack_mask = [
            False if (not hasattr(input_, "ack") or (input_.ack is None)) else True
            for input_ in self.inputs_with_ids
        ]

        # No output components in chat mode; keep the attributes the shared
        # machinery expects present-but-empty.
        self.outputs = []
        self.outputs_with_ids = []
        self.output_tags = []
        self.output_state_default = []
        self.output_state = []
        self.output_state_blank = []
        self.latest_output_state = []
        self.update_live = False

        self.app.title = self.title or ""
        self._set_chat_layout()
        self._register_chat_callbacks()
        if self.serve_agui:
            self._mount_agui()

        self.submit_clicks = 0
        self.reset_clicks = 0
        self.app_initialized = False

    def _mount_agui(self):
        """Serve the chat's LangGraph over AG-UI SSE at ``/agui`` (Phase 4).

        Mirrors the MCP story: an external AG-UI frontend can drive the same
        graph the chat UI does. Requires a langstage agent on an ASGI backend
        (AG-UI is an SSE transport); anything else is a friendly no-op warning.
        """
        if not self.is_langstage:
            warnings.warn(
                "serve_agui=True needs a LangGraph agent (chat=True with a graph "
                "or 'module:attr' spec); no AG-UI endpoint was mounted.",
                stacklevel=2,
            )
            return
        if not self._backend:
            warnings.warn(
                "serve_agui=True needs an ASGI backend (backend='fastapi'); "
                "AG-UI is served over SSE. No AG-UI endpoint was mounted.",
                stacklevel=2,
            )
            return
        from .adapters.langstage import serve_agui_endpoint
        graph = getattr(self.callback_fn, "__fast_dash_graph__", None)
        serve_agui_endpoint(self.app.server, graph, path="/agui",
                            name=self.title or "Fast Dash chat")

    # ----- chat mode: layout + callbacks (RFC #133) ---------------------- #

    @staticmethod
    def _chat_user_bubble(text):
        from dash import html
        return html.Div(
            html.Div(text, className="fd-chat-bubble"),
            className="fd-chat-msg fd-chat-user",
        )

    def _chat_assistant_bubble(self, blocks, streaming=False):
        """Render an assistant turn from its ordered blocks (RFC #133 Phase 2).

        ``blocks`` is a list of ``{"kind": ...}`` dicts accumulated from the
        frame stream: ``text`` / ``reasoning`` / ``tool`` / ``artifact`` /
        ``extraction``. During streaming, text stays raw and artifacts show a
        placeholder; the final render materializes markdown + artifacts.
        """
        from dash import dcc, html
        parts = []
        for b in (blocks or []):
            kind = b.get("kind")
            if kind == "text":
                if streaming:
                    parts.append(html.Div(b["text"], className="fd-chat-text fd-chat-stream"))
                else:
                    parts.append(dcc.Markdown(b["text"] or "", className="fd-chat-text",
                                              link_target="_blank"))
            elif kind == "reasoning":
                parts.append(self._chat_reasoning_block(b["text"]))
            elif kind == "tool":
                parts.append(self._chat_tool_card(b))
            elif kind == "artifact":
                parts.append(self._chat_artifact_block(b["content"], streaming))
            elif kind == "extraction":
                parts.append(self._chat_extraction_card(b.get("content")))
            elif kind == "interrupt":
                parts.append(self._chat_interrupt_card(b, pending=not b.get("resolved")))
        return html.Div(
            html.Div(parts, className="fd-chat-bubble fd-chat-blocks"),
            className="fd-chat-msg fd-chat-assistant",
        )

    def _chat_interrupt_card(self, block, pending=True):
        """Approve/deny/edit card for a human-in-the-loop interrupt (Phase 4).

        Renders the agent's ``action_requests`` and a decision button per
        ``allowed_decisions``. While ``pending`` the buttons are live (a
        pattern-matching callback resumes the paused turn); once a decision is
        made the card is frozen and shows the chosen decision.
        """
        from dash import html

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        requests = block.get("action_requests") or []
        decisions = block.get("allowed_decisions") or ["approve", "reject"]
        chosen = block.get("decision")

        body = [
            dmc.Group(
                [
                    DashIconify(icon="tabler:hand-stop", width=16),
                    html.Span("Action needed", className="fd-chat-interrupt-title"),
                ],
                gap="xs", wrap="nowrap",
            )
        ]
        for req in requests:
            name = req.get("action") or req.get("name") or "action"
            args = req.get("args")
            body.append(html.Div(str(name), className="fd-chat-interrupt-action"))
            if args:
                body.append(html.Pre(self._chat_short_json(args),
                                     className="fd-chat-tool-args"))

        if pending:
            _color = {"approve": "green", "accept": "green",
                      "reject": "red", "deny": "red"}
            buttons = [
                dmc.Button(
                    str(d).capitalize(),
                    id={"type": "chat-decision", "decision": str(d)},
                    color=_color.get(str(d), "blue"),
                    variant="light", size="xs", n_clicks=0,
                )
                for d in decisions
            ]
            body.append(dmc.Group(buttons, gap="xs", className="fd-chat-interrupt-actions"))
        elif chosen is not None:
            body.append(html.Span("Decision: " + str(chosen),
                                   className="fd-chat-interrupt-decided"))

        return dmc.Paper(body, withBorder=True, radius="sm", p="xs",
                         className="fd-chat-interrupt")

    @staticmethod
    def _chat_reasoning_block(text):
        """A collapsible 'thinking' block (native details/summary, no callback)."""
        from dash import dcc, html
        return html.Details(
            [
                html.Summary("Thinking", className="fd-chat-reasoning-summary"),
                dcc.Markdown(text or "", className="fd-chat-reasoning-body"),
            ],
            className="fd-chat-reasoning",
        )

    def _chat_tool_card(self, block):
        """A tool-call card: name, optional args, status, and (on completion) result."""
        from dash import dcc, html

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        done = block.get("status") == "done"
        icon = "tabler:circle-check" if done else "tabler:loader-2"
        header = dmc.Group(
            [
                DashIconify(icon=icon, width=16,
                            className="" if done else "fd-chat-tool-spin"),
                html.Span(str(block.get("name", "tool")), className="fd-chat-tool-name"),
                html.Span("done" if done else "running", className="fd-chat-tool-status"),
            ],
            gap="xs", wrap="nowrap",
        )
        body = []
        args = block.get("args")
        if args:
            body.append(html.Pre(self._chat_short_json(args), className="fd-chat-tool-args"))
        if done and block.get("result") is not None:
            body.append(html.Pre(self._chat_short_json(block["result"]),
                                  className="fd-chat-tool-result"))
        return dmc.Paper([header] + body, withBorder=True, radius="sm",
                         p="xs", className="fd-chat-tool")

    def _chat_extraction_card(self, content):
        from dash import html
        return html.Pre(self._chat_short_json(content), className="fd-chat-extraction")

    @staticmethod
    def _chat_short_json(value, limit=800):
        """Compact, JSON-safe, length-capped string for tool args/results."""
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, default=str, indent=2)
            except Exception:
                text = str(value)
        return text if len(text) <= limit else text[:limit] + " ..."

    def _chat_artifact_block(self, content, streaming=False):
        """Render an inline artifact (Plotly / DataFrame / image / text).

        During streaming a lightweight placeholder is shown; the real component
        materializes at turn completion (RFC D2).
        """
        from dash import dcc, html
        if streaming:
            return html.Div("Rendering artifact...", className="fd-chat-artifact-pending")

        import dash_mantine_components as dmc

        try:
            import plotly.graph_objects as go
            if isinstance(content, go.Figure):
                return dcc.Graph(figure=content, className="fd-chat-artifact",
                                 style={"width": "100%"})
        except Exception:
            pass
        try:
            import pandas as pd
            if isinstance(content, pd.DataFrame):
                from dash import dash_table
                return dash_table.DataTable(
                    data=content.to_dict("records"),
                    columns=[{"name": str(c), "id": str(c)} for c in content.columns],
                    page_size=10, sort_action="native",
                    style_table={"overflowX": "auto"},
                    className="fd-chat-artifact",
                )
        except Exception:
            pass
        try:
            import PIL.Image
            from .utils import _pil_to_b64
            if isinstance(content, PIL.Image.Image):
                return html.Img(src=_pil_to_b64(content), className="fd-chat-artifact",
                                style={"maxWidth": "100%"})
        except Exception:
            pass
        try:
            import matplotlib as mpl
            from .utils import _mpl_to_b64
            if isinstance(content, mpl.figure.Figure):
                return html.Img(src=_mpl_to_b64(content), className="fd-chat-artifact",
                                style={"maxWidth": "100%"})
        except Exception:
            pass
        # Fallback: render as markdown text.
        return dcc.Markdown(str(content), className="fd-chat-text")

    def _chat_bubble_json(self, component):
        """Serialize a Dash component to the plotly-json the reducer inserts."""
        return json.loads(to_json_plotly(component))

    def _chat_canvas_render(self, sid):
        """Serialize the session's canvas specs into a Dash children list.

        Reuses DynamicDash's ``render_spec`` verbatim, then extracts the group
        list so it drops straight into ``chat-canvas.children`` (mirroring how
        DynamicDash sets ``dyn-form.children``).
        """
        from .dynamic import render_spec
        div = render_spec(self._session(sid).canvas_specs,
                          container_id="_canvas_render")
        return self._chat_bubble_json(div).get("props", {}).get("children", [])

    @staticmethod
    def _gather_canvas_values(states):
        """Build ``{name: value}`` from the canvas pattern-matching ALL-states.

        ``states`` is ``(vals_value, vals_checked, vals_contents, ids_value,
        ids_checked, ids_contents)`` — the same homogeneous-property pool
        DynamicDash reads its form values from.
        """
        (vals_value, vals_checked, vals_contents,
         ids_value, ids_checked, ids_contents) = states
        out = {}
        for vals, ids in ((vals_value, ids_value), (vals_checked, ids_checked),
                          (vals_contents, ids_contents)):
            for v, idd in zip(vals or [], ids or []):
                if isinstance(idd, dict) and "name" in idd:
                    out[idd["name"]] = v
        return out

    def _chat_canvas_apply(self, sid, frame):
        """Apply a ``canvas`` or ``set_props`` frame to the session's spec state."""
        from .dynamic import COMPONENT_REGISTRY
        sess = self._session(sid)
        if frame["type"] == "canvas":
            sess.canvas_specs = list(frame["specs"])
            return
        # set_props: patch the target spec's props, routing a value-prop update
        # to the spec's 'value' so _spec_to_component applies it (props are
        # overridden by 'value' otherwise).
        for spec in sess.canvas_specs:
            if spec.get("name") == frame["target"]:
                props = dict(frame["props"])
                factory = COMPONENT_REGISTRY.get(spec.get("type"))
                vprop = getattr(factory, "component_property", "value")
                if vprop in props:
                    spec["value"] = props.pop(vprop)
                spec["props"] = {**(spec.get("props") or {}), **props}
                break

    def _set_chat_layout(self):
        from .Components import AppLayout

        input_groups = (
            _make_input_groups(self.inputs_with_ids, False, show_submit=False)
            if self.inputs_with_ids else []
        )
        layout_args = {
            "mosaic": None,
            "inputs": input_groups,
            "outputs": [],
            "title": self.title,
            "title_image_path": self.title_image_path,
            "subtitle": self.subtitle,
            "github_url": self.github_url,
            "linkedin_url": self.linkedin_url,
            "twitter_url": self.twitter_url,
            "navbar": self.navbar,
            "footer": self.footer,
            "loader": self.loader,
            "branding": self.branding,
            "about": self.about,
            "minimal": self.minimal,
            "scale_height": self.scale_height,
            "theme": self.theme,
            "app": self,
        }
        app_layout = AppLayout(**layout_args)
        self.layout_object = app_layout
        event_names = ["chat_frames", "notification-container"]
        if self.is_canvas:
            event_names.append("chat_canvas")     # dedicated canvas transport
        self.app.layout = app_layout.generate_chat_layout(
            has_settings=bool(self.inputs_with_ids),
            stream_event_names=event_names,
            native_stream=self._native_stream,
            canvas=self.is_canvas,
        )

    def _register_chat_callbacks(self):
        from dash import ALL, Input, Output, State
        from dash.exceptions import PreventUpdate

        app = self.app

        # Shared chrome callbacks (dark-mode toggle, burger, About).
        if not self.minimal:
            self.layout_object.callbacks(self)

        # (1) Per-browser session id — generated once on load, kept stable.
        app.clientside_callback(
            """
            function(_id, current) {
                if (current) { return current; }
                if (window.crypto && crypto.randomUUID) { return crypto.randomUUID(); }
                return 'sid-' + Date.now() + '-' + Math.random().toString(16).slice(2);
            }
            """,
            Output("chat-session", "data"),
            Input("chat-messages", "id"),
            State("chat-session", "data"),
        )

        # (2) The transcript reducer (Flask only): apply start / replace0 ops
        # delivered as ordered socket.io events to the message list. On ASGI
        # there is no socket component; the server pushes the full rendered list
        # straight to chat-messages.children via set_props (see _run_chat_turn),
        # so no clientside reducer is registered.
        if not self._native_stream:
            app.clientside_callback(
                """
                function(payload, children) {
                    if (!payload || (payload.op !== 'start' && payload.op !== 'replace0')) {
                        return dash_clientside.no_update;
                    }
                    children = Array.isArray(children) ? [...children] : (children ? [children] : []);
                    if (payload.op === 'start') {
                        // Atomic: add the user bubble AND the empty assistant bubble
                        // together (index 0 = assistant, the replace0 target). Doing
                        // this in one op avoids a stale-State race between two adds.
                        if (payload.user) { children.unshift(payload.user); }
                        if (payload.assistant) { children.unshift(payload.assistant); }
                    } else if (payload.op === 'replace0') {
                        // Idempotent: carries the full accumulated render, so a
                        // dropped/stale frame self-heals on the next one.
                        var comp = payload.value || null;
                        if (children.length) { children[0] = comp; }
                        else if (comp !== null) { children.unshift(comp); }
                    }
                    return children;
                }
                """,
                Output("chat-messages", "children", allow_duplicate=True),
                Input("socketio", "data-chat_frames"),
                State("chat-messages", "children"),
                prevent_initial_call=True,
            )

            # (2b) Canvas reducer (Flask + canvas mode): a 'canvas' op on the
            # dedicated chat_canvas event carries the full rendered spec list;
            # replace chat-canvas.children wholesale (full-state, coalescing-safe).
            if self.is_canvas:
                app.clientside_callback(
                    """
                    function(payload) {
                        if (!payload || payload.op !== 'canvas') {
                            return dash_clientside.no_update;
                        }
                        return payload.value || [];
                    }
                    """,
                    Output("chat-canvas", "children", allow_duplicate=True),
                    Input("socketio", "data-chat_canvas"),
                    prevent_initial_call=True,
                )

        # (3) Send handler (button click). Guards empty / in-flight, clears the
        # composer, sets the submit trigger, flags streaming.
        app.clientside_callback(
            """
            function(n_clicks, value, streaming) {
                var no = dash_clientside.no_update;
                if (!n_clicks) { return [no, no, no]; }
                var text = (value || '').trim();
                if (!text || streaming) { return [no, no, no]; }
                return [{q: text, ts: Date.now()}, '', true];
            }
            """,
            [Output("chat-submit-store", "data"),
             Output("chat-input", "value"),
             Output("chat-streaming", "data", allow_duplicate=True)],
            Input("chat-send", "n_clicks"),
            [State("chat-input", "value"), State("chat-streaming", "data")],
            prevent_initial_call=True,
        )

        # (4) Enter-to-send / Shift+Enter=newline — attach a keydown listener to
        # the composer once. The listener lives on the actual <textarea> (the id
        # may sit on a wrapper), and clicks the send button on Enter.
        app.clientside_callback(
            """
            function(_id) {
                var root = document.getElementById('chat-input');
                if (!root) { return window.dash_clientside.no_update; }
                var ta = (root.tagName === 'TEXTAREA') ? root : root.querySelector('textarea');
                if (ta && !ta.dataset.fdEnterBound) {
                    ta.dataset.fdEnterBound = '1';
                    ta.addEventListener('keydown', function(e) {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            var btn = document.getElementById('chat-send');
                            if (btn && !btn.disabled) { btn.click(); }
                        }
                    });
                }
                return window.dash_clientside.no_update;
            }
            """,
            Output("chat-enter-init", "data"),
            Input("chat-input", "id"),
        )

        # (5) Disable the send button while a turn streams.
        app.clientside_callback(
            "function(streaming) { return !!streaming; }",
            Output("chat-send", "disabled"),
            Input("chat-streaming", "data"),
        )

        # (6) The server turn callback: drive the generator, stream frames to the
        # browser (socket.io on Flask, set_props on ASGI), append to history,
        # re-enable the composer. On ASGI it becomes a WebSocket callback so
        # set_props can push mid-execution; there is no socket id there.
        setting_states = [
            State(inp.id, inp.component_property) for inp in self.inputs_with_ids
        ]
        turn_states = [State("chat-session", "data")]
        if not self._native_stream:
            turn_states.append(State("socketio", "socketId"))
        turn_states += setting_states
        # Canvas value read-back: the same homogeneous-property pool DynamicDash
        # gathers its form values from (6 ALL-states, appended last).
        if self.is_canvas:
            turn_states += [
                State({"role": "dyn-input", "name": ALL, "prop": "value"}, "value"),
                State({"role": "dyn-input", "name": ALL, "prop": "checked"}, "checked"),
                State({"role": "dyn-input", "name": ALL, "prop": "contents"}, "contents"),
                State({"role": "dyn-input", "name": ALL, "prop": "value"}, "id"),
                State({"role": "dyn-input", "name": ALL, "prop": "checked"}, "id"),
                State({"role": "dyn-input", "name": ALL, "prop": "contents"}, "id"),
            ]

        _turn_cb_kwargs = dict(prevent_initial_call=True)
        if self._native_stream:
            _turn_cb_kwargs["websocket"] = True

        @app.callback(
            [Output("chat-streaming", "data", allow_duplicate=True),
             Output("notification-container", "sendNotifications", allow_duplicate=True)],
            Input("chat-submit-store", "data"),
            turn_states,
            **_turn_cb_kwargs,
        )
        def _chat_turn(submit, session_id, *rest):
            rest = list(rest)
            # Canvas ALL-states are appended last; peel them off to read values.
            canvas_values = None
            if self.is_canvas:
                canvas_values = self._gather_canvas_values(rest[-6:])
                rest = rest[:-6]
            # Flask: rest = (socket_id, *setting_values); ASGI: rest = setting_values.
            if self._native_stream:
                socket_id = None
                setting_values = tuple(rest)
            else:
                socket_id = rest[0] if rest else None
                setting_values = tuple(rest[1:])

            if not submit or not (submit.get("q") or "").strip():
                raise PreventUpdate
            query = submit["q"].strip()
            sid = session_id or "default"

            sess = self._session(sid)
            # A pending interrupt must be answered (via the decision buttons)
            # before a new turn can start (HITL, Phase 4).
            if sess.pending:
                return False, _get_error_notification_component(
                    "Please respond to the pending action first.")

            # One in-flight turn per session (server-side guard, D4).
            with self._sessions_lock:
                if sess.active:
                    return False, _get_error_notification_component(
                        "A response is still streaming; please wait.")
                sess.active = True
                sess.cancel = False              # fresh turn, clear Stop flag

            try:
                self._run_chat_turn(query, sid, socket_id, setting_values,
                                    canvas_values=canvas_values)
                return False, []
            finally:
                with self._sessions_lock:
                    sess.active = False
                    sess.cancel = False

        # Stop button: set the per-session cancel flag; the running turn thread
        # observes it via run_turn's cancelled() check and stops gracefully.
        @app.callback(
            Output("chat-stop", "n_clicks"),
            Input("chat-stop", "n_clicks"),
            State("chat-session", "data"),
            prevent_initial_call=True,
        )
        def _chat_stop(n_clicks, session_id):
            if n_clicks:
                sess = self._session(session_id or "default")
                with self._sessions_lock:
                    sess.cancel = True
            return 0

        # Show the Stop button (and hide Send) only while a turn streams.
        app.clientside_callback(
            """
            function(streaming) {
                var show = {display: 'inline-flex'};
                var hide = {display: 'none'};
                return streaming ? [hide, show] : [show, hide];
            }
            """,
            [Output("chat-send", "style"), Output("chat-stop", "style")],
            Input("chat-streaming", "data"),
        )

        # (7) HITL decision buttons (langstage only): a pattern-matching callback
        # resumes the paused turn with the chosen decision. Rendered inside the
        # interrupt card, so it uses ALL + ctx.triggered_id to find the click.
        if self.is_langstage:
            from dash import ALL, ctx

            dec_states = [State("chat-session", "data")]
            if not self._native_stream:
                dec_states.append(State("socketio", "socketId"))
            _dec_cb_kwargs = dict(prevent_initial_call=True)
            if self._native_stream:
                _dec_cb_kwargs["websocket"] = True

            @app.callback(
                [Output("chat-streaming", "data", allow_duplicate=True),
                 Output("notification-container", "sendNotifications",
                        allow_duplicate=True)],
                Input({"type": "chat-decision", "decision": ALL}, "n_clicks"),
                dec_states,
                **_dec_cb_kwargs,
            )
            def _chat_decision(n_clicks_list, session_id, *rest):
                if not n_clicks_list or not any(n_clicks_list):
                    raise PreventUpdate
                triggered = ctx.triggered_id
                if not triggered or triggered.get("type") != "chat-decision":
                    raise PreventUpdate
                decision = triggered.get("decision")
                socket_id = None if self._native_stream else (rest[0] if rest else None)
                sid = session_id or "default"
                sess = self._session(sid)

                with self._sessions_lock:
                    if sess.active:
                        return False, _get_error_notification_component(
                            "A response is still streaming; please wait.")
                    if not sess.pending:
                        raise PreventUpdate
                    sess.active = True
                    sess.cancel = False
                try:
                    self._resume_chat_turn(sid, socket_id, decision)
                    return False, []
                finally:
                    with self._sessions_lock:
                        sess.active = False
                        sess.cancel = False

    def _run_chat_turn(self, query, sid, socket_id, setting_values, emit=None,
                       resume=None, resume_decision=None, resume_blocks=None,
                       canvas_values=None):
        """Drive one chat turn, streaming its blocks to the browser.

        Two transports, one turn-driver:

        * **Flask** (default): incremental ops (``start`` / ``replace0``) are
          pushed as discrete socket.io events; a clientside reducer applies them
          to the message list. ``emit`` may be supplied to capture these ops.
        * **ASGI** (``_native_stream``): ``set_props`` is a latest-value-wins
          transport, so incremental ops would be lost to coalescing. Instead the
          server owns the per-session transcript and pushes the *full* rendered
          message list straight to ``chat-messages.children`` on each flush.

        Either way the callback's content/reasoning/tool/artifact/extraction
        frames are accumulated into ordered blocks, the live bubble re-renders on
        a batched cadence, and the finished turn is rendered once at completion.

        When ``resume`` is given (HITL, Phase 4) the turn *continues* the paused
        assistant bubble: no new user/assistant bubbles are added, the blocks are
        seeded from ``resume_blocks`` (the paused turn's state), and the callback
        is driven with ``resume`` to answer the pending interrupt.
        """
        import time as _time

        from .chat import blocks_text as _blocks_text
        from .chat import has_text as _has_text
        from .chat import run_turn

        settings = dict(zip(self._chat_setting_names, setting_values))
        history = self.chat_history.get(sid)

        blocks = list(resume_blocks) if resume is not None and resume_blocks else []
        state = {"last": 0.0, "n": 0}
        user_json = self._chat_bubble_json(self._chat_user_bubble(query))

        if emit is None and self._native_stream:
            # ASGI full-state transport: keep a bounded, newest-first list of
            # rendered messages per session and push the whole list each flush.
            from dash import set_props
            msgs = self._session(sid).msgs
            if resume is None:
                msgs.insert(0, user_json)  # index 1 once the assistant is prepended
                msgs.insert(0, None)       # index 0 = the live assistant bubble
            # On resume, msgs[0] is already the paused assistant bubble.

            def _emit_start():
                _emit_replace0(streaming=True)

            def _emit_replace0(streaming):
                msgs[0] = self._chat_bubble_json(
                    self._chat_assistant_bubble(blocks, streaming=streaming))
                set_props("chat-messages", {"children": list(msgs)})
                if not streaming:
                    # Bound the transcript to the same window as history.
                    del msgs[2 * self.chat_history_size:]

            def _emit_canvas():
                set_props("chat-canvas", {"children": self._chat_canvas_render(sid)})
        else:
            # Flask op protocol (or a caller-supplied capture emit).
            _sio_emit = None
            if emit is None:
                from flask_socketio import emit as _sio_emit

                def emit(payload):
                    _sio_emit("chat_frames", payload, namespace="/", to=socket_id)

            def _emit_start():
                # Atomic user + empty assistant (index 0 = assistant).
                emit({"op": "start", "user": user_json,
                      "assistant": self._chat_bubble_json(
                          self._chat_assistant_bubble([], streaming=True))})

            def _emit_replace0(streaming):
                emit({"op": "replace0",
                      "value": self._chat_bubble_json(
                          self._chat_assistant_bubble(blocks, streaming=streaming))})

            def _emit_canvas():
                # Dedicated event so a trailing replace0 can't clobber the canvas
                # op on the shared chat_frames prop; each op is full canvas state,
                # so coalescing to the latest is harmless.
                payload = {"op": "canvas", "value": self._chat_canvas_render(sid)}
                if _sio_emit is not None:
                    _sio_emit("chat_canvas", payload, namespace="/", to=socket_id)
                else:
                    emit(payload)

        def _append_text(text):
            if blocks and blocks[-1].get("kind") == "text":
                blocks[-1]["text"] += text
            else:
                blocks.append({"kind": "text", "text": text})

        def _flush(force=False):
            now = _time.monotonic()
            if force or state["n"] >= 20 or (now - state["last"]) >= 0.05:
                _emit_replace0(streaming=True)
                state["last"] = now
                state["n"] = 0

        def _on_frame(frame):
            t = frame["type"]
            if t == "content":
                _append_text(frame["content"]); state["n"] += 1; _flush()
            elif t == "reasoning":
                blocks.append({"kind": "reasoning", "text": frame["content"]}); _flush(True)
            elif t == "tool_start":
                blocks.append({"kind": "tool", "id": frame["id"], "name": frame["name"],
                               "args": frame.get("args"), "result": None, "status": "running"})
                _flush(True)
            elif t == "tool_end":
                for b in blocks:
                    if b.get("kind") == "tool" and b.get("id") == frame["id"]:
                        b["result"] = frame.get("result"); b["status"] = "done"; break
                else:
                    blocks.append({"kind": "tool", "id": frame["id"], "name": frame["name"],
                                   "args": None, "result": frame.get("result"), "status": "done"})
                _flush(True)
            elif t == "artifact":
                blocks.append({"kind": "artifact", "content": frame["content"]}); _flush(True)
            elif t == "extraction":
                blocks.append({"kind": "extraction", "content": frame.get("content")}); _flush(True)
            elif t == "canvas" or t == "set_props":
                # Canvas mutations target the side canvas, not the transcript.
                self._chat_canvas_apply(sid, frame)
                _emit_canvas()
            elif t == "interrupt":
                blocks.append({
                    "kind": "interrupt",
                    "action_requests": frame.get("action_requests", []),
                    "allowed_decisions": frame.get("allowed_decisions", []),
                    "resolved": False,
                })
                _flush(True)
            elif t == "error":
                _append_text(("\n\n" if _has_text(blocks) else "")
                             + "**Error:** " + frame["message"])
                _flush(True)

        if resume is None:
            # Fresh turn: show the user's message and an empty assistant bubble.
            _emit_start()
        else:
            # Resume: the paused assistant bubble already exists; mark its
            # interrupt block decided and re-render in place (no new bubbles).
            for b in blocks:
                if b.get("kind") == "interrupt" and not b.get("resolved"):
                    b["resolved"] = True
                    b["decision"] = resume_decision
            _emit_replace0(streaming=True)

        result = run_turn(
            self.callback_fn, query,
            history=history, settings=settings, emit=_on_frame,
            friendly_error=lambda m: m,
            cancelled=lambda: self._chat_cancelled(sid),
            thread_id=sid, resume=resume, canvas=canvas_values,
        )

        if self._chat_cancelled(sid):
            _append_text(("\n\n" if _has_text(blocks) else "") + "_(stopped)_")

        # A turn that paused on an interrupt stays open awaiting a decision
        # (HITL). Only langstage agents can resume; for others the card is
        # frozen (informational) and the turn is treated as complete.
        pending = (result.get("interrupt") is not None
                   and self.is_langstage
                   and not self._chat_cancelled(sid))
        if pending:
            self._session(sid).pending = {"query": query, "blocks": blocks}
            _emit_replace0(streaming=False)          # card with live buttons
            return

        # Complete: freeze any interrupt card and record the turn.
        for b in blocks:
            if b.get("kind") == "interrupt":
                b["resolved"] = True
        self._session(sid).pending = None
        _emit_replace0(streaming=False)
        self.chat_history.append_turn(sid, query, _blocks_text(blocks))

    def _session(self, sid):
        """Return the ChatSession for ``sid``, creating and touching it.

        Opportunistically evicts sessions idle past the TTL (throttled to one
        sweep per interval), clearing their history too, so a long-running
        server never accumulates dead sessions.
        """
        from .chat import ChatSession
        now = time.monotonic()
        with self._sessions_lock:
            sess = self._sessions.get(sid)
            if sess is None:
                sess = self._sessions[sid] = ChatSession()
            sess.last_seen = now
            if (now - self._last_sweep > _SESSION_SWEEP_INTERVAL
                    and len(self._sessions) > 1):
                self._last_sweep = now
                stale = [k for k, s in self._sessions.items()
                         if k != sid and now - s.last_seen > _SESSION_TTL_SECONDS]
                for k in stale:
                    del self._sessions[k]
                    self.chat_history.clear(k)
            return sess

    def _chat_cancelled(self, sid):
        # Lightweight read (no touch/sweep) — called once per streamed frame.
        with self._sessions_lock:
            s = self._sessions.get(sid)
            return bool(s and s.cancel)

    def _resume_chat_turn(self, sid, socket_id, decision, value=None):
        """Answer a pending interrupt and continue the paused turn (HITL).

        Builds the langstage ``resume`` payload from ``decision`` and re-drives
        the callback, continuing the same assistant bubble from the paused
        turn's blocks. No-op (returns False) if nothing is pending.
        """
        pending = self._session(sid).pending
        if not pending:
            return False
        from .adapters.langstage import make_resume_input

        resume = make_resume_input([{"type": decision}], value=value)
        # Hand the continuation to the shared turn driver (no new bubbles).
        self._run_chat_turn(
            pending["query"], sid, socket_id, (),
            resume=resume, resume_decision=decision,
            resume_blocks=pending["blocks"],
        )
        return True

"""Native chat-mode app for Fast Dash (RFC #133).

The transport- and UI-*independent* chat core (frame grammar, history, turn
runner) lives in :mod:`fast_dash.chat`. This module holds the Dash-facing
**chat application** — layout, clientside/server callbacks, the streaming turn
driver, rich-frame rendering, HITL, and the assistant-driven canvas — as a mixin
that :class:`fast_dash.FastDash` inherits. It is split out to keep
``fast_dash.py`` focused on the general app; behavior is unchanged.
"""

import copy
import inspect
import json
import threading
import time

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
        # The callback that drives each chat turn. In chat mode it's the app's
        # own callback; a sidecar (chat= agent on a normal app) points it at the
        # agent instead, so _run_chat_turn is surface-agnostic.
        self._chat_fn = callback_fn
        # How the turn callback's input States are used: "settings" (chat mode,
        # passed to the callback as kwargs) or "ctx" (sidecar, surfaced as
        # ctx.inputs). Set to "ctx" by _init_chat_sidecar.
        self._chat_input_mode = "settings"
        self._chat_input_names = []
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

        self.submit_clicks = 0
        self.reset_clicks = 0
        self.app_initialized = False

    # ----- chat sidecar (chat=<agent> on an app callback) ---------------- #

    def _init_chat_sidecar(self):
        """Mount an independent chat agent on a normal app (``chat=<agent>``).

        Runs the same streaming turn machinery as chat mode, but the host app
        keeps its own callback, inputs, and outputs. The agent reads the app's
        live inputs via ``ctx.inputs`` and drives it with ``set_input`` /
        ``run_app`` frames; it shares nothing else with the app.
        """
        import inspect
        import threading
        import warnings

        from .chat import ChatHistory
        from .adapters.langstage import build_chat_callback, is_langstage_target

        agent = self._chat_agent
        # A LangGraph graph / "module:attr" spec is bridged to the frame grammar.
        if is_langstage_target(agent):
            agent = build_chat_callback(agent, getattr(self, "chat_extractors", None))
            self.is_langstage = True

        _params = list(inspect.signature(agent).parameters)
        if not _params or _params[0] != "query":
            raise TypeError(
                "A chat agent's first parameter must be named 'query' (it "
                "receives the composer text). Got signature (%s)."
                % ", ".join(_params)
            )

        # Per-session chat state, independent of the app's own callback.
        self.chat_history = ChatHistory(size=self.chat_history_size)
        self._sessions = {}
        self._sessions_lock = threading.Lock()
        self._last_sweep = 0.0
        self._chat_fn = agent
        self._chat_setting_names = []

        # The resolved chat_tools allowlist governs which drive verbs the agent
        # may use (set_input / run_app). It was trimmed at construction for
        # update_live and multi/steps apps (see _resolve_chat_tools).
        allow = getattr(self, "chat_tools_config", {}) or {}

        # Host-input read + drive is well-defined only on a single-function app.
        # A multi-function / steps app has several surfaces (tabs / steps), so
        # v1 mounts the *conversational* sidecar there (the agent streams and can
        # use its own tools) without reading or driving host inputs; that needs
        # its own active-surface design.
        if self.is_multi or self.is_steps:
            self._chat_input_mode = "none"
            self._chat_input_names = []
            self._sidecar_can_drive = False
            self._sidecar_no_drive_note = (
                "_(This app has multiple surfaces; the assistant can't set its "
                "inputs directly.)_")
        else:
            # The turn callback reads the host app's live inputs and hands them
            # to the agent as ctx.inputs, keyed by the host input ids — the same
            # keys the contract and set_input use (derived from inputs_with_ids,
            # not a positional guess off the callback signature, which would
            # mis-key an explicit inputs= that doesn't line up 1:1 with params).
            from .mcp import _stringify_id
            self._chat_input_mode = "ctx"
            self._chat_input_names = [
                _stringify_id(inp.id) for inp in self.inputs_with_ids
            ]
            # Secret (password) inputs are never shown to the agent — ctx.inputs
            # and the contract redact them — and never settable by it.
            self._sidecar_secret_inputs = {
                name for name, inp in zip(self._chat_input_names, self.inputs_with_ids)
                if type(getattr(inp, "component", None)).__name__ == "PasswordInput"
            }
            # The host app's input contract (types / options / bounds), computed
            # once — its shape is static, only the live values change per turn.
            self._sidecar_contract = self._sidecar_input_contract()
            # Drive is possible when the allowlist grants at least one drive
            # verb and the structural conditions hold. The allowlist was already
            # trimmed at construction (update_live drops set_input/run_app), so
            # a read-only agent simply has neither verb.
            self._sidecar_can_drive = (
                ("set_input" in allow or "run_app" in allow)
            )
            self._sidecar_no_drive_note = (
                None if self._sidecar_can_drive
                else "_(The assistant is read-only for this app.)_")

        self._drive_tick = 0                          # bumped per drive (ASGI flash)
        # Monotonic drive-payload sequence (RFC #133 D3 ordering on the drive
        # channel). Stamped on every payload the Flask reducers key on; the
        # fd-drive-seq store carries the last-applied value so a remount re-fire
        # of a stale data-chat_drive payload (seq <= stored) is skipped.
        self._drive_seq = 0
        self._drive_seq_lock = threading.Lock()
        self._register_chat_callbacks(register_chrome=False)
        self._register_chat_panel_collapse()          # collapse/expand affordance
        self._register_chat_drive_reducer()
        self._register_chat_content_reducer()         # set_output / set_layout ops
        self._register_chat_drive_flash()
        self._register_run_reset()                    # Run-always-wins reconcile

    def _register_chat_panel_collapse(self):
        """Wire the sidebar chat panel's collapse/expand affordance.

        The chat panel lives stacked under the inputs in the navbar and is
        collapsible: a chevron ActionIcon in the panel header toggles a
        className on the panel section (CSS collapses it to just the header row)
        and on the navbar root (so the inputs section reclaims the vertical
        space). Clientside so it is instant; persists nothing (default expanded).
        """
        from dash import Input, Output, State
        app = self.app

        app.clientside_callback(
            """
            function(n, collapsed) {
                if (!n) { return [dash_clientside.no_update,
                                  dash_clientside.no_update,
                                  dash_clientside.no_update]; }
                var now = !collapsed;
                var panelCls = now ? 'fd-chat-panel fd-chat-collapsed'
                                   : 'fd-chat-panel';
                var navCls = now ? 'fd-chat-sidebar fd-chat-inputs-expanded'
                                 : 'fd-chat-sidebar';
                var icon = now ? 'tabler:chevron-up' : 'tabler:chevron-down';
                return [now, panelCls, navCls, icon];
            }
            """,
            [Output("chat-panel-collapsed", "data"),
             Output("chat-sidebar-panel", "className"),
             Output("appshell", "className"),
             Output("chat-panel-collapse-icon", "icon")],
            Input("chat-panel-collapse", "n_clicks"),
            State("chat-panel-collapsed", "data"),
            prevent_initial_call=True,
        )

    def _sidecar_input_contract(self):
        """The host app's input contract (types / options / bounds) for the agent.

        Reuses the MCP describe path (``_describe_static_inputs``) so the sidecar
        agent and a headless MCP agent see the *same* contract — one source of
        truth. Falls back to bare names if that path is unavailable.
        """
        try:
            from .mcp import _describe_static_inputs
            contract = _describe_static_inputs(self, {})
        except Exception:                                 # noqa: BLE001
            contract = [{"id": n} for n in self._chat_input_names]
        # Never advertise secret (password) inputs to the agent.
        secret = getattr(self, "_sidecar_secret_inputs", set())
        return [e for e in contract if e.get("id") not in secret]

    def _sidecar_validate_input(self, name, value):
        """Return an actionable error string if ``set_input(name, value)`` is
        invalid, else ``None``. Rejects secret (password) inputs, unknown inputs,
        values outside an input's options, and values of the wrong type. Keeps a
        bad value from reaching the host callback (where it would raise a raw
        exception) and gives an LLM feedback to self-correct.
        """
        if name in getattr(self, "_sidecar_secret_inputs", set()):
            return "The assistant can't set the '%s' field." % name
        contract = {s.get("id"): s
                    for s in (getattr(self, "_sidecar_contract", None) or [])}
        spec = contract.get(name)
        if spec is None:
            valid = ", ".join(str(s.get("id")) for s in (self._sidecar_contract or []))
            return "No input named '%s'. Valid inputs: %s." % (name, valid or "none")
        options = spec.get("options")
        if options:
            if value not in options and str(value) not in [str(o) for o in options]:
                return "'%s' isn't a valid value for '%s'. Choose one of: %s." % (
                    value, name, ", ".join(str(o) for o in options))
            return None
        jtype = spec.get("type")
        if value is not None and jtype in ("integer", "number"):
            try:
                (int if jtype == "integer" else float)(value)
            except (TypeError, ValueError):
                return "'%s' isn't a valid %s for '%s'." % (value, jtype, name)
        if value is not None and jtype == "boolean" and not isinstance(value, bool) \
                and str(value).lower() not in ("true", "false", "0", "1"):
            return "'%s' isn't a valid boolean for '%s' (use true or false)." % (value, name)
        return None

    def _tool_refusal_note(self, verb):
        """The italic transcript note appended when a drive verb is disabled.

        Generalizes the old ``_sidecar_no_drive_note``: a per-verb refusal keyed
        on the chat_tools allowlist. When the specific ``verb`` is simply not in
        the allowlist (but the app is otherwise drivable, or another verb is
        allowed), emit the SPEC per-verb note. Otherwise fall back to the
        mode-specific note set at init (multi/steps, read-only, update_live).
        """
        allow = getattr(self, "chat_tools_config", {}) or {}
        has_any_drive_verb = "set_input" in allow or "run_app" in allow
        if verb not in allow and has_any_drive_verb:
            return "_( The %s capability is disabled on this app (chat_tools). )_" % verb
        note = getattr(self, "_sidecar_no_drive_note", None)
        if note:
            return note
        return "_( The %s capability is disabled on this app (chat_tools). )_" % verb

    def _sidecar_run_app(self, drive_inputs):
        """Run the host app's callback on ``drive_inputs``; return its outputs.

        Uses the same transform pipeline as the Run button, so a ``run_app``
        drive produces exactly what a manual Run would. Returns the list of
        output-component property values (figures, tables, text, ...).
        """
        return self._sidecar_run_app_with_result(drive_inputs)[0]

    def _sidecar_run_app_with_result(self, drive_inputs):
        """Run the callback; return ``(outputs, raw_return_values)``.

        ``outputs`` is the transformed list a Run pushes to the components;
        ``raw_return_values`` is the callback's own return (a figure, DataFrame,
        string, ...), which summarizes far more cleanly than its transformed form
        — the auto-agent's ``run_app`` tool needs it to tell the model what the
        run produced (closing the loop: the agent can now *see* its own run's
        output, not just trigger it). The single callback execution here is the
        run: the ``run_app`` frame it emits carries these outputs so the frame
        drain renders them instead of running the callback a second time.
        """
        from .utils import _transform_inputs, _transform_outputs
        raw = [drive_inputs.get(n) for n in self._chat_input_names]
        inputs = _transform_inputs(raw, self.input_tags, self.inputs_with_ids)
        # Serialize against a user's manual Run (A4): one host-callback execution
        # at a time across the Run thread and this chat thread.
        lock = getattr(self, "_host_callback_lock", None)
        if lock is None:
            lock = self._host_callback_lock = threading.Lock()
        with lock:
            self.state_counter += 1
            result = self.callback_fn(*inputs)
            result = list(result) if isinstance(result, tuple) else [result]
            outputs = _transform_outputs(result, self.output_tags,
                                         self.outputs_with_ids, self.state_counter)
            # Mirror a manual Run's server-side effect, so describe_app (over MCP)
            # and any state replay reflect what the agent produced.
            self.output_state = outputs
            self.latest_output_state = outputs
            self.app_initialized = True
        self._sidecar_sync_mcp_mirror(drive_inputs)
        return outputs, result

    def _output_slot_letters(self):
        """The stable mosaic slot letters for this app's outputs (sorted)."""
        lo = getattr(self, "layout_object", None)
        return list(getattr(lo, "output_slot_letters", []) or [])

    def _resolve_slot(self, slot):
        """Map a mosaic slot letter to its output index, or None if unknown.

        Case-insensitive (the mosaic engine uses uppercase letters, but an agent
        may say "a"); the letter position in the sorted slot list is the output
        index (outputs_with_ids / output_tags share that order).
        """
        letters = self._output_slot_letters()
        s = str(slot)
        for i, letter in enumerate(letters):
            if str(letter) == s or str(letter).lower() == s.lower():
                return i
        return None

    def _sidecar_set_output(self, index, value):
        """Transform ``value`` for output slot ``index`` the way a Run would.

        Returns ``(leaf_id, component_property, transformed_value)`` for the
        slot's leaf component, using the SAME per-output transform pipeline as
        _sidecar_run_app (figures/DataFrames/images converted server-side).
        """
        from .utils import _transform_outputs
        leaf = self.outputs_with_ids[index]
        tag = self.output_tags[index]
        self.state_counter += 1
        transformed = _transform_outputs(
            [value], [tag], [leaf], self.state_counter)[0]
        # Mirror a manual Run's server-side effect for this one slot, so
        # describe_app / state replay reflect what the agent produced.
        if isinstance(self.output_state, list) and index < len(self.output_state):
            self.output_state[index] = transformed
            self.latest_output_state = self.output_state
            self.app_initialized = True
        return leaf.id, leaf.component_property, transformed

    def _sidecar_sync_mcp_mirror(self, drive_inputs):
        """Reflect the agent's driven inputs into the MCP input mirror.

        Keeps ``describe_app`` accurate after the agent sets inputs, when the app
        also exposes an MCP surface (``mcp_server=True``). No-op otherwise.
        """
        state = getattr(self, "_mcp_state", None)
        if state is None:
            return
        try:
            from .mcp import _stringify_id
            for inp, name in zip(self.inputs_with_ids, self._chat_input_names):
                if name in drive_inputs:
                    state.inputs[_stringify_id(inp.id)] = drive_inputs[name]
        except Exception:                                 # noqa: BLE001
            pass

    @staticmethod
    def _json_safe(value):
        """A JSON-serializable form of a component value (figures -> dicts)."""
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            pass
        try:
            return json.loads(to_json_plotly(value))
        except Exception:
            return str(value)

    def _json_safe_list(self, values):
        return [self._json_safe(v) for v in values]

    # ----- per-session output mirror (Bug 3: set_layout preserves content) --- #

    def _mirror_outputs(self, sid, values):
        """Stash the full transformed output list for ``sid`` (manual Run / run_app).

        ``values`` is position-matched to ``outputs_with_ids``. Stored so a later
        set_layout re-mosaic can re-inject surviving slots' contents rather than
        reverting them to the build-time defaults.
        """
        if not sid or not self._sidecar_layout_enabled():
            return
        mirror = self._session(sid).output_mirror
        for i, val in enumerate(values):
            mirror[i] = val

    def _mirror_output_slot(self, sid, index, value):
        """Stash a single slot's transformed value for ``sid`` (set_output)."""
        if not sid or not self._sidecar_layout_enabled():
            return
        self._session(sid).output_mirror[index] = value

    def _mirrored_layout_tree(self, sid, tree):
        """Return ``tree`` with each surviving leaf carrying its mirrored value.

        ``rebuild_output_layout`` re-parents the canonical server leaf objects,
        whose props are the build-time defaults (empty figure/table). Pushing
        that as-is wipes whatever Run / set_output had rendered. This injects the
        per-session last-known value into each leaf in the SERIALIZED tree (a
        deep copy -- the canonical server objects are never mutated), keyed by
        leaf id. Missing entries are left at their default.
        """
        mirror = None
        if sid:
            mirror = self._session(sid).output_mirror
        if not mirror:
            return tree
        # index -> (leaf_id, component_property) for this app's outputs.
        by_index = {i: (o.id, o.component_property)
                    for i, o in enumerate(self.outputs_with_ids)}
        overrides = {}
        for index, value in mirror.items():
            spec = by_index.get(index)
            if spec is None:
                continue
            leaf_id, prop = spec
            overrides[leaf_id] = (prop, self._json_safe(value))
        if not overrides:
            return tree
        tree = copy.deepcopy(tree)     # never mutate the serialized canonical tree

        def _inject(node):
            if isinstance(node, dict):
                props = node.get("props")
                if isinstance(props, dict):
                    ov = overrides.get(props.get("id"))
                    if ov is not None:
                        props[ov[0]] = ov[1]
                    for v in props.values():
                        _inject(v)
            elif isinstance(node, list):
                for x in node:
                    _inject(x)

        _inject(tree)
        return tree

    def _run_reset_children(self, output_values):
        """The DEFAULT output layout tree with ``output_values`` in its leaves.

        Used by the server-atomic Run-reset (process_input): a manual Run on an
        agent-remosaiced app reasserts the DEFAULT layout, and this returns that
        default tree already carrying the Run's freshly computed outputs so the
        structure and content land in ONE response (no clientside swap can arrive
        later and blank the leaves). ``output_values`` is position-matched to
        ``outputs_with_ids``. Reuses rebuild_output_layout(default_mosaic) so the
        same leaf ids are re-parented, then injects the values into the
        serialized tree (a deep copy; canonical objects are never mutated).
        """
        lo = self.layout_object
        default_mosaic = getattr(self, "mosaic", None) or getattr(lo, "mosaic", None)
        tree, reason = lo.rebuild_output_layout(default_mosaic)
        if reason is not None:
            # Should not happen for the app's own default mosaic; leave the live
            # tree untouched rather than push a broken layout.
            raise ValueError(reason)
        serialized = self._chat_bubble_json(tree)
        by_index = {i: (o.id, o.component_property)
                    for i, o in enumerate(self.outputs_with_ids)}
        overrides = {}
        for index, value in enumerate(output_values or []):
            spec = by_index.get(index)
            if spec is None:
                continue
            leaf_id, prop = spec
            overrides[leaf_id] = (prop, self._json_safe(value))
        if not overrides:
            return serialized
        serialized = copy.deepcopy(serialized)

        def _inject(node):
            if isinstance(node, dict):
                props = node.get("props")
                if isinstance(props, dict):
                    ov = overrides.get(props.get("id"))
                    if ov is not None:
                        props[ov[0]] = ov[1]
                    for v in props.values():
                        _inject(v)
            elif isinstance(node, list):
                for x in node:
                    _inject(x)

        _inject(serialized)
        return serialized

    def _next_drive_seq(self):
        """Allocate the next monotonically increasing drive-payload sequence.

        Stamped onto every payload the Flask drive/content reducers key on so a
        replayed (stale) payload from a remount re-fire is skipped by the
        seq gate (RFC #133 D3 ordering on the drive channel). Thread-safe: a
        chat turn thread and a manual Run may both drive.
        """
        with self._drive_seq_lock:
            self._drive_seq += 1
            return self._drive_seq

    def _register_chat_drive_reducer(self):
        """Flask: write set_input/run_app pushes into the live components.

        ASGI drives components with ``set_props`` directly, so this is a no-op
        there. A single reducer writes the full input and output value lists
        (position-matched) into the host app's components on a 'drive' op.
        """
        if self._native_stream or not getattr(self, "_sidecar_can_drive", True):
            return
        from dash import Input, Output, State
        app = self.app

        in_outputs = [Output(inp.id, inp.component_property, allow_duplicate=True)
                      for inp in self.inputs_with_ids]
        out_outputs = [Output(out.id, out.component_property, allow_duplicate=True)
                       for out in self.outputs_with_ids]
        value_outputs = in_outputs + out_outputs
        if not value_outputs:
            return
        n_in, n_out = len(in_outputs), len(out_outputs)
        # On a run_app, also clear the pre-run 'fd-not-run' placeholder so the
        # agent's run refreshes the *view*, not just the inputs. The placeholder
        # is otherwise only cleared by a manual Run (submit_inputs.n_clicks),
        # which the sidecar never fires -- so outputs were written but stayed
        # hidden behind "Run to see results". The trailing output is the drive
        # seq store: bumped to the applied payload's seq so a later stale
        # re-fire (remount) is gated out (RFC #133 D3).
        drive_outputs = value_outputs + [
            Output("output-group-col", "className", allow_duplicate=True),
            Output("fd-drive-seq", "data", allow_duplicate=True),
        ]
        # tail = className + seq store; body values precede it.
        app.clientside_callback(
            """
            function(payload, appliedSeq) {
                var no = dash_clientside.no_update;
                var res = [];
                var i;
                // Ordering gate: skip a payload whose seq is not newer than the
                // last one applied on this channel. A remount re-fire replays
                // the last (stale) payload -- its seq is <= appliedSeq, so every
                // output stays no_update and the just-rendered values survive.
                var seq = (payload && typeof payload.seq === 'number') ? payload.seq : null;
                var stale = (seq !== null && appliedSeq !== null
                             && appliedSeq !== undefined && seq <= appliedSeq);
                if (!payload || payload.op !== 'drive' || stale) {
                    for (i = 0; i < %d; i++) { res.push(no); }
                    res.push(no);   // className
                    res.push(no);   // seq store
                    return res;
                }
                var inv = payload.inputs, ov = payload.outputs;
                for (i = 0; i < %d; i++) { res.push(inv ? inv[i] : no); }
                for (i = 0; i < %d; i++) { res.push(ov ? ov[i] : no); }
                res.push(payload.ran ? '' : no);   // reveal outputs on a run
                res.push(seq !== null ? seq : no); // record the applied seq
                return res;
            }
            """ % (n_in + n_out, n_in, n_out),
            drive_outputs,
            Input("socketio", "data-chat_drive"),
            State("fd-drive-seq", "data"),
            prevent_initial_call=True,
        )

    def _register_chat_content_reducer(self):
        """Flask: apply set_output / set_layout pushes to the output surface.

        A ``set_output`` op targets one leaf id known only at push time, so it is
        applied with ``dash_clientside.set_props`` (an arbitrary target) -- a
        single leaf *prop* hydrates fine that way.

        A ``layout`` op replaces the whole ``output-group-col.children`` with a
        fresh component tree. ``set_props`` does NOT hydrate a raw component-JSON
        children payload in this Dash version (Bug 2: the op arrived but the new
        mosaic never mounted), so the tree is returned as a real callback
        ``Output`` instead -- callback responses DO hydrate component JSON. The
        same op marks ``fd-layout-dirty`` true so the Run-reset knows to restore
        the default layout on the next manual Run (Bug 1).

        ASGI applies both ops server-side via ``set_props`` (its transcript
        children push is the proven precedent), so this reducer is Flask-only.
        """
        if self._native_stream or not getattr(self, "_sidecar_can_drive", True):
            return
        from dash import Input, Output, State
        app = self.app

        # A layout op returns real children (hydrates) + sets the dirty flag;
        # everything else is applied via set_props or left untouched. When the
        # app carries no layout plumbing there is no dirty store, so that Output
        # is omitted. The trailing output is the drive seq store, bumped to the
        # applied payload's seq so a stale re-fire is gated out (RFC #133 D3).
        layout_enabled = self._sidecar_layout_enabled()
        outputs = [Output("chat-content-sink", "data"),
                   Output("output-group-col", "children", allow_duplicate=True)]
        if layout_enabled:
            outputs.append(Output("fd-layout-dirty", "data", allow_duplicate=True))
        seq_idx = len(outputs)                     # index of the seq store output
        outputs.append(Output("fd-drive-seq", "data", allow_duplicate=True))
        n_out = len(outputs)

        app.clientside_callback(
            """
            function(payload, appliedSeq) {
                var no = dash_clientside.no_update;
                var res = [];
                var i;
                for (i = 0; i < %d; i++) { res.push(no); }
                if (!payload) { return res; }
                // Only set_output / layout ops belong to this reducer; a 'drive'
                // op is owned by the drive reducer (it bumps the seq there).
                var mine = (payload.op === 'set_output' || payload.op === 'layout');
                if (!mine) { return res; }
                // Ordering gate: skip a payload not newer than the last applied
                // on this channel (a remount re-fire replays the stale value).
                var seq = (typeof payload.seq === 'number') ? payload.seq : null;
                if (seq !== null && appliedSeq !== null && appliedSeq !== undefined
                        && seq <= appliedSeq) {
                    return res;
                }
                if (payload.op === 'set_output') {
                    var p = {};
                    p[payload.prop] = payload.value;
                    dash_clientside.set_props(payload.id, p);
                    dash_clientside.set_props('output-group-col', {className: ''});
                } else if (payload.op === 'layout') {
                    // Return the tree as a real Output so Dash hydrates it
                    // (set_props does not hydrate a component-JSON children
                    // payload). Reveal the outputs, and mark the layout dirty.
                    res[1] = payload.tree;
                    if (%s) { res[2] = true; }
                    dash_clientside.set_props('output-group-col', {className: ''});
                }
                if (seq !== null) { res[%d] = seq; }   // record the applied seq
                return res;
            }
            """ % (n_out, "true" if layout_enabled else "false", seq_idx),
            outputs,
            Input("socketio", "data-chat_drive"),
            State("fd-drive-seq", "data"),
            prevent_initial_call=True,
        )

    def _register_run_reset(self):
        """Run-reset: restore the default output layout on a manual Run -- but
        ONLY when the agent has actually re-mosaiced (Bug 1).

        This is now done SERVER-ATOMICALLY inside ``process_input``: a genuine
        Run on a layout-dirty app returns the restored default tree (with the
        Run's freshly computed outputs already injected into the leaves) AND the
        leaf values AND the cleared dirty flag in ONE response. The earlier
        standalone clientside children-swap raced the server leaf fill -- when
        the swap (which pushed the build-time *empty* default tree) landed after
        the fill, it blanked the just-rendered output (intermittent layout->Run
        clobber). Folding the restore into the Run response removes that race,
        because structure and content can no longer arrive out of order.

        Kept as a no-op hook (see :meth:`fast_dash.FastDash.register_callback_fn`
        for the server path) so the sidecar init sequence is unchanged.
        """
        return

    def _sidecar_layout_enabled(self):
        """True when this app should carry set_layout plumbing (store + reset).

        Gated on: a drivable chat sidecar whose allowlist includes set_layout
        and which actually has output slots to rearrange.
        """
        allow = getattr(self, "chat_tools_config", {}) or {}
        return bool(
            getattr(self, "has_chat_sidecar", False)
            and getattr(self, "_sidecar_can_drive", False)
            and "set_layout" in allow
            and self._output_slot_letters()
        )

    def _register_chat_drive_flash(self):
        """Flash the controls the agent just set, and pulse the output on a run.

        A brief highlight makes agent-driven changes legible — trust in an
        agent-driven app comes from *seeing* what it touched. Reads the drive
        signal from wherever the transport delivers it (Flask: the chat_drive
        socket event; ASGI: the chat-drive-tick store set via set_props).
        """
        if not getattr(self, "_sidecar_can_drive", False):
            return
        from dash import Input, Output
        app = self.app

        flash_js = """
        function(payload) {
            var no = window.dash_clientside.no_update;
            if (!payload) { return no; }
            var d = payload.op === 'drive' ? payload : payload;   // both shapes
            var pulse = function(el, cls) {
                if (!el) { return; }
                el.classList.remove(cls);
                void el.offsetWidth;                 // reflow -> restart anim
                el.classList.add(cls);
                setTimeout(function(){ el.classList.remove(cls); }, 1100);
            };
            (d.changed || []).forEach(function(id) {
                pulse(document.getElementById(id), 'fd-drive-flash');
            });
            if (d.ran) {
                document.querySelectorAll('.fd-output-card, .fd-output-content > *')
                    .forEach(function(c){ pulse(c, 'fd-drive-pulse'); });
            }
            return no;
        }
        """
        if self._native_stream:
            trigger = Input("chat-drive-tick", "data")
        else:
            trigger = Input("socketio", "data-chat_drive")
        app.clientside_callback(
            flash_js, Output("chat-drive-flash", "data"), trigger,
            prevent_initial_call=True,
        )

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
        ``interrupt``. During streaming, text stays raw and artifacts show a
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
                parts.append(self._chat_extraction_block(b, streaming))
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
    def _chat_reasoning_block(text, summary="Thinking"):
        """A collapsible 'thinking' block (native details/summary, no callback).

        ``summary`` labels the closed block; a langstage ``reflection`` event
        reuses this renderer with a "Reflection" label.
        """
        from dash import dcc, html
        return html.Details(
            [
                html.Summary(summary, className="fd-chat-reasoning-summary"),
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
                # Note: dash_table.DataTable does not accept className (dash 4.3),
                # so the class rides a wrapper Div instead.
                return html.Div(
                    dash_table.DataTable(
                        data=content.to_dict("records"),
                        columns=[{"name": str(c), "id": str(c)} for c in content.columns],
                        page_size=10, sort_action="native",
                        style_table={"overflowX": "auto"},
                    ),
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

    # ----- typed langstage events (extraction frames) -------------------- #

    def _chat_extraction_block(self, block, streaming=False):
        """Render one langstage typed-object event by its ``extracted_type``.

        Dispatches on ``extracted_type`` to a per-type Mantine card (todos,
        reflection, memory / skill / compression callouts, display_inline rich
        content). An unknown type falls back to a compact JSON card, so a typed
        event is NEVER dropped. During streaming a lightweight one-line status
        stands in; the full card materializes at turn completion (RFC D2).
        """
        etype = block.get("extracted_type") or ""
        data = block.get("data")
        if streaming:
            return self._chat_extraction_status(etype)
        if etype == "reflection":
            return self._chat_reasoning_block(self._as_reflection_text(data),
                                              summary="Reflection")
        if etype == "todos":
            return self._chat_todos_card(data)
        if etype == "memory_updated":
            return self._chat_memory_callout(data)
        if etype == "skill_loaded":
            return self._chat_skill_callout(data, loaded=True)
        if etype == "skill_event":
            return self._chat_skill_callout(data, loaded=False)
        if etype == "compression_summary":
            return self._chat_compression_callout(data)
        if etype == "display_inline":
            return self._chat_display_inline_block(data)
        return self._chat_extraction_fallback(etype, data)

    @staticmethod
    def _chat_extraction_status(etype):
        """A one-line live-bubble status for a mid-stream typed event."""
        from dash import html
        label = {
            "reflection": "thinking...",
            "todos": "todos updated",
            "memory_updated": "memory updated",
            "skill_loaded": "skill loaded",
            "skill_event": "skill updated",
            "compression_summary": "context compressed",
            "display_inline": "rendering...",
        }.get(etype, (etype or "event").replace("_", " "))
        return html.Div(label, className="fd-chat-extraction-status")

    @staticmethod
    def _as_reflection_text(data):
        """A reflection payload is a string (or a dict/other, coerced)."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return str(data.get("reflection", data))
        return str(data) if data is not None else ""

    def _chat_todos_card(self, data):
        """A task-list card: one row per todo with a status icon + text.

        Completed items are struck through; unknown statuses fall back to the
        pending look. ``data`` is a list of ``{"content"/"title", "status"}``.
        """
        from dash import html

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        items = data if isinstance(data, list) else []
        _ICON = {
            "completed": ("tabler:circle-check-filled", "green"),
            "done": ("tabler:circle-check-filled", "green"),
            "in_progress": ("tabler:loader-2", "blue"),
            "in-progress": ("tabler:loader-2", "blue"),
            "pending": ("tabler:circle", "gray"),
        }
        rows = []
        for it in items:
            if isinstance(it, dict):
                text = it.get("content") or it.get("title") or it.get("task") or ""
                status = str(it.get("status", "pending")).lower()
            else:
                text, status = str(it), "pending"
            icon, color = _ICON.get(status, ("tabler:circle", "gray"))
            done = status in ("completed", "done")
            spin = "fd-chat-tool-spin" if status in ("in_progress", "in-progress") else ""
            rows.append(dmc.Group(
                [
                    DashIconify(icon=icon, width=16, color=self._accent_color(color),
                                className=spin),
                    html.Span(str(text),
                              className="fd-chat-todo-text"
                              + (" fd-chat-todo-done" if done else "")),
                ],
                gap="xs", wrap="nowrap", className="fd-chat-todo-row",
            ))
        header = dmc.Group(
            [
                DashIconify(icon="tabler:list-check", width=16),
                html.Span("Tasks", className="fd-chat-extraction-title"),
            ],
            gap="xs", wrap="nowrap",
        )
        return dmc.Paper([header] + rows, withBorder=True, radius="sm", p="xs",
                         className="fd-chat-extraction fd-chat-todos")

    def _chat_memory_callout(self, data):
        """A compact one-line callout: 'Memory updated' + a short summary."""
        summary = ""
        if isinstance(data, dict):
            action = data.get("action")
            target = data.get("target")
            bits = [b for b in (action, target) if b]
            summary = " ".join(str(b) for b in bits)
        return self._chat_extraction_callout(
            "tabler:brain", "Memory updated", summary)

    def _chat_skill_callout(self, data, loaded=True):
        """A compact callout for a skill_loaded / skill_event typed event."""
        if loaded:
            chars = ""
            if isinstance(data, dict) and data.get("body_chars"):
                chars = "%s chars" % data["body_chars"]
            return self._chat_extraction_callout(
                "tabler:book", "Skill loaded", chars)
        # skill_event (create / update / delete).
        name = summary = ""
        if isinstance(data, dict):
            name = data.get("name") or ""
            action = data.get("action") or ""
            summary = (str(name) + (" (" + str(action) + ")" if action else "")).strip()
        title = "Skill " + (str(name) if name else "event")
        return self._chat_extraction_callout("tabler:tool", title, summary)

    def _chat_compression_callout(self, data):
        """A subtle divider-style callout: 'Context compressed' (+ details)."""
        from dash import dcc, html

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        head = dmc.Group(
            [
                DashIconify(icon="tabler:arrows-minimize", width=14),
                html.Span("Context compressed", className="fd-chat-extraction-title"),
            ],
            gap="xs", wrap="nowrap",
        )
        detail = None
        if isinstance(data, dict):
            parts = []
            if "before_tokens" in data and "after_tokens" in data:
                parts.append("%s -> %s tokens" % (data["before_tokens"], data["after_tokens"]))
            if data.get("ratio"):
                parts.append("%sx" % data["ratio"])
            if data.get("reason"):
                parts.append(str(data["reason"]))
            if parts:
                detail = dcc.Markdown(", ".join(parts),
                                      className="fd-chat-extraction-detail")
        body = [dmc.Divider(className="fd-chat-compression-divider"), head]
        if detail is not None:
            body.append(detail)
        return dmc.Paper(body, radius="sm", p="xs",
                         className="fd-chat-extraction fd-chat-compression")

    def _chat_extraction_callout(self, icon, title, summary=""):
        """A shared compact one-line callout chip: icon + title (+ summary)."""
        from dash import html

        import dash_mantine_components as dmc
        from dash_iconify import DashIconify

        row = [
            DashIconify(icon=icon, width=16),
            html.Span(str(title), className="fd-chat-extraction-title"),
        ]
        if summary:
            row.append(html.Span(str(summary), className="fd-chat-extraction-summary"))
        return dmc.Paper(
            dmc.Group(row, gap="xs", wrap="nowrap"),
            withBorder=True, radius="sm", p="xs",
            className="fd-chat-extraction fd-chat-callout",
        )

    def _chat_display_inline_block(self, data):
        """Render a display_inline payload inline, like an artifact.

        The DisplayInlineExtractor returns ``{"display_type", "data", "title",
        "status"}``. ``markdown`` / ``html`` / ``text`` render as text; a
        ``table`` (list of dicts or a DataFrame-able) and any figure-shaped
        payload route through the same artifact renderer figures/frames use, so
        rich content lands inline exactly like an ``artifact`` frame.
        """
        from dash import dcc, html

        import dash_mantine_components as dmc

        if not isinstance(data, dict):
            # A raw value (not the {display_type, data} envelope): render it as
            # an artifact (figure / frame / image / text fallback).
            return self._chat_artifact_block(data, streaming=False)

        dtype = str(data.get("display_type", "")).lower()
        payload = data.get("data")
        title = data.get("title")
        header = ([html.Div(str(title), className="fd-chat-extraction-title")]
                  if title else [])

        if dtype in ("markdown", "md", "text", ""):
            body = dcc.Markdown(str(payload if payload is not None else ""),
                                className="fd-chat-text", link_target="_blank")
        elif dtype in ("table", "dataframe"):
            body = self._chat_display_table(payload)
        elif dtype in ("figure", "plotly", "chart"):
            body = self._chat_display_figure(payload)
        else:
            # json / image / html and anything else: hand the payload to the
            # artifact renderer, which figures out the best component.
            body = self._chat_artifact_block(payload, streaming=False)

        return dmc.Paper(header + [body], radius="sm", p="xs",
                         className="fd-chat-extraction fd-chat-display-inline")

    def _chat_display_table(self, payload):
        """Render a display_inline table payload as a DataTable (best-effort)."""
        try:
            import pandas as pd
            if not isinstance(payload, pd.DataFrame):
                payload = pd.DataFrame(payload)
            return self._chat_artifact_block(payload, streaming=False)
        except Exception:
            return self._chat_artifact_block(payload, streaming=False)

    def _chat_display_figure(self, payload):
        """Render a display_inline figure payload as a dcc.Graph (best-effort).

        The payload may be a live ``go.Figure`` (route to the artifact renderer)
        or a plotly figure dict (``{"data": [...], "layout": {...}}``), which the
        artifact renderer does not recognize -- wrap it in a Graph directly.
        """
        from dash import dcc
        try:
            import plotly.graph_objects as go
            if isinstance(payload, go.Figure):
                return self._chat_artifact_block(payload, streaming=False)
            if isinstance(payload, dict) and ("data" in payload or "layout" in payload):
                return dcc.Graph(figure=payload, className="fd-chat-artifact",
                                 style={"width": "100%"})
        except Exception:
            pass
        return self._chat_artifact_block(payload, streaming=False)

    def _chat_extraction_fallback(self, etype, data):
        """Unknown extracted_type -> a compact, collapsible JSON card.

        The safety net that guarantees a typed event is never dropped: it shows
        the raw payload in a collapsible pre block labeled by its type.
        """
        from dash import html
        return html.Details(
            [
                html.Summary(str(etype or "event"),
                             className="fd-chat-reasoning-summary"),
                html.Pre(self._chat_short_json(data),
                         className="fd-chat-tool-result"),
            ],
            className="fd-chat-reasoning fd-chat-extraction-fallback",
        )

    @staticmethod
    def _accent_color(color):
        """Pass a Mantine color name through (kept as a hook for theming)."""
        return color

    def _chat_bubble_json(self, component):
        """Serialize a Dash component to the plotly-json the reducer inserts."""
        return json.loads(to_json_plotly(component))

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
        self.app.layout = app_layout.generate_chat_layout(
            has_settings=bool(self.inputs_with_ids),
            stream_event_names=event_names,
            native_stream=self._native_stream,
        )

    def _register_chat_callbacks(self, register_chrome=True):
        from dash import Input, Output, State
        from dash.exceptions import PreventUpdate

        from .chat import ChatFrameError

        app = self.app

        # Shared chrome callbacks (dark-mode toggle, burger, About). A sidecar
        # rides a normal app that already registered these, so it opts out.
        if register_chrome and not self.minimal:
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
        # "none" (multi/steps sidecar) reads no host inputs; "settings" (chat
        # mode) and "ctx" (single-function sidecar) read inputs_with_ids.
        setting_states = (
            []
            if self._chat_input_mode == "none"
            else [State(inp.id, inp.component_property) for inp in self.inputs_with_ids]
        )
        turn_states = [State("chat-session", "data")]
        if not self._native_stream:
            turn_states.append(State("socketio", "socketId"))
        turn_states += setting_states

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
            # Flask: rest = (socket_id, *state_values); ASGI: rest = state_values.
            if self._native_stream:
                socket_id = None
                state_values = tuple(rest)
            else:
                socket_id = rest[0] if rest else None
                state_values = tuple(rest[1:])
            # In chat mode the input states are settings passed to the callback
            # as kwargs; in a sidecar (chat= agent on a normal app) they are the
            # host app's live inputs, surfaced to the agent via ctx.inputs.
            if self._chat_input_mode == "ctx":
                app_inputs = dict(zip(self._chat_input_names, state_values))
                setting_values = ()
            else:
                app_inputs = None
                setting_values = state_values

            # A Run (app-first drawer mode) drives the callback from the settings
            # with no chat message: query is empty, output goes to the canvas
            # only (no transcript entry).
            is_run = bool(submit.get("run")) if submit else False
            if not submit or (not is_run and not (submit.get("q") or "").strip()):
                raise PreventUpdate
            query = "" if is_run else submit["q"].strip()
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
                                    to_transcript=not is_run, app_inputs=app_inputs)
                return False, []
            except ChatFrameError as e:
                # A malformed frame is a developer bug worth surfacing — but at
                # the callback boundary it must not wedge the UI (an uncaught
                # raise would leave chat-streaming stuck True, disabling the
                # composer until a refresh). Surface it as a notification.
                return False, _get_error_notification_component(
                    "Chat callback yielded a malformed frame: %s" % e)
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
                except ChatFrameError as e:
                    # Same boundary guard as _chat_turn: never wedge the UI.
                    return False, _get_error_notification_component(
                        "Chat callback yielded a malformed frame: %s" % e)
                finally:
                    with self._sessions_lock:
                        sess.active = False
                        sess.cancel = False

    def _run_chat_turn(self, query, sid, socket_id, setting_values, emit=None,
                       resume=None, resume_decision=None, resume_blocks=None,
                       to_transcript=True, app_inputs=None):
        """Drive one chat turn, streaming its blocks to the browser.

        Two transports, one turn-driver:

        * **Flask** (default): incremental ops (``start`` / ``replace0``) are
          pushed as discrete socket.io events; a clientside reducer applies them
          to the message list. ``emit`` may be supplied to capture these ops.
        * **ASGI** (``_native_stream``): ``set_props`` is a latest-value-wins
          transport, so incremental ops would be lost to coalescing. Instead the
          server owns the per-session transcript and pushes the *full* rendered
          message list straight to ``chat-messages.children`` on each flush.

        Either way the callback's content/reasoning/tool/artifact frames are
        accumulated into ordered blocks, the live bubble re-renders on a batched
        cadence, and the finished turn is rendered once at completion.

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
        # Sidecar app-drive: set_input frames accumulate over the turn-start
        # input values, and run_app applies them through the host callback.
        drive_inputs = dict(app_inputs or {})       # REAL values, for run_app
        drive_changed = []                           # input names set this turn
        # What the agent sees as ctx.inputs — with secret (password) values
        # redacted so they never reach the LLM. run_app still uses drive_inputs.
        _secret = getattr(self, "_sidecar_secret_inputs", None)
        ctx_inputs = ({k: ("***" if k in _secret else v)
                       for k, v in (app_inputs or {}).items()}
                      if _secret else app_inputs)

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

            def _emit_drive(inputs=None, outputs=None, changed=None, ran=False):
                # ASGI: push input/output component values directly via set_props.
                if inputs is not None:
                    for inp, val in zip(self.inputs_with_ids, inputs):
                        set_props(inp.id, {inp.component_property: val})
                if outputs is not None:
                    for out, val in zip(self.outputs_with_ids, outputs):
                        set_props(out.id, {out.component_property: val})
                if ran:
                    # Clear the pre-run placeholder so the run reveals the outputs
                    # (parity with the Flask reducer; otherwise only a manual Run
                    # clears it). See _register_chat_drive_reducer.
                    set_props("output-group-col", {"className": ""})
                # Flash affordance: bump a tick store so a clientside callback
                # highlights the just-changed controls / pulses the output.
                self._drive_tick += 1
                set_props("chat-drive-tick", {"data": {
                    "changed": list(changed or []), "ran": bool(ran),
                    "n": self._drive_tick}})

            def _emit_set_output(leaf_id, prop, value):
                # ASGI: push the single slot's transformed value straight onto
                # the leaf component, then flash the output.
                set_props(leaf_id, {prop: value})
                set_props("output-group-col", {"className": ""})
                self._drive_tick += 1
                set_props("chat-drive-tick", {"data": {
                    "changed": [], "ran": True, "n": self._drive_tick}})

            def _emit_layout(tree):
                # ASGI: full-state push of the re-mosaiced output tree
                # (established pattern: replace output-group-col.children, the
                # same set_props children push proven for chat-messages).
                set_props("output-group-col", {"children": tree})
                set_props("output-group-col", {"className": ""})
                # Mark the layout dirty so a subsequent manual Run reasserts the
                # default layout (Bug 1); the store exists only when set_layout
                # plumbing is enabled.
                if self._sidecar_layout_enabled():
                    set_props("fd-layout-dirty", {"data": True})
                self._drive_tick += 1
                set_props("chat-drive-tick", {"data": {
                    "changed": [], "ran": True, "n": self._drive_tick}})
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

            def _emit_drive(inputs=None, outputs=None, changed=None, ran=False):
                # Flask: emit a full-state drive op; a clientside reducer writes
                # the values into the live input/output components and flashes
                # the changed controls.
                payload = {
                    "op": "drive",
                    "inputs": (self._json_safe_list(inputs)
                               if inputs is not None else None),
                    "outputs": (self._json_safe_list(outputs)
                                if outputs is not None else None),
                    "changed": list(changed or []),
                    "ran": bool(ran),
                    "seq": self._next_drive_seq(),
                }
                if _sio_emit is not None:
                    _sio_emit("chat_drive", payload, namespace="/", to=socket_id)
                else:
                    emit(payload)

            def _emit_set_output(leaf_id, prop, value):
                # Flask: a 'set_output' op the drive reducer applies to the leaf
                # via dash_clientside.set_props (arbitrary target, no declared
                # Output). The value is JSON-safe (figures/frames converted).
                payload = {"op": "set_output", "id": leaf_id, "prop": prop,
                           "value": self._json_safe(value), "ran": True,
                           "seq": self._next_drive_seq()}
                if _sio_emit is not None:
                    _sio_emit("chat_drive", payload, namespace="/", to=socket_id)
                else:
                    emit(payload)

            def _emit_layout(tree):
                # Flask: a 'layout' op carrying the re-mosaiced tree as Dash
                # component JSON; the reducer sets output-group-col.children.
                payload = {"op": "layout", "tree": tree, "ran": True,
                           "seq": self._next_drive_seq()}
                if _sio_emit is not None:
                    _sio_emit("chat_drive", payload, namespace="/", to=socket_id)
                else:
                    emit(payload)

        def _append_text(text):
            if blocks and blocks[-1].get("kind") == "text":
                blocks[-1]["text"] += text
            else:
                blocks.append({"kind": "text", "text": text})

        def _flush(force=False):
            if not to_transcript:
                return                       # a Run: canvas only, no transcript
            now = _time.monotonic()
            if force or state["n"] >= 20 or (now - state["last"]) >= 0.05:
                _emit_replace0(streaming=True)
                state["last"] = now
                state["n"] = 0

        def _dispatch_frame(frame):
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
                # A langstage typed-object event (todos / reflection / display_inline
                # / skill / memory / compression / unknown). Joins the block list
                # and is rendered server-side by _chat_extraction_block, so both
                # transports (Flask op + ASGI full-state) show the same typed card.
                blocks.append({"kind": "extraction",
                               "extracted_type": frame.get("extracted_type", ""),
                               "tool_name": frame.get("tool_name", ""),
                               "data": frame.get("data")})
                _flush(True)
            elif t == "set_input" and self.has_chat_sidecar:
                # Per-verb gating: set_input is honored only if it's in the
                # chat_tools allowlist. A refusal appends an italic note.
                if "set_input" not in (getattr(self, "chat_tools_config", {}) or {}) \
                        or not self._sidecar_can_drive:
                    _append_text(("\n\n" if _has_text(blocks) else "")
                                 + self._tool_refusal_note("set_input"))
                    _flush(True)
                else:
                    err = self._sidecar_validate_input(frame["name"], frame["value"])
                    if err:
                        # Refuse: leave the (still-valid) current value in place
                        # and tell the agent why, so run_app stays safe.
                        _append_text(("\n\n" if _has_text(blocks) else "")
                                     + "_(" + err + ")_")
                        _flush(True)
                    else:
                        # Set a host-app input; reflect it in the live control
                        # and flash it.
                        drive_inputs[frame["name"]] = frame["value"]
                        if frame["name"] not in drive_changed:
                            drive_changed.append(frame["name"])
                        _emit_drive(
                            inputs=[drive_inputs.get(n)
                                    for n in self._chat_input_names],
                            changed=[frame["name"]])
            elif t == "run_app" and self.has_chat_sidecar:
                if "run_app" not in (getattr(self, "chat_tools_config", {}) or {}) \
                        or not self._sidecar_can_drive:
                    _append_text(("\n\n" if _has_text(blocks) else "")
                                 + self._tool_refusal_note("run_app"))
                    _flush(True)
                else:
                    # Run the host app on the current inputs, push outputs. Send
                    # the full input list too: socketio's data-chat_drive prop is
                    # latest-value-wins, so a trailing run_app must carry the
                    # inputs set earlier this turn or they'd be clobbered.
                    try:
                        if frame.get("ran"):
                            # The auto-agent's run_app tool already ran the
                            # callback (to summarize its result for the model) and
                            # carried the outputs on the frame -- render them,
                            # don't run a second time.
                            outputs = frame.get("outputs") or []
                        else:
                            outputs = self._sidecar_run_app(drive_inputs)
                        # Mirror the run's outputs so a later set_layout keeps
                        # them (Bug 3).
                        self._mirror_outputs(sid, outputs)
                        _emit_drive(
                            inputs=[drive_inputs.get(n)
                                    for n in self._chat_input_names],
                            outputs=outputs,
                            changed=list(drive_changed), ran=True)
                    except Exception as exc:                  # noqa: BLE001
                        _append_text(("\n\n" if _has_text(blocks) else "")
                                     + "**Error running the app:** " + str(exc))
                        _flush(True)
            elif t == "set_output" and self.has_chat_sidecar:
                # Render one value into a slot through the Run transform pipeline
                # and push it per-client. Gated by the chat_tools allowlist.
                if "set_output" not in (getattr(self, "chat_tools_config", {}) or {}) \
                        or not self._sidecar_can_drive:
                    _append_text(("\n\n" if _has_text(blocks) else "")
                                 + self._tool_refusal_note("set_output"))
                    _flush(True)
                else:
                    idx = self._resolve_slot(frame.get("slot"))
                    if idx is None:
                        valid = ", ".join(self._output_slot_letters()) or "none"
                        _append_text(("\n\n" if _has_text(blocks) else "")
                                     + "_( No output slot '%s'. Valid slots: %s. )_"
                                     % (frame.get("slot"), valid))
                        _flush(True)
                    else:
                        try:
                            leaf_id, prop, val = self._sidecar_set_output(
                                idx, frame.get("value"))
                            # Mirror this slot so a later set_layout keeps it
                            # (Bug 3).
                            self._mirror_output_slot(sid, idx, val)
                            _emit_set_output(leaf_id, prop, val)
                        except Exception as exc:              # noqa: BLE001
                            _append_text(("\n\n" if _has_text(blocks) else "")
                                         + "**Error setting the output:** " + str(exc))
                            _flush(True)
            elif t == "set_layout" and self.has_chat_sidecar:
                # Re-mosaic the existing output slots. Gated by the allowlist;
                # an invalid mosaic appends the friendly reason as a refusal note.
                if "set_layout" not in (getattr(self, "chat_tools_config", {}) or {}) \
                        or not self._sidecar_can_drive:
                    _append_text(("\n\n" if _has_text(blocks) else "")
                                 + self._tool_refusal_note("set_layout"))
                    _flush(True)
                else:
                    tree, reason = self.layout_object.rebuild_output_layout(
                        frame.get("mosaic"))
                    if reason is not None:
                        _append_text(("\n\n" if _has_text(blocks) else "")
                                     + "_(" + reason + ")_")
                        _flush(True)
                    else:
                        # Inject the per-session last-known output values into the
                        # serialized tree so surviving slots keep their content
                        # (Bug 3) -- the rebuilt tree re-parents build-time-default
                        # leaves, which would otherwise wipe the current output.
                        pushed = self._mirrored_layout_tree(
                            sid, self._chat_bubble_json(tree))
                        _emit_layout(pushed)
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

        def _drain_tail():
            # Drain the agent_tools per-turn buffer (a list of frame dicts a
            # @tool emitted while running inside the graph). Returns [] when the
            # [agent] extra is absent or nothing was buffered; never raises.
            try:
                from .agent_tools import drain_frames
            except ImportError:
                return []
            try:
                return drain_frames() or []
            except Exception:                             # noqa: BLE001
                return []                                 # a drain error never kills the turn

        def _on_frame(frame):
            # Dispatch the agent's own frame, then drain any frames buffered by
            # fast_dash.agent_tools during graph execution. langchain @tool
            # functions run *inside* the graph (not on the frame stream), so
            # their set_input / set_output / set_layout effects are queued in a
            # per-turn contextvar buffer and surfaced here (RFC #145 Phase C).
            _dispatch_frame(frame)
            for buffered in _drain_tail():
                _dispatch_frame(buffered)

        if not to_transcript:
            pass                              # a Run: no user/assistant bubbles
        elif resume is None:
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

        # Open a per-turn frame buffer so any set_input / run_app / set_output /
        # set_layout / artifact frame an agent_tools @tool emits while it runs
        # *inside* the agent graph lands somewhere the drain hook can pick up
        # (the tools don't sit on the frame stream -- they run in the graph's
        # executor). A ContextVar buffer propagates into the tasks langgraph
        # spawns, so a tool call writes to the turn that opened it. No-op when
        # agent_tools isn't importable (the [agent] extra is absent) -- a plain
        # (query, ctx) chat agent never calls emit_frame anyway.
        try:
            from .agent_tools import turn_buffer as _turn_buffer
        except ImportError:
            import contextlib
            _turn_buffer = contextlib.nullcontext

        from .chat import ChatFrameError
        try:
            # Seed the drive tools with THIS turn's input dict (same object the
            # frame drain mutates), so an auto-agent's run_app runs on the inputs
            # it just staged and can report the result. nullcontext ignores the
            # arg when the [agent] extra is absent.
            with _turn_buffer(drive_inputs):
                result = run_turn(
                    self._chat_fn, query,
                    history=history, settings=settings, emit=_on_frame,
                    friendly_error=lambda m: m,
                    cancelled=lambda: self._chat_cancelled(sid),
                    thread_id=sid, resume=resume, app_inputs=ctx_inputs,
                    app_input_specs=getattr(self, "_sidecar_contract", None),
                )
                # Drain any frames the final agent step emitted after its last
                # streamed frame (e.g. a tool that ran with no trailing agent
                # event to trigger the per-frame drain in _on_frame).
                try:
                    for _buffered in (_drain_tail() or []):
                        _dispatch_frame(_buffered)
                except Exception:                         # noqa: BLE001
                    pass
        except ChatFrameError as e:
            # A malformed frame is a developer bug worth surfacing loudly — but
            # it must not abort the turn mid-stream (that would strand the
            # streaming bubble and, at the callback boundary, wedge the
            # composer). Keep the partial reply, surface the bug in the
            # transcript, and finish the turn normally.
            _append_text(("\n\n" if _has_text(blocks) else "")
                         + "**Malformed chat frame:** " + str(e))
            _flush(True)
            result = {"content": "", "frames": [], "interrupt": None}

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

        # A Run (to_transcript=False) only updates the canvas — no transcript
        # render, no history. The canvas frames already streamed via _emit_canvas.
        if not to_transcript:
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

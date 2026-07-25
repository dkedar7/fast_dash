/* Fast Dash: drag-to-resize the input sidebar (progressive, no-op without it).

   Mantine's AppShell drives BOTH the navbar's own width and the main pane's
   offset from two CSS variables it writes inline on the shell
   (`--app-shell-navbar-width` / `--app-shell-navbar-offset`), and it builds the
   collapse transform out of the width var too. So setting those two vars during
   a drag moves the sidebar, shifts the output pane with it, and keeps the
   collapse animation correct -- no server round-trip, no layout thrash.

   dmc recomputes those vars from the `navbar` prop whenever the shell
   re-renders (the toggle callback returns a fresh dict), which would snap a
   dragged sidebar back to its default. On release we therefore persist the
   width into a dcc.Store that the toggle callback reads back, so the width
   survives a collapse/expand cycle. */
(function () {
  var MIN_WIDTH = 200;                 // narrower than this and controls clip
  var MAX_FRACTION = 0.5;              // issue #80: at most half the screen
  var SHELL_ID = "appshell";
  var STORE_ID = "fd-sidebar-width";

  function maxWidth() {
    return Math.round(window.innerWidth * MAX_FRACTION);
  }

  function clampWidth(px) {
    return Math.max(MIN_WIDTH, Math.min(px, maxWidth()));
  }

  function applyWidth(shell, px) {
    // Width drives the navbar box AND (via calc) the collapse transform;
    // offset drives the main pane. Both must move together or the output
    // ends up shifted under the sidebar.
    shell.style.setProperty("--app-shell-navbar-width", px + "px");
    shell.style.setProperty("--app-shell-navbar-offset", px + "px");
  }

  function persistWidth(px) {
    // Let the server-side toggle callback reuse this width instead of the
    // hardcoded default the next time it re-renders the shell.
    try {
      if (window.dash_clientside && window.dash_clientside.set_props) {
        window.dash_clientside.set_props(STORE_ID, { data: px });
      }
    } catch (e) { /* persistence is best-effort; the drag still applied */ }
  }

  function startDrag(handle, ev) {
    var shell = document.getElementById(SHELL_ID);
    if (!shell) { return; }
    // Below the breakpoint the navbar is full-width and dragging is meaningless
    // (CSS hides the handle there too; this is the belt-and-braces check).
    if (window.innerWidth <= 768) { return; }

    ev.preventDefault();
    document.body.classList.add("fd-resizing");

    var shellLeft = shell.getBoundingClientRect().left;

    function onMove(e) {
      var px = clampWidth(Math.round(e.clientX - shellLeft));
      applyWidth(shell, px);
      handle.setAttribute("aria-valuenow", String(px));
    }

    function onUp() {
      document.body.classList.remove("fd-resizing");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      var current = parseInt(
        shell.style.getPropertyValue("--app-shell-navbar-width"), 10);
      if (!isNaN(current)) { persistWidth(current); }
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function wire(handle) {
    if (handle.getAttribute("data-fd-resize")) { return; }
    handle.setAttribute("data-fd-resize", "1");
    handle.addEventListener("pointerdown", function (ev) { startDrag(handle, ev); });

    // Keyboard access: the handle is focusable, so arrows nudge it and the
    // sidebar stays operable without a pointer.
    handle.addEventListener("keydown", function (ev) {
      var step = ev.shiftKey ? 50 : 10;
      var delta = ev.key === "ArrowLeft" ? -step : ev.key === "ArrowRight" ? step : 0;
      if (!delta) { return; }
      var shell = document.getElementById(SHELL_ID);
      if (!shell) { return; }
      ev.preventDefault();
      var now = parseInt(
        shell.style.getPropertyValue("--app-shell-navbar-width"), 10) || MIN_WIDTH;
      var px = clampWidth(now + delta);
      applyWidth(shell, px);
      handle.setAttribute("aria-valuenow", String(px));
      persistWidth(px);
    });
  }

  function scan() {
    document.querySelectorAll(".fd-sidebar-resizer").forEach(wire);
  }

  // The handle arrives with Dash's first render and again after any re-render
  // that replaces the navbar, so keep watching rather than wiring once.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", scan);
  } else {
    scan();
  }
  new MutationObserver(scan).observe(document.documentElement, {
    childList: true, subtree: true,
  });

  // A resize that shrinks the viewport can leave the sidebar wider than the
  // 50% cap, so re-clamp against the new viewport.
  window.addEventListener("resize", function () {
    var shell = document.getElementById(SHELL_ID);
    if (!shell) { return; }
    var now = parseInt(
      shell.style.getPropertyValue("--app-shell-navbar-width"), 10);
    if (isNaN(now)) { return; }
    var px = clampWidth(now);
    if (px !== now) { applyWidth(shell, px); persistWidth(px); }
  });
})();

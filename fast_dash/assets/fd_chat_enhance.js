/* Fast Dash chat enhancements (progressive, no-op outside chat surfaces):
   adds a hover "Copy" button to code blocks in the transcript. */
(function () {
  function addCopyButtons(root) {
    root.querySelectorAll(".fd-chat-bubble pre:not([data-fd-copy])").forEach(function (pre) {
      pre.setAttribute("data-fd-copy", "1");
      var btn = document.createElement("button");
      btn.className = "fd-code-copy";
      btn.type = "button";
      btn.textContent = "Copy";
      btn.addEventListener("click", function () {
        var code = pre.querySelector("code") || pre;
        var text = code.innerText.replace(/\s*Copy\s*$/, "");
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(function () {
            btn.textContent = "Copied";
            setTimeout(function () { btn.textContent = "Copy"; }, 1200);
          });
        }
      });
      pre.appendChild(btn);
    });
  }

  function focusComposer() {
    var root = document.getElementById("chat-input");
    if (!root) { return; }
    var ta = root.tagName === "TEXTAREA" ? root : root.querySelector("textarea");
    if (ta) { setTimeout(function () { ta.focus(); }, 60); }
  }

  function wireSidecarA11y() {
    // Opening the sidecar (or the drawer expand button) focuses the composer;
    // Esc closes the sidecar aside. Progressive — only where those ids exist.
    ["chat-sidecar-toggle", "chat-open"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.dataset.fdFocusBound) {
        el.dataset.fdFocusBound = "1";
        el.addEventListener("click", focusComposer);
      }
    });
    if (!document.body.dataset.fdEscBound) {
      document.body.dataset.fdEscBound = "1";
      document.addEventListener("keydown", function (e) {
        if (e.key !== "Escape") { return; }
        var open = document.getElementById("chat-sidecar-open");
        var close = document.getElementById("chat-sidecar-close");
        var aside = document.getElementById("chat-aside");
        // Only act when a sidecar aside is actually open on screen.
        if (close && aside && aside.offsetParent !== null) { close.click(); }
      });
    }
  }

  function init() {
    var list = document.getElementById("chat-messages");
    if (!list) { return false; }
    addCopyButtons(list);
    wireSidecarA11y();
    new MutationObserver(function () {
      addCopyButtons(list);
      wireSidecarA11y();
    }).observe(list, { childList: true, subtree: true });
    return true;
  }

  // chat-messages mounts after Dash boots; retry briefly, then give up (this
  // page has no chat surface).
  if (!init()) {
    var tries = 0;
    var iv = setInterval(function () {
      if (init() || ++tries > 40) { clearInterval(iv); }
    }, 250);
  }
})();

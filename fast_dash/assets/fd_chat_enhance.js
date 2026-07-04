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

  function init() {
    var list = document.getElementById("chat-messages");
    if (!list) { return false; }
    addCopyButtons(list);
    new MutationObserver(function () { addCopyButtons(list); })
      .observe(list, { childList: true, subtree: true });
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

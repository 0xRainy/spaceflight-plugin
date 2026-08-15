/* Live countdown for the hero terminal mock (client-side only). */
(function () {
  "use strict";

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function formatRemaining(ms) {
    if (ms < 0) ms = 0;
    var total = Math.floor(ms / 1000);
    var d = Math.floor(total / 86400);
    var h = Math.floor((total % 86400) / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    if (d > 0) {
      return "T-" + d + "d:" + pad(h) + "h:" + pad(m) + "m:" + pad(s) + "s";
    }
    if (h > 0) {
      return "T-" + pad(h) + "h:" + pad(m) + "m:" + pad(s) + "s";
    }
    return "T-" + pad(m) + "m:" + pad(s) + "s";
  }

  function tick() {
    var el = document.getElementById("live-countdown");
    if (!el) return;
    var target = Number(el.getAttribute("data-target-ms") || "0");
    if (!target) {
      // ~36h from first page load
      target = Date.now() + 36 * 3600 * 1000 + 12 * 60 * 1000 + 44 * 1000;
      el.setAttribute("data-target-ms", String(target));
    }
    el.textContent = formatRemaining(target - Date.now());
  }

  tick();
  setInterval(tick, 1000);

  // Copy install command
  var copyBtn = document.getElementById("copy-install");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var text = ["omarchy plugin add https://github.com/0xRainy/spaceflight-plugin"].join("\n");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          copyBtn.textContent = "Copied!";
          setTimeout(function () {
            copyBtn.textContent = "Copy install";
          }, 1600);
        });
      }
    });
  }
})();

// The question mark controls. Click to open, click away or press Escape to
// close, one open at a time. A title attribute was doing this before, which
// meant hovering and waiting, and gave no way to read a long explanation.
(function () {
  var open = null;

  function close() {
    if (open) { open.remove(); open = null; }
  }

  function show(button) {
    close();
    var bubble = document.createElement("div");
    bubble.className = "tip-bubble";
    bubble.textContent = button.dataset.tip;
    document.body.appendChild(bubble);

    // Placed against the page rather than the button's parent, so a bubble
    // inside a scrolling panel or a table cell is not clipped by it.
    var at = button.getBoundingClientRect();
    var left = at.left + window.scrollX + at.width / 2 - bubble.offsetWidth / 2;
    var top = at.bottom + window.scrollY + 8;
    var margin = 8;
    left = Math.max(margin, Math.min(left,
      document.documentElement.clientWidth - bubble.offsetWidth - margin));
    if (at.bottom + bubble.offsetHeight + 24 > window.innerHeight) {
      top = at.top + window.scrollY - bubble.offsetHeight - 8;
    }
    bubble.style.left = left + "px";
    bubble.style.top = top + "px";
    open = bubble;
  }

  // Delegated, so tips inside anything loaded later still work.
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".tip");
    if (button && button.dataset.tip) {
      event.preventDefault();
      event.stopPropagation();
      if (open && open.dataset.owner === button.dataset.tip) { close(); return; }
      show(button);
      open.dataset.owner = button.dataset.tip;
      return;
    }
    close();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") close();
  });

  window.addEventListener("resize", close);
})();

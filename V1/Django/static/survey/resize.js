/*
 * Drag the Explore sidebars wider or narrower. The handles sit on the map's
 * two edges and set --left-w / --right-w on the layout, between 260px (the default) and 480px. Widths are kept in
 * this browser; double-clicking a handle goes back to the default.
 */
(function () {
  var layout = document.querySelector(".panel-layout");
  if (!layout) return;
  var MIN = 260, MAX = 480, MAP_MIN = 320, KEY = "explore-side-width-";

  function store(side, value) {
    try {
      if (value == null) localStorage.removeItem(KEY + side);
      else localStorage.setItem(KEY + side, value);
    } catch (e) {}
  }
  function apply(side, px) {
    if (px == null) layout.style.removeProperty("--" + side + "-w");
    else layout.style.setProperty("--" + side + "-w", px + "px");
    window.dispatchEvent(new Event("resize"));  // Leaflet re-measures on this
  }
  function other(side) {
    var panel = layout.querySelector(side === "left" ? ".explore-results" : ".filter-panel");
    return panel.getBoundingClientRect().width;
  }

  document.querySelectorAll(".side-handle").forEach(function (handle) {
    var side = handle.dataset.side;
    try {
      var saved = parseInt(localStorage.getItem(KEY + side), 10);
      if (saved >= MIN) apply(side, Math.min(saved, MAX));
    } catch (e) {}

    handle.addEventListener("pointerdown", function (e) {
      handle.setPointerCapture(e.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing");
      e.preventDefault();
    });
    handle.addEventListener("pointermove", function (e) {
      if (!handle.classList.contains("dragging")) return;
      var box = layout.getBoundingClientRect();
      var width = side === "left" ? e.clientX - box.left : box.right - e.clientX;
      var max = Math.min(MAX, box.width - other(side) - MAP_MIN);
      apply(side, Math.round(Math.max(MIN, Math.min(width, max))));
    });
    function end() {
      if (!handle.classList.contains("dragging")) return;
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing");
      var now = parseInt(layout.style.getPropertyValue("--" + side + "-w"), 10);
      if (now) store(side, now);
    }
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("dblclick", function () {
      apply(side, null);
      store(side, null);
    });
  });
})();

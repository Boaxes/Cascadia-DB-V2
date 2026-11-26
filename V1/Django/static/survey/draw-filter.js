/*
 * The "draw an area" accordion on the Efforts and Sightings lists.
 *
 * The drawn shape is written into a hidden field as GeoJSON and submitted
 * with the rest of the form, so an area filter behaves like any other
 * filter: it survives sorting, paging and the export.
 */
(function () {
  var container = document.getElementById("filter-map");
  var field = document.getElementById("area");
  if (!container || !field) return;

  var map = null;
  var drawn = new L.FeatureGroup();

  function build() {
    map = L.map(container).setView([47.6, -122.8], 7);
    basemap(map);
    map.addLayer(drawn);

    map.addControl(new L.Control.Draw({
      edit: { featureGroup: drawn, edit: false },
      draw: {
        polygon: true, rectangle: true,
        polyline: false, circle: false, marker: false, circlemarker: false
      }
    }));

    /* One area at a time. Drawing a second replaces the first, which is
       less surprising than silently combining them. */
    map.on(L.Draw.Event.CREATED, function (e) {
      drawn.clearLayers();
      drawn.addLayer(e.layer);
      field.value = JSON.stringify(e.layer.toGeoJSON().geometry);
    });
    map.on(L.Draw.Event.DELETED, function () { field.value = ""; });

    restore();
  }

  function restore() {
    if (!field.value) return;
    try {
      var layer = L.geoJSON(JSON.parse(field.value));
      layer.eachLayer(function (l) { drawn.addLayer(l); });
      map.fitBounds(drawn.getBounds(), { padding: [20, 20] });
    } catch (err) {
      /* A hand edited URL. Leave the map empty rather than failing. */
    }
  }

  /* Leaflet measures the container when it is created, so a map built while
     the accordion is closed renders as a grey box. Build it on first open. */
  var accordion = container.closest("details");
  if (accordion && !accordion.open) {
    accordion.addEventListener("toggle", function once() {
      if (!accordion.open) return;
      accordion.removeEventListener("toggle", once);
      build();
    });
  } else {
    build();
  }

  var clear = document.getElementById("clear-area");
  if (clear) {
    clear.addEventListener("click", function (e) {
      e.preventDefault();
      drawn.clearLayers();
      field.value = "";
    });
  }
})();

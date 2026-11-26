/*
 * The map on one sighting's detail page: the sighting itself, and the GPS
 * track of the effort it belongs to.
 *
 * One sighting on the shared basemap, with its effort track behind it.
 */
(function () {
  var config = window.SIGHTING_MAP;
  if (!config) return;

  var container = document.getElementById(config.container);
  if (!container || typeof L === "undefined") return;

  if (container._leaflet_id) container._leaflet_id = null;
  container.innerHTML = "";

  var map = L.map(container);

  basemap(map);

  var bounds = [];

  if (config.point) {
    L.circleMarker(config.point, {
      radius: 8, color: "#fff", weight: 2,
      fillColor: config.colour, fillOpacity: 0.9
    }).bindPopup("<strong>" + config.label + "</strong>").addTo(map);
    bounds.push(config.point);
  }

  /* The end position is not drawn. Two dots a few hundred metres apart, one
     of them the vessel where it left the group, read as two sightings. The
     value is on the page, where it can be labelled. */

  function fit() {
    if (bounds.length > 1) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    else if (bounds.length === 1) map.setView(bounds[0], 11);
    else map.setView([47.6, -122.8], 7);
  }

  if (config.trackUrl) {
    fetch(config.trackUrl)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (feature) {
        if (feature && feature.geometry) {
          L.geoJSON(feature, {
            style: { color: mapColour("track"), weight: 2.5, opacity: 0.7 }
          }).addTo(map);
        }
        fit();
      })
      .catch(fit);
  } else {
    fit();
  }

  screenshotControl(map, {
    title: "Sighting " + config.id,
    caption: function () { return config.caption; },
    filename: "sighting-" + config.id + "-map"
  });

  setTimeout(function () { map.invalidateSize(); fit(); }, 60);
})();

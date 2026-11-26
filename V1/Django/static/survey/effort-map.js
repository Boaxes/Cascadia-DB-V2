/*
 * The map on one effort's detail page: its GPS track, its sightings, and
 * where the day's first position came from.
 *
 * Runs both on the standalone page and again each time the detail is opened
 * in a modal, so it reads its configuration fresh from window.EFFORT_MAP and
 * tolerates being executed more than once.
 */
(function () {
  var config = window.EFFORT_MAP;
  if (!config) return;

  var container = document.getElementById(config.container);
  if (!container || typeof L === "undefined") return;

  /* Leaflet refuses to initialise a container it has already used. */
  if (container._leaflet_id) container._leaflet_id = null;
  container.innerHTML = "";

  var map = L.map(container);
  basemap(map);

  var bounds = [];

  config.sightings.forEach(function (s) {
    L.circleMarker([s.lat, s.lon], {
      radius: 5, color: "#fff", weight: 1,
      fillColor: s.colour, fillOpacity: 0.9
    })
      .bindPopup(
        '<strong>' + s.label + "</strong><br>" + (s.time || "") +
        '<br><a href="/sightings/' + s.id + '/" data-modal-url="/sightings/' + s.id + '/">Open sighting ' + s.id + "</a>"
      )
      .addTo(map);
    bounds.push([s.lat, s.lon]);
  });

  /* Start and end are drawn here as well as on Explore. They were on Explore
     only, so an effort whose end position is wrong looked fine on its own
     page and wrong on the map, with nothing to explain the difference. */
  function endpoint(at, colour, title) {
    if (!at) return;
    L.circleMarker(at, {
      radius: 7, color: "#fff", weight: 2,
      fillColor: colour, fillOpacity: 1
    }).bindPopup(title).addTo(map);
    bounds.push(at);
  }

  endpoint(config.start, mapColour("green-fg"), config.startIsDeparture
    ? "Start of the effort"
    : "First recorded position of the day, not the departure point");
  endpoint(config.end, mapColour("danger"), "End of the effort" +
    (config.endSource ? " (" + config.endSource + ")" : ""));

  /* No GPS file, so the day is drawn from the positions that were recorded,
     joined in time order. Dashed because nothing between them was. */
  if (!config.trackUrl && config.path && config.path.length > 1) {
    L.polyline(config.path, {
      color: mapColour("track"), weight: 2, opacity: 0.7, dashArray: "5 6"
    }).bindPopup("No GPS file for this effort. This line joins the positions " +
                 "that were recorded, in time order.").addTo(map);
    bounds = bounds.concat(config.path);
  }

  function fit() {
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
    else map.setView([47.6, -122.8], 7);
  }

  if (config.trackUrl) {
    fetch(config.trackUrl)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (feature) {
        if (!feature || !feature.geometry) { fit(); return; }
        var line = L.geoJSON(feature, {
          style: config.trackIsSuspect
            ? { color: mapColour("danger"), weight: 2, opacity: 0.6, dashArray: "6 5" }
            : { color: mapColour("track"), weight: 3, opacity: 0.7 }
        }).addTo(map);

        /* The same dashed bridge Explore draws. A track is one line per run
           of GPS, and without this the gaps read as the boat not being there
           rather than the device being quiet. */
        var parts = feature.geometry.type === "MultiLineString"
          ? feature.geometry.coordinates : [feature.geometry.coordinates];
        for (var i = 1; i < parts.length; i++) {
          var previous = parts[i - 1];
          var from = previous[previous.length - 1];
          var to = parts[i][0];
          L.polyline([[from[1], from[0]], [to[1], to[0]]], {
            color: mapColour("track"), weight: 1.6, opacity: 0.5, dashArray: "5 6"
          }).bindPopup("The GPS went quiet here. Nothing between these two "
                       + "points was recorded.").addTo(map);
        }

        /* A corrupted line spans an ocean. Drawing it is honest; letting it
           set the zoom would push every sighting off the screen. */
        if (!config.trackIsSuspect) {
          var b = line.getBounds();
          bounds = bounds.concat([b.getSouthWest(), b.getNorthEast()]);
        }
        fit();
      })
      .catch(fit);
  } else {
    fit();
  }

  /* The modal animates in, so the container has no size at the moment the
     map is built. */
  setTimeout(function () { map.invalidateSize(); fit(); }, 60);
})();

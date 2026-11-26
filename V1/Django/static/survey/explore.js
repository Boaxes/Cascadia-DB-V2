/*
 * The Explore map.
 *
 * The whole filtered dataset is fetched once, in two requests, and the
 * browser owns everything after that. Panning and zooming issue no request
 * and nothing disappears when you zoom out, because there is nothing left to
 * load. A request happens only when a filter is applied, which is a
 * deliberate action where a short wait is expected.
 */
(function () {
  var config = window.EXPLORE;
  if (!config || typeof L === "undefined") return;

  var species = config.species || {};
  var OTHER = { name: "Not identified", colour: "#5d6e77" };

  /* A count as people read it: 1,049, and "1 Animal" against "2 Animals". */
  function num(n) { return Number(n).toLocaleString("en-US"); }
  function plural(n, one) { return num(n) + " " + one + (Number(n) === 1 ? "" : "s"); }

  /* The view and the layers are kept in the link (setPageState, filters.js),
     so applying filters, reloading or sharing the link comes back to the
     same map. The map opens straight at that view rather than moving to it. */
  var view = (getPageState("view") || "").split(",").map(Number);
  var hasView = view.length === 3 && view.every(isFinite);
  /* A track is under two pixels wide. The tolerance gives a finger or a
     mouse a few pixels either side of it to click. */
  var map = L.map("explore-map", { preferCanvas: true, renderer: L.canvas({ tolerance: 5 }) })
    .setView(hasView ? [view[0], view[1]] : [44, -124], hasView ? view[2] : 5);

  basemap(map);
  var base = map.baseLayers[getPageState("base")];
  if (base && base !== map.baseLayers.satellite) {
    map.removeLayer(map.baseLayers.satellite);
    map.addLayer(base);
  }
  if (getPageState("labels") === "0") map.removeLayer(map.placesLayer);

  map.on("moveend", function () {
    var c = map.getCenter();
    setPageState("view", [c.lat.toFixed(4), c.lng.toFixed(4), map.getZoom()].join(","));
  });
  map.on("baselayerchange", function (e) {
    for (var name in map.baseLayers) {
      if (map.baseLayers[name] === e.layer) setPageState("base", name === "satellite" ? null : name);
    }
  });
  map.on("overlayadd overlayremove", function (e) {
    if (e.layer === map.placesLayer) setPageState("labels", e.type === "overlayremove" ? "0" : null);
  });

  new L.Control.Measure({
    primaryLengthUnit: "nauticalmiles", secondaryLengthUnit: "kilometers",
    primaryAreaUnit: "sqkilometers", position: "topleft"
  }).addTo(map);
  /* The plugin words its own tooltip in sentence case. */
  var measureToggle = document.querySelector(".leaflet-control-measure-toggle");
  if (measureToggle) measureToggle.title = "Measure Distances and Areas";

  /* Fullscreen is the map and its legend only; the sidebars are siblings, so
     they drop away on their own. */
  var mapBox = document.querySelector(".explore-map");
  if (mapBox.requestFullscreen) {
    var FullscreenControl = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var bar = L.DomUtil.create("div", "leaflet-bar leaflet-control leaflet-control-fullscreen");
        var link = L.DomUtil.create("a", "", bar);
        link.href = "#";
        link.setAttribute("role", "button");
        function sync() {
          var on = document.fullscreenElement === mapBox;
          link.innerHTML = on ? "&#x2715;" : "&#x26F6;";
          link.title = on ? "Exit Fullscreen" : "Fullscreen";
          link.setAttribute("aria-label", link.title);
          map.invalidateSize();
        }
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(link, "click", function (e) {
          L.DomEvent.preventDefault(e);
          if (document.fullscreenElement === mapBox) document.exitFullscreen();
          else mapBox.requestFullscreen();
        });
        document.addEventListener("fullscreenchange", sync);
        sync();
        return bar;
      }
    });
    new FullscreenControl().addTo(map);
  }

  screenshotControl(map, {
    node: mapBox,
    skip: ".side-handle, .map-loading",
    title: "Explore Map",
    caption: function () {
      return config.counts + ". " + (config.filters.length
        ? "Filters: " + config.filters.join(", ") + "."
        : "No filters applied.");
    },
    filename: "explore-map-" + new Date().toISOString().slice(0, 10)
  });

  var trackLayer = L.layerGroup().addTo(map);
  var gapLayer = L.layerGroup().addTo(map);

  /* Sightings are drawn either grouped into counted circles or as one dot per
     record. Clustering keeps 31,682 dots from becoming a solid mass at low
     zoom; ungrouped is what you want when the question is where the animals
     actually were rather than how many there are. Both layers hold the same
     markers, so the toggle only decides which is on the map. */
  var clustered = L.markerClusterGroup({
    chunkedLoading: true,
    spiderfyOnMaxZoom: false,
    disableClusteringAtZoom: 10,
    maxClusterRadius: 34
  });
  var ungrouped = L.layerGroup();
  var sightingLayer = clustered;
  var allMarkers = [];
  clustered.addTo(map);

  function setClustering(on) {
    var next = on ? clustered : ungrouped;
    if (next === sightingLayer && map.hasLayer(next)) return;
    map.removeLayer(clustered);
    map.removeLayer(ungrouped);
    sightingLayer = next;
    if (on) {
      clustered.clearLayers();
      clustered.addLayers(allMarkers);
    } else {
      ungrouped.clearLayers();
      allMarkers.forEach(function (m) { ungrouped.addLayer(m); });
    }
    sightingLayer.addTo(map);
  }
  window.setSightingClustering = setClustering;

  /* ---------------------------------------------------------- drawn area */

  var drawn = new L.FeatureGroup().addTo(map);
  var areaField = document.getElementById("area");

  map.addControl(new L.Control.Draw({
    edit: { featureGroup: drawn, edit: false },
    draw: {
      polygon: true, rectangle: true,
      polyline: false, circle: false, marker: false, circlemarker: false
    }
  }));

  function setArea(geometry, layer) {
    drawn.clearLayers();
    if (layer) drawn.addLayer(layer);
    areaField.value = geometry ? JSON.stringify(geometry) : "";
    var state = document.getElementById("area-state");
    state.firstChild.textContent = geometry
      ? "An area is drawn. Apply Filters to use it. "
      : "Draw an area on the map with the shape tools. ";
    areaField.dispatchEvent(new Event("change", { bubbles: true }));
  }

  map.on(L.Draw.Event.CREATED, function (e) {
    setArea(e.layer.toGeoJSON().geometry, e.layer);
  });

  document.getElementById("clear-area").addEventListener("click", function (e) {
    e.preventDefault();
    setArea(null, null);
  });

  if (areaField.value) {
    try {
      L.geoJSON(JSON.parse(areaField.value)).eachLayer(function (l) {
        drawn.addLayer(l);
      });
      if (!hasView) map.fitBounds(drawn.getBounds(), { padding: [30, 30] });
    } catch (err) { /* a hand edited URL; leave the map alone */ }
  }

  /* --------------------------------------------------------- layer toggles */

  function toggle(id, get) {
    var box = document.getElementById(id);
    if (!box) return;
    box.addEventListener("change", function (e) {
      var layer = get();
      if (e.target.checked) map.addLayer(layer); else map.removeLayer(layer);
    });
  }
  /* Sightings are read through a function rather than captured, because the
     cluster toggle swaps which layer holds them. */
  toggle("toggle-sightings", function () { return sightingLayer; });
  toggle("toggle-tracks", function () { return trackLayer; });

  var clusterBox = document.getElementById("toggle-clusters");
  if (clusterBox) {
    clusterBox.addEventListener("change", function (e) {
      var showing = document.getElementById("toggle-sightings");
      setClustering(e.target.checked);
      if (showing && !showing.checked) map.removeLayer(sightingLayer);
    });
  }

  /* The checkboxes as the link left them, and back into the link on change. */
  [["toggle-tracks", "tracks"], ["toggle-sightings", "points"], ["toggle-clusters", "clusters"]]
    .forEach(function (pair) {
      var box = document.getElementById(pair[0]);
      if (!box) return;
      if (getPageState(pair[1]) === "0") {
        box.checked = false;
        box.dispatchEvent(new Event("change"));
      }
      box.addEventListener("change", function () {
        setPageState(pair[1], box.checked ? null : "0");
      });
    });

  /* -------------------------------------------------------------- loading */

  var loading = document.getElementById("map-loading");
  var pending = 2;

  function done() {
    if (--pending <= 0) loading.classList.remove("on");
  }

  loading.classList.add("on");

  /* Dot size follows the best group estimate. A square root keeps a group
     of 200 from swamping the map: area, not radius, tracks the count. */
  function radiusFor(size) {
    if (!size || size < 1) return 3;
    return Math.min(3 + Math.sqrt(size) * 1.2, 12);
  }

  fetch("/api/sightings/?" + config.query)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var markers = [];
      var results = [];

      data.rows.forEach(function (row) {
        var id = row[0], lon = row[1], lat = row[2],
            speciesId = row[3], year = row[4], size = row[5];
        var meta = species[speciesId] || OTHER;

        var marker = L.circleMarker([lat, lon], {
          radius: radiusFor(size),
          color: "#ffffff", weight: 1, opacity: 0.9,
          fillColor: meta.colour, fillOpacity: 0.82
        });

        marker.bindPopup(
          "<strong>" + meta.name + "</strong><br>" +
          (year || "") +
          (size ? " &middot; about " + plural(size, "Animal") : "") +
          '<br><a href="/sightings/' + id + '/" data-modal-url="/sightings/' + id + '/">Open Sighting ' + id + "</a>"
        );

        markers.push(marker);
        if (results.length < 300) {
          results.push({
            id: id, name: meta.name, year: year, size: size, colour: meta.colour
          });
        }
      });

      /* Cascadia colours each species, so its legend is the nine species
         seen most in these results rather than one row per group. */
      var legend = document.getElementById("species-legend");
      if (legend) {
        var counts = {};
        data.rows.forEach(function (row) { counts[row[3]] = (counts[row[3]] || 0) + 1; });
        legend.innerHTML = Object.keys(counts)
          .sort(function (a, b) { return counts[b] - counts[a]; })
          .slice(0, 9)
          .map(function (id) {
            var meta = species[id] || OTHER;
            return '<div class="legend-row"><span style="background:' + meta.colour +
              '"></span><span>' + meta.name + "</span></div>";
          }).join("");
      }

      allMarkers = markers;
      if (sightingLayer === clustered) {
        clustered.addLayers(markers);
      } else {
        markers.forEach(function (m) { ungrouped.addLayer(m); });
      }
      renderResults(results, data.rows.length);
      done();
    })
    .catch(done);

  var TRACK = { color: mapColour("track"), weight: 1.8, opacity: 0.7 };
  var GAP = { color: mapColour("track"), weight: 1.2, opacity: 0.55, dashArray: "5 6" };

  function flip(ring) {
    return ring.map(function (c) { return [c[1], c[0]]; });
  }

  fetch("/api/tracks/?" + config.query)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      data.features.forEach(function (feature) {
        var effort = feature.properties.effort;
        var trackId = feature.properties.track;
        var geometry = feature.geometry;
        var parts = geometry.type === "MultiLineString"
          ? geometry.coordinates : [geometry.coordinates];

        /* One layer per track, however many runs it has, so clicking any
           part of it selects all of it. */
        var track = L.featureGroup(parts.map(function (part) {
          return L.polyline(flip(part), TRACK);
        }));
        track.on("add", track.bringToBack);  // keep sightings on top
        track.bindTooltip("Track " + trackId + ", Effort " + effort, { sticky: true });
        clickableTrack(track, TRACK, feature.properties,
                       { effortLink: true, managerUrl: config.trackManagerUrl });
        track.addTo(trackLayer);

        /* The straight line between two runs is the part nobody recorded, so
           it is dashed rather than drawn as track. */
        for (var i = 1; i < parts.length; i++) {
          var previous = parts[i - 1];
          L.polyline(flip([previous[previous.length - 1], parts[i][0]]), GAP)
            .on("add", function () { this.bringToBack(); })
            .addTo(gapLayer);
        }
      });
      done();
    })
    .catch(done);

  /* --------------------------------------------------------------- results */

  var container = document.getElementById("results");
  var listLink = document.querySelector("[data-list]");
  var panels = { sightings: null, efforts: null };
  var showing = "sightings";

  function tooMany(shown, total, what) {
    if (total <= shown) return "";
    return '<p class="small muted" style="padding:12px 14px">Showing the first ' +
      num(shown) + " of " + num(total) + " " + what +
      ". Narrow the filters, or open the full list.</p>";
  }

  function renderResults(rows, total) {
    panels.sightings = rows.map(function (row) {
      return '<a class="result-item" href="/sightings/' + row.id + '/"' +
        ' data-modal-url="/sightings/' + row.id + '/">' +
        '<div class="t"><span class="result-dot" style="background:' + row.colour + '"></span>' +
        row.name + (row.size ? '<span class="result-count" title="Animals in the '
          + 'group, as the observer best estimated it">'
          + plural(row.size, "Animal") + '</span>' : "") +
        '</div><div class="s">' + (row.year || "Year not recorded") +
        " &middot; Sighting " + row.id + "</div></a>";
    }).join("") + tooMany(rows.length, total, "Sightings");
    if (showing === "sightings") container.innerHTML = panels.sightings;
  }

  function renderEfforts(data) {
    panels.efforts = data.rows.map(function (row) {
      var id = row[0], date = row[1], locality = row[2],
          vessel = row[3], sightings = row[4];
      return '<a class="result-item" href="/efforts/' + id + '/"' +
        ' data-modal-url="/efforts/' + id + '/">' +
        '<div class="t">' + (locality || "Locality not recorded") +
        (sightings ? '<span class="result-count">' + plural(sightings, "Sighting")
          + '</span>' : "") +
        '</div><div class="s">' + (date || "Date not recorded") +
        (vessel ? " &middot; " + vessel : "") + " &middot; Effort " + id +
        "</div></a>";
    }).join("") + tooMany(data.rows.length, data.total, "Efforts");
    if (showing === "efforts") container.innerHTML = panels.efforts;
  }

  /* Efforts are fetched the first time the tab is opened. Loading both with
     the page would charge everybody for a list most people never open. */
  document.querySelectorAll("[data-tab]").forEach(function (button) {
    button.addEventListener("click", function () {
      showing = button.dataset.tab;
      document.querySelectorAll("[data-tab]").forEach(function (other) {
        other.classList.toggle("active", other === button);
      });
      listLink.href = (showing === "efforts" ? "/efforts/" : "/sightings/") +
        (config.query ? "?" + config.query : "");
      /* Show the Add To Export button of the open tab. */
      document.querySelectorAll("[data-export-tab]").forEach(function (form) {
        form.hidden = form.dataset.exportTab !== showing;
      });

      if (panels[showing] !== null) {
        container.innerHTML = panels[showing];
        return;
      }
      container.innerHTML = '<p class="small muted" style="padding:12px 14px">Loading&hellip;</p>';
      fetch("/api/efforts/?" + config.query)
        .then(function (r) { return r.json(); })
        .then(renderEfforts)
        .catch(function () {
          container.innerHTML = '<p class="small muted" style="padding:12px 14px">Could not load the Efforts.</p>';
        });
    });
  });
})();

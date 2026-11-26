// The backdrop for every map in the application.
//
// Defined once because it was defined three times: Explore opened on one
// basemap and offered it twice under two names, effort detail opened on
// another, and sighting detail opened on satellite. Two maps side by side
// looked like two different applications.
//
// Satellite is the default: the work is on the water, and imagery shows the
// coastline and bathymetry shading that a road map leaves blank. Place names
// are a separate overlay on top of it, so they can be turned off without
// leaving satellite, and so the satellite view is not unlabelled.
//
// None of these need an API key. The previous basemap did, and every map in
// the application was showing "API KEY REQUIRED" written across it.
// Map colours are read from the palette in app.css, so the maps and the
// pages around them can never drift apart.
window.mapColour = function (name) {
  return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
};

window.basemap = function (map) {
  var satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri, Maxar, Earthstar Geographics", maxZoom: 19 }
  ).addTo(map);

  var street = L.tileLayer(
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19 }
  );

  var ocean = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri, GEBCO, NOAA", maxZoom: 13 }
  );

  // Coastlines, borders and place names, drawn over whatever is beneath.
  var places = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri", maxZoom: 19, pane: "shadowPane" }
  ).addTo(map);

  var control = L.control.layers(
    { Satellite: satellite, Map: street, Ocean: ocean },
    { "Place names": places }
  ).addTo(map);

  L.control.scale({ imperial: true, metric: true }).addTo(map);

  // Handed back so a caller can add its own overlays to the same control, and
  // switch layers itself (Explore restores the ones in its link).
  map.layerControl = control;
  map.baseLayers = { satellite: satellite, map: street, ocean: ocean };
  map.placesLayer = places;
  return satellite;
};

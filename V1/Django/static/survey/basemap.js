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
//
// All four servers send Access-Control-Allow-Origin, so the tiles are loaded
// with crossOrigin. Without it a saved picture of the map (map-tools.js)
// could not read them back and would come out blank.
// Map colours are read from the palette in app.css, so the maps and the
// pages around them can never drift apart.
window.mapColour = function (name) {
  return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
};

// The names Leaflet and its drawing tools show when a button is hovered, in
// Title Case like every other label. The zoom buttons are built with the map,
// so theirs are set here, before any map exists.
if (window.L) {
  L.Control.Zoom.prototype.options.zoomInTitle = "Zoom In";
  L.Control.Zoom.prototype.options.zoomOutTitle = "Zoom Out";
}
function localiseDrawing() {
  if (!window.L || !L.drawLocal) return;
  var buttons = L.drawLocal.draw.toolbar.buttons, edit = L.drawLocal.edit.toolbar;
  buttons.polygon = "Draw a Polygon";
  buttons.rectangle = "Draw a Rectangle";
  edit.buttons.remove = "Delete Layers";
  edit.buttons.removeDisabled = "No Layers To Delete";
  edit.actions.clearAll.text = "Clear All";
  edit.actions.clearAll.title = "Clear All Layers";
  edit.actions.cancel.text = "Cancel";
  edit.actions.cancel.title = "Cancel Deleting";
  edit.actions.save.text = "Save";
  edit.actions.save.title = "Save Changes";
  L.drawLocal.draw.toolbar.actions.title = "Cancel Drawing";
  L.drawLocal.draw.toolbar.actions.text = "Cancel";
  L.drawLocal.draw.toolbar.finish.title = "Finish Drawing";
  L.drawLocal.draw.toolbar.finish.text = "Finish";
  L.drawLocal.draw.toolbar.undo.title = "Delete Last Point Drawn";
  L.drawLocal.draw.toolbar.undo.text = "Delete Last Point";
}

window.basemap = function (map) {
  localiseDrawing();
  var satellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri, Maxar, Earthstar Geographics", maxZoom: 19, crossOrigin: true }
  ).addTo(map);

  var street = L.tileLayer(
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { attribution: "&copy; OpenStreetMap contributors", maxZoom: 19, crossOrigin: true }
  );

  var ocean = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri, GEBCO, NOAA", maxZoom: 13, crossOrigin: true }
  );

  // Coastlines, borders and place names, drawn over whatever is beneath.
  var places = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Esri", maxZoom: 19, pane: "shadowPane", crossOrigin: true }
  ).addTo(map);

  var bases = { Satellite: satellite, Map: street, Ocean: ocean };
  var overlays = { "Place Names": places };
  var control = L.control.layers(bases, overlays).addTo(map);

  // Each layer knows the name the layers menu shows, so a message about a
  // layer can use the same words.
  [bases, overlays].forEach(function (group) {
    for (var name in group) group[name].menuName = name;
  });

  L.control.scale({ imperial: true, metric: true }).addTo(map);

  // Handed back so a caller can add its own overlays to the same control, and
  // switch layers itself (Explore restores the ones in its link).
  map.layerControl = control;
  map.baseLayers = { satellite: satellite, map: street, ocean: ocean };
  map.placesLayer = places;
  return satellite;
};

// Mockup helper only: draws the shared sidebar (NAV-01) so every page has the same one.
// <body data-page="efforts"> marks the active link. Add ?search=1 to a page's URL to show
// the Global Search results (SRCH-03). The real site renders the sidebar in a Django template.
(function () {
  var page = document.body.dataset.page || "";
  var link = function (id, href, label, icon, extra) {
    return '<a class="nav-link' + (id === page ? " active" : "") + '" href="' + href + '">' +
      '<svg class="icon"><use href="icons.svg#' + icon + '"/></svg>' + label + (extra || "") + "</a>";
  };
  var results = new URLSearchParams(location.search).has("search") ?
    '<div class="search-results">' +
    "<h3>Individuals</h3>" +
    '<a class="best" href="individual.html"><span>CRC-20417 <span class="muted small">Humpback Whale</span></span><span class="muted small">Enter</span></a>' +
    '<a href="individual.html"><span>CRC-12043 <span class="muted small">alias of CRC-20417</span></span></a>' +
    "<h3>Sightings</h3>" +
    '<a href="sighting.html"><span>Sighting 120417 <span class="muted small">2024-07-14</span></span></a>' +
    "<h3>Efforts</h3>" +
    '<a href="effort.html"><span>Effort 20417 <span class="muted small">2023-08-02</span></span></a>' +
    "</div>" : "";
  var html =
    '<aside class="sidebar" id="sidebar">' +
    '<a class="brand" href="explore.html"><img src="cascadia-logo.png" alt=""><span>Unified DB</span></a>' +
    '<div class="search"><svg class="icon"><use href="icons.svg#search"/></svg>' +
    '<input type="text" placeholder="Search IDs, Vessels, Places" value="' + (results ? "20417" : "") + '">' + results + "</div>" +
    '<nav class="nav-group"><h3>Survey</h3>' +
    link("explore", "explore.html", "Explore", "explore") +
    link("efforts", "efforts.html", "Efforts", "efforts") +
    link("sightings", "sightings.html", "Sightings", "sightings") + "</nav>" +
    '<nav class="nav-group"><h3>Photo-ID</h3>' +
    link("individuals", "individuals.html", "Individuals", "individuals") + "</nav>" +
    '<nav class="nav-group"><h3>Data</h3>' +
    link("export", "export.html", "Export", "export", '<span class="count">3</span>') +
    link("sql", "sql.html", "SQL", "sql") + "</nav>" +
    '<nav class="nav-group"><h3>Manage</h3>' +
    link("tracks", "tracks.html", "Track File Manager", "tracks") +
    link("audit", "audit.html", "Audit Log", "audit") +
    link("users", "users.html", "Users", "users") +
    link("server", "server.html", "Server", "server") + "</nav>" +
    '<div class="spacer"></div>' +
    '<nav class="nav-group">' +
    link("feedback", "feedback.html", "Feedback", "feedback") +
    link("settings", "settings.html", "Settings", "settings") + "</nav>" +
    '<div class="user"><div class="avatar">ST</div><div class="who">Sam Taylor<br><small>Admin</small></div>' +
    '<button class="btn btn-sm btn-quiet" type="button">Sign Out</button></div>' +
    "</aside>";
  var top = '<div class="topbar"><button class="btn btn-sm" type="button" id="menu-button" aria-label="Menu">' +
    '<svg class="icon"><use href="icons.svg#menu"/></svg></button><img src="cascadia-logo.png" alt=""><b>Unified DB</b></div>';
  document.currentScript.insertAdjacentHTML("beforebegin", html);
  document.addEventListener("DOMContentLoaded", function () {
    var main = document.querySelector(".main");
    if (main) main.insertAdjacentHTML("afterbegin", top);
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest("#menu-button")) document.body.classList.toggle("menu-open");
  });
})();

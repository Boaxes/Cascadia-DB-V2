// Mockup helper only: draws the shared filter panel (FILT-01 to FILT-06).
// <div class="filters" data-for="explore|efforts|sightings"></div>
// Efforts get no sighting-only filters. The real site renders this in a Django template.
(function () {
  var box = document.currentScript.previousElementSibling;
  var kind = box.dataset.for;
  var sightingFilters = kind !== "efforts";
  var years = "";
  for (var y = 2026; y >= 2001; y--) years += '<span class="chip">' + y + "</span>";
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    .map(function (m) { return '<span class="chip">' + m + "</span>"; }).join("");
  box.innerHTML =
    '<button class="filters-toggle" type="button">Filters <span class="set">1</span></button>' +
    '<details open><summary>Group, Species and Vessel <span class="set">1</span></summary><div class="body">' +
    '<label class="field"><span>Research Group</span><div class="tagbox"><span class="tag">CRC <b>&times;</b></span><input type="text" placeholder="Add"></div></label>' +
    (sightingFilters ?
      '<label class="field"><span>Species</span><div class="tagbox"><input type="text" placeholder="All Species"></div></label>' +
      '<label class="field"><span>Individual</span><input type="text" placeholder="Any Whale ID or Alias"></label>' : "") +
    '<label class="field"><span>Vessel</span><div class="tagbox"><input type="text" placeholder="All Vessels"></div></label>' +
    "</div></details>" +
    '<details><summary>Location</summary><div class="body">' +
    '<label class="field"><span>Region</span><select><option>All Regions</option><option>Salish Sea</option><option>Washington Coast</option><option>Oregon Coast</option></select></label>' +
    '<label class="field"><span>Sub-Area</span><div class="tagbox"><input type="text" placeholder="All Sub-Areas"></div></label>' +
    '<label class="field"><span>Locality</span><select><option>All Localities</option><option>Haro Strait</option><option>Port Angeles</option><option>Grays Harbor</option></select></label>' +
    '<button class="btn btn-sm" type="button"><svg class="icon"><use href="icons.svg#draw"/></svg>Draw an Area</button>' +
    "</div></details>" +
    '<details><summary>Time</summary><div class="body">' +
    '<h3>Years</h3><div class="chips">' + years + "</div>" +
    '<h3 style="margin-top:10px">Months</h3><div class="chips">' + months + "</div>" +
    '<div class="chips" style="margin-top:6px"><span class="chip">Winter</span><span class="chip">Spring</span><span class="chip">Summer</span><span class="chip">Fall</span></div>' +
    '<div class="form-grid" style="margin-top:10px"><label class="field"><span>From</span><input type="date"></label><label class="field"><span>To</span><input type="date"></label></div>' +
    "</div></details>" +
    '<details><summary>Other</summary><div class="body">' +
    '<label class="field"><span>Survey Type</span><select><option>All Survey Types</option><option>Dedicated</option><option>Opportunistic</option></select></label>' +
    '<label class="field"><span>Project or Objective</span><div class="tagbox"><input type="text" placeholder="All Projects"></div></label>' +
    '<label class="field"><span>Tags and Samples</span><select><option>Either</option><option>With</option><option>Without</option></select></label>' +
    '<label class="field"><span>GPS Track</span><select><option>Any</option><option>Available</option><option>No Track File</option><option>Blank</option></select></label>' +
    '<label class="field"><span>Crew Member</span><input type="text"></label>' +
    (sightingFilters ?
      '<label class="field"><span>Position Type</span><select><option>Any</option><option>Precise</option><option>Calculated</option><option>Estimated</option><option>General</option></select></label>' +
      '<label class="field"><span>Uncertain Species</span><select><option>Include</option><option>Exclude</option><option>Only</option></select></label>' +
      '<label class="field"><span>Sightings on Land</span><select><option>Include</option><option>Exclude</option><option>Only</option></select></label>' +
      '<label class="check"><input type="checkbox"> Include Non-Animal Records</label>' : "") +
    (kind === "explore" ? '<label class="check"><input type="checkbox" checked> Only Efforts With Matching Sightings</label>' : "") +
    "</div></details>" +
    '<div class="filter-buttons"><button class="btn btn-primary" type="button">Apply Filters</button><button class="btn" type="button">Reset</button></div>';
  box.querySelector(".filters-toggle").addEventListener("click", function () { box.classList.toggle("open"); });
  box.querySelectorAll(".chip").forEach(function (c) { c.addEventListener("click", function () { c.classList.toggle("on"); }); });
})();

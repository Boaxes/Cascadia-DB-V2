/*
 * The small behaviours of the filter panel: year and month chips, season
 * buttons, the count on each section, and keeping the page state in the link.
 */
(function () {
  function changed(el) { el.dispatchEvent(new Event("change", { bubbles: true })); }

  /* How the page is left -- which filter sections are open, and on Explore
     the map's view and layers -- lives in the link, so Apply, a reload or a
     shared link comes back to it. These are not filters: the server ignores
     them, and they never reach an export. */
  var PAGE_STATE = ["open", "view", "base", "labels", "tracks", "points", "clusters"];
  window.setPageState = function (name, value) {
    var url = new URL(window.location.href);
    url.searchParams.delete(name);
    (Array.isArray(value) ? value : value == null ? [] : [value])
      .forEach(function (v) { url.searchParams.append(name, v); });
    history.replaceState(history.state, "", url);
  };
  window.getPageState = function (name) {
    return new URL(window.location.href).searchParams.get(name);
  };

  document.querySelectorAll(".fsec[data-key]").forEach(function (section) {
    section.addEventListener("toggle", function () {
      var open = Array.prototype.map.call(
        document.querySelectorAll(".fsec[data-key][open]"),
        function (s) { return s.dataset.key; });
      /* Always written once touched, so "none open" is kept too. */
      setPageState("open", open.length ? open : [""]);
    });
  });
  /* Apply takes the page state along with the filters. */
  document.querySelectorAll("form#filters").forEach(function (form) {
    /* Back from the results can restore the page from the back/forward
       cache with the two inputs still disabled by the submit below. */
    window.addEventListener("pageshow", function () {
      ["#match-sightings-off", "#match-sightings"].forEach(function (id) {
        var el = form.querySelector(id);
        if (el) el.disabled = false;
      });
    });
    form.addEventListener("submit", function () {
      /* Only Efforts With Matching Sightings is on by default, so it is
         sent only when it is turned off. */
      var off = form.querySelector("#match-sightings-off");
      var on = form.querySelector("#match-sightings");
      if (off && on) { off.disabled = on.checked; on.disabled = on.checked; }
      /* Read the open sections from the page itself: a section opened just
         before Apply may not have reached the link yet. */
      if (document.querySelector(".fsec[data-key]")) {
        var open = Array.prototype.map.call(
          document.querySelectorAll(".fsec[data-key][open]"),
          function (s) { return s.dataset.key; });
        setPageState("open", open.length ? open : null);
      }
      var here = new URL(window.location.href).searchParams;
      PAGE_STATE.forEach(function (name) {
        here.getAll(name).forEach(function (value) {
          var input = document.createElement("input");
          input.type = "hidden"; input.name = name; input.value = value;
          form.appendChild(input);
        });
      });
    });
  });

  /* Chips select like files in a file manager. Click picks only that one
     (clicking the only one again clears it, which means all). Shift-click
     adds the run from the last one clicked. Cmd or Ctrl-click adds or
     removes one. The keyboard (Space) toggles as a normal checkbox. */
  document.querySelectorAll(".chips").forEach(function (chips) {
    var boxes = Array.prototype.slice.call(chips.querySelectorAll("input"));
    var anchor = -1;
    chips.addEventListener("click", function (e) {
      var chip = e.target.closest(".chip");
      if (!chip || e.target.tagName === "INPUT") return;
      e.preventDefault();
      var box = chip.querySelector("input"), i = boxes.indexOf(box);
      if (e.shiftKey && anchor >= 0) {
        boxes.slice(Math.min(anchor, i), Math.max(anchor, i) + 1)
          .forEach(function (b) { b.checked = true; });
      } else if (e.metaKey || e.ctrlKey) {
        box.checked = !box.checked;
      } else {
        var only = box.checked && boxes.filter(function (b) { return b.checked; }).length === 1;
        boxes.forEach(function (b) { b.checked = b === box && !only; });
      }
      anchor = i;
      changed(chips);
    });
  });

  /* Click a season for just its months, Shift-click to add it to the others.
     A season lights up only when it was clicked: ticking Sep, Oct and Nov by
     hand is three months, not Fall, and any change to the months by hand
     puts the lights out. */
  document.querySelectorAll(".seasons").forEach(function (seasons) {
    var chips = seasons.parentNode.querySelector(".chips");
    var months = Array.prototype.slice.call(chips.querySelectorAll("input"));
    var buttons = Array.prototype.slice.call(seasons.querySelectorAll("button"));
    function picks(button) {
      var wanted = button.dataset.months.split(",");
      return months.filter(function (m) { return wanted.indexOf(m.value) !== -1; });
    }
    buttons.forEach(function (button) {
      button.addEventListener("click", function (e) {
        var mine = picks(button), add = e.shiftKey || e.metaKey || e.ctrlKey;
        var on = !button.classList.contains("on");
        if (add) {
          mine.forEach(function (m) { m.checked = on; });
        } else {
          buttons.forEach(function (b) { b.classList.remove("on"); });
          months.forEach(function (m) { m.checked = on && mine.indexOf(m) !== -1; });
        }
        button.classList.toggle("on", on);
        changed(seasons);
      });
    });
    chips.addEventListener("change", function () {
      buttons.forEach(function (b) { b.classList.remove("on"); });
    });
  });

  document.querySelectorAll(".chips-clear").forEach(function (link) {
    link.addEventListener("click", function (e) {
      e.preventDefault();
      var field = link.closest(".field");
      field.querySelectorAll(".chips input").forEach(function (b) { b.checked = false; });
      changed(field.querySelector(".chips"));
    });
  });

  /* An empty date is greyed as a whole; see app.css. */
  document.querySelectorAll('input[type="date"]').forEach(function (input) {
    function mark() { input.classList.toggle("empty", !input.value); }
    input.addEventListener("input", mark);
    input.addEventListener("change", mark);
    mark();
  });

  /* Research Group: nothing chosen means CRC, the default. Ticking All
     Research Groups clears the picker, and picking a group clears the box,
     so the two never disagree. The chip above says what will be shown. */
  var groupSelect = document.getElementById("research_group");
  var allGroups = document.getElementById("rg-all");
  var groupChip = document.getElementById("rg-chip");
  if (groupSelect && allGroups && groupChip) {
    var defaultLabel = "CRC (Default)";
    var describeGroups = function () {
      var names = Array.prototype.map.call(groupSelect.selectedOptions, function (o) { return o.value; });
      var label = allGroups.checked ? "All Research Groups"
        : !names.length ? defaultLabel
        : names.slice(0, 3).join(", ") + (names.length > 3 ? " and " + (names.length - 3) + " more" : "");
      groupChip.querySelector("strong").textContent = label;
      groupSelect.dataset.tagpicker = allGroups.checked ? "All Research Groups" : defaultLabel;
      groupSelect.dispatchEvent(new Event("tagpicker:refresh"));
    };
    allGroups.addEventListener("change", function () {
      if (allGroups.checked) {
        Array.prototype.forEach.call(groupSelect.options, function (o) { o.selected = false; });
      }
      describeGroups();
    });
    groupSelect.addEventListener("change", function () {
      if (groupSelect.selectedOptions.length) allGroups.checked = false;
      describeGroups();
    });
  }

  /* Each section heading shows how many of its filters are set, so a
     closed section never hides one. */
  document.querySelectorAll(".fsec").forEach(function (section) {
    var badge = section.querySelector(".fsec-count");
    if (!badge) return;   /* a section that is not a filter group, such as the Track File Manager's */
    function count() {
      var names = {};
      section.querySelectorAll("input, select").forEach(function (el) {
        if (!el.name) return;   /* the species picker's own boxes, not filters */
        if (el.id === "match-sightings-off") return;
        if (el.id === "match-sightings") {   /* on is the default, so only off is set */
          if (!el.checked) names[el.name] = true;
          return;
        }
        if (el.type === "checkbox" ? el.checked : el.value) names[el.name] = true;
      });
      badge.textContent = Object.keys(names).length || "";
    }
    section.addEventListener("change", count);
    section.addEventListener("input", count);
    count();
  });

})();

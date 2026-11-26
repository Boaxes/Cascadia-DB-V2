/*
 * The Track File Manager: the explorer on the left, the one open file with a
 * plain-text editor in the middle, the map, Effort and History on the right.
 * One file is open at a time: opening another takes its place.
 *
 * The explorer never holds more than a page of files: the list, its filters and
 * its count come from the server. An open file's text is held here until Save,
 * which sends the whole text and gets the checked, stored text back. Nothing
 * on this page changes data except through the server's endpoints, each of
 * which writes the Audit Log.
 */
(function () {
  var root = document.getElementById("ws");
  if (!root) return;

  var $ = function (id) { return document.getElementById(id); };
  var API = root.dataset.api, FILES = root.dataset.filesUrl;
  var ta = $("text"), gutter = $("gutter");
  var tabs = [], active = null, map, line = null, notice = null, fitted = false;
  /* With the line: arrowheads for the way the vessel went, and, when ticked, the dashed
     joins across the gaps that the Effort page draws. */
  var arrows = null, gaps = null, GAPS_KEY = "track-manager-gaps";
  /* Over the line: unsaved points in blue, the selected stretch in red. Both are drawn on one
     canvas, which stays quick with tens of thousands of points. */
  var canvas, blue = null, red = null, parsed = null, blueFor = null, selKey = null, marksFor = null;
  /* The chosen rows: one or more [first, last] ranges, merged. They follow the editor's own
     selection, except while they are the ones picked from the line numbers or the map
     (`picked` is the editor selection that picking set, so its own change event keeps them). */
  var ranges = [], chosen = [], picked = null, marked = [];
  var MARKS = 2000, TRACK_WEIGHT = 4;
  var rows = [], total = 0, everything = 0, loading = false, generation = 0;
  /* "" lists track files; "positions" lists Efforts with no track file that can be made into one. */
  var mode = "";

  function token() { return document.querySelector("[name=csrfmiddlewaretoken]").value; }
  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function call(path, body) {
    var options = { credentials: "same-origin" };
    if (body !== undefined) {
      var form = body instanceof FormData ? body : new URLSearchParams(body);
      options.method = "POST"; options.body = form; options.headers = { "X-CSRFToken": token() };
    }
    return fetch(API + path, options).then(function (r) {
      return r.json().then(function (data) { data.status = r.status; return data; },
                           function () { return { ok: false, status: r.status, message: "That did not work (" + r.status + ")." }; });
    });
  }

  /* ---- explorer: filtered and paged on the server */
  var DOT = { matched: "green", unmatched: "amber", blank: "grey", deleted: "red", draft: "amber" };
  var FILE_ICON = '<svg class="ico" viewBox="0 0 24 24"><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/></svg>';

  /* A draft's tab is named "p" and its Effort's number, so it cannot be mistaken for a track's. */
  function keyOf(r) { return mode === "positions" ? "p" + r.id : r.id; }
  function findTab(key) { return tabs.filter(function (x) { return String(x.id) === String(key); })[0]; }
  /* Whether the open text holds changes that closing it would lose. A draft that has only
     been opened holds none: its positions are still on the Effort. */
  function changed(t) { return t.text !== (t.draft ? t.original : t.saved); }
  function mayLeave() {
    return !active || !changed(active) || window.confirm("Discard unsaved changes to " + active.f.name + "?");
  }
  function hasMore() { return mode !== "positions" && rows.length < total; }

  function drawList() {
    var list = $("list");
    list.innerHTML = rows.map(function (r) {
      var t = findTab(keyOf(r));
      return '<div class="ws-item' + (active && String(active.id) === String(keyOf(r)) ? " on" : "") + '" data-id="' + keyOf(r) + '" title="' + esc(r.name) + '">' +
        FILE_ICON + '<span class="nm">' + esc(r.name) + "</span>" + (t && changed(t) ? '<span class="dirty"></span>' : "") +
        '<span class="dot ' + DOT[r.state] + '"></span></div>';
    }).join("") + (hasMore() ? '<div class="ws-more">Loading more files...</div>' : "") ||
      '<p class="muted small ws-pad" style="padding:12px">' + (mode === "positions" ? "No Efforts match." : "No track files match.") + '</p>';
    $("count").textContent = mode === "positions"
      ? (total > rows.length ? "Showing the newest " + fmt(rows.length) + " of " + fmt(total) + " Efforts with no track file. Search to narrow the list."
                             : fmt(total) + (total === 1 ? " Effort" : " Efforts") + " with no track file")
      : fmt(total) + " of " + fmt(everything) + " files";
  }

  function query(offset) {
    if (mode === "positions") return API + "positions/?" + new URLSearchParams({ q: $("q").value }).toString();
    var p = new URLSearchParams({ q: $("q").value, status: $("status").value, vessel: $("vessel").value, year: $("year").value,
                                  health: $("health").value, offset: offset });
    return FILES + "?" + p.toString();
  }

  function load(reset) {
    if (loading && !reset) return;
    if (reset) { generation++; rows = []; total = 0; $("list").scrollTop = 0; }
    var mine = generation;
    loading = true;
    fetch(query(rows.length), { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (data) {
      if (mine !== generation) return;
      rows = rows.concat(data.files); total = data.total; everything = data.all; loading = false;
      drawList();
      var list = $("list");
      if (hasMore() && list.scrollHeight <= list.clientHeight) load(false);
    }).catch(function () { loading = false; });
  }

  var typing;
  $("q").addEventListener("input", function () { clearTimeout(typing); typing = setTimeout(function () { load(true); }, 250); });
  ["status", "vessel", "year", "health"].forEach(function (i) { $(i).addEventListener("change", function () { load(true); }); });
  $("source").addEventListener("change", function () {
    mode = $("source").value;
    $("file-filters").hidden = mode === "positions";
    $("q").placeholder = mode === "positions" ? "Search date, vessel or group" : "Search file names";
    $("q").setAttribute("aria-label", $("q").placeholder);
    $("q").value = "";
    load(true);
  });
  $("list").addEventListener("click", function (e) {
    var i = e.target.closest("[data-id]"); if (!i) return;
    if (mode === "positions") openDraft(+i.dataset.id.slice(1)); else openFile(+i.dataset.id);
  });
  $("list").addEventListener("scroll", function () {
    var list = $("list");
    if (hasMore() && list.scrollTop + list.clientHeight > list.scrollHeight - 200) load(false);
  });

  /* ---- the open file */
  function openFile(id) {
    if (findTab(id) || !mayLeave()) return Promise.resolve();
    return call(id + "/").then(function (f) {
      if (f.status !== 200) { msg("error", "That file could not be opened."); return; }
      var t = { id: id, f: f, saved: f.text, text: f.text };
      tabs = [t]; activate(t);
    });
  }
  /* An Effort's recorded positions as an unsaved file. It is a draft: nothing is stored
     until Save As Track File. Its points are all unsaved, so the map shows them in blue, but
     opening it changes nothing, so it is not marked as changed until its text is edited. */
  function openDraft(effortId) {
    if (findTab("p" + effortId) || !mayLeave()) return Promise.resolve();
    return call("positions/" + effortId + "/").then(function (f) {
      if (!f.ok) { msg("error", f.message || "That draft could not be opened."); return; }
      var t = { id: "p" + effortId, draft: true, effort: effortId, f: f, original: f.text, saved: "", text: f.text };
      tabs = [t]; activate(t);
    });
  }
  /* The name of the open file, with the dot that says it has unsaved changes. */
  function drawTabs() {
    $("tabs").innerHTML = tabs.map(function (t) {
      return '<div class="tab on">' + FILE_ICON + esc(t.f.name) +
        (changed(t) ? '<span class="dirty"></span>' : "") + '<button type="button" class="x" data-close aria-label="Close">&times;</button></div>';
    }).join("");
  }
  $("tabs").addEventListener("click", function (e) {
    if (e.target.closest("[data-close]") && mayLeave()) closeOpen();
  });
  function closeOpen() { tabs = []; active = null; show(); }
  function activate(t) {
    active = t; fitted = false; ta.value = t.text; ta.readOnly = t.f.state === "deleted";
    ranges = []; picked = null; playAt = 0; pause();
    $("msg").hidden = true; show(); refresh(); fitSoon();
  }
  function show() {
    var on = !!active, gone = on && active.f.state === "deleted", draft = on && !!active.draft;
    $("bar").hidden = $("editor").hidden = $("status-bar").hidden = !on; $("empty").hidden = on;
    ["fill", "delete", "save"].forEach(function (b) { $(b).hidden = gone || draft; });
    $("revert").hidden = gone;
    $("save-new").hidden = !draft;
    $("restore").hidden = !gone;
    drawTabs(); drawList(); effort(); history(); checks();
    if (!on) {
      [line, arrows, gaps, blue, red, dots, events].forEach(function (l) { if (l) map.removeLayer(l); });
      line = arrows = gaps = blue = red = blueFor = selKey = marksFor = parsed = dots = dotsFor = events = eventsFor = null; clearNotice();
      ranges = []; chosen = []; picked = null; marked = []; player(null);
      $("effort").innerHTML = '<p class="muted small">No file open.</p>'; $("history").innerHTML = '<p class="muted small">No file open.</p>';
    }
  }

  /* ---- editor, status and map */
  function msg(kind, text, extra) {
    var m = $("msg"); m.hidden = false; m.innerHTML = '<li class="' + kind + '">' + esc(text) + (extra || "") + '</li>';
  }
  function clearNotice() { if (notice) { map.removeControl(notice); notice = null; } }
  function refresh() {
    if (!active) return;
    var t = parseTrack(ta.value, true);
    parsed = t;
    gutter.innerHTML = gutterHtml(t.lines, t.bad); marked = [];
    $("stats").textContent = fmt(t.points) + " points" + (t.points ? " - " + t.first.slice(0, 16) + " to " + t.last.slice(0, 16) + " UTC - " + t.nm.toFixed(1) + " nm" : "");
    $("errs").innerHTML = t.errors.length
      ? '<a href="#" data-line="' + t.errors[0][0] + '" class="bad-link">' + t.errors.length + (t.errors.length === 1 ? " row cannot be read" : " rows cannot be read") + ": line " + t.errors[0][0] + ", " + esc(t.errors[0][1]) + "</a>" : "Every row can be read";
    var dirty = ta.value !== active.saved;
    $("save").disabled = !dirty || t.errors.length > 0;
    $("save-new").disabled = t.errors.length > 0 || !t.points;
    $("revert").disabled = active.draft ? ta.value === active.original : !dirty;
    $("state").innerHTML = stateHtml();
    if (line) map.removeLayer(line);
    clearNotice(); line = null;
    if (t.points) {
      line = drawLine(map, t.runs, { color: mapColour("track"), weight: TRACK_WEIGHT });
      if (!fitted) { fitLine(); fitted = true; }
    } else {
      notice = L.control({ position: "topleft" });
      notice.onAdd = function () { var d = L.DomUtil.create("div", "map-notice"); d.style.position = "static"; d.textContent = active.f.state === "deleted" ? "This file is deleted." : active.draft ? "No points in this text." : "No points yet. Use Fill From File to add them."; return d; };
      notice.addTo(map);
    }
    drawExtras(); drawUnsaved(); drawPoints(); drawEvents(); drawSelected(true);
    drawTabs(); drawList(); player(t);
  }

  /* The arrowheads and, when ticked, the dashed joins. The arrows are spaced on the screen, so
     they are drawn again whenever the zoom changes. */
  function drawExtras() {
    if (gaps) map.removeLayer(gaps);
    gaps = null;
    if (active && parsed && parsed.points && $("gaps").checked) gaps = drawGaps(map, parsed.runs, { color: mapColour("track") });
    drawArrowLayer();
  }

  /* Where the arrows go, kept until the text, the zoom or the gaps tick changes, so a moving
     selection only recolours them. The joins carry arrows too when they are shown, or a file of
     scattered points would show no direction. */
  function arrowList() {
    var zoom = map.getZoom(), withGaps = $("gaps").checked;
    if (marksFor && marksFor.parsed === parsed && marksFor.zoom === zoom && marksFor.gaps === withGaps) return marksFor.marks;
    var runs = parsed.runs, nos = parsed.runLines;
    if (withGaps) { runs = runs.concat(gapJoins(parsed.runs)); nos = nos.concat(gapJoins(parsed.runLines)); }
    marksFor = { parsed: parsed, zoom: zoom, gaps: withGaps, marks: arrowMarks(map, runs, nos) };
    return marksFor.marks;
  }
  /* An arrow is red when both ends of the stretch it sits on are in one chosen range. */
  function onSelection(lines) {
    return !!lines && chosen.some(function (r) { return lines[0] >= r[0] && lines[1] <= r[1]; });
  }
  /* Ranges sorted and joined where they touch or overlap, so rows next to each other read as one stretch. */
  function merge(list) {
    var out = [];
    list.map(function (r) { return [Math.min(r[0], r[1]), Math.max(r[0], r[1])]; })
      .sort(function (a, b) { return a[0] - b[0]; })
      .forEach(function (r) {
        var last = out[out.length - 1];
        if (last && r[0] <= last[1] + 1) last[1] = Math.max(last[1], r[1]); else out.push(r);
      });
    return out;
  }
  /* The editor can show one selection only, so the line numbers of every chosen row are shaded too. */
  function markGutter() {
    var rows = gutter.children;
    marked.forEach(function (r) { for (var n = r[0]; n <= r[1] && n <= rows.length; n++) rows[n - 1].classList.remove("sel"); });
    chosen.forEach(function (r) { for (var n = r[0]; n <= r[1] && n <= rows.length; n++) rows[n - 1].classList.add("sel"); });
    marked = chosen.map(function (r) { return r.slice(); });
  }
  function drawArrowLayer() {
    if (arrows) map.removeLayer(arrows);
    arrows = null;
    if (!active || !parsed || !parsed.points) return;
    var yellow = mapColour("track"), colour = mapColour("track-selected");
    arrows = drawArrows(map, arrowList(), function (m) { return onSelection(m.lines) ? colour : yellow; }, "arrows");
  }

  /* Blue: points whose row is not in the saved text. Rebuilt only when the text or the saved
     text has changed, and thinned if a whole large file is unsaved. */
  function drawUnsaved() {
    var base = active.draft ? active.original : active.saved;
    if (blueFor && blueFor.tab === active && blueFor.text === ta.value && blueFor.saved === base) return;
    blueFor = { tab: active, text: ta.value, saved: base };
    if (blue) map.removeLayer(blue);
    blue = null;
    var pts = ta.value === base ? [] : unsavedPoints(parsed, ta.value, base);
    if (!pts.length) return;
    blue = L.layerGroup(thin(pts, MARKS).map(function (p) {
      return L.circleMarker(p, { renderer: canvas, radius: 4, color: "#fff", weight: 1, fillColor: mapColour("track-unsaved"), fillOpacity: 1, interactive: false });
    })).addTo(map);
  }

  /* Show Points: the file's points as dots, the same in a track file and in a draft made from
     positions. Spaced on the screen as the arrows are: along each run a point is drawn only once
     it is POINT_SPACING px from the last one drawn, so zoomed out the dots never pile into a
     band, and zoomed in every point shows. Worked out again when the zoom changes. */
  var dots = null, dotsFor = null, dotCanvas, POINT_SPACING = 32;
  function drawPoints() {
    var want = active && parsed && parsed.points && $("points").checked ? parsed : null;
    var zoom = map.getZoom();
    if (dotsFor && want && dotsFor.parsed === want && dotsFor.zoom === zoom) return;
    if (!dotsFor && !want) return;
    dotsFor = want ? { parsed: want, zoom: zoom } : null;
    if (dots) map.removeLayer(dots);
    dots = null;
    if (!want) return;
    var shown = [], least = POINT_SPACING * POINT_SPACING;
    want.runs.forEach(function (run) {
      var last = null;
      run.forEach(function (p) {
        var at = map.project(p, zoom);
        if (last) { var dx = at.x - last.x, dy = at.y - last.y; if (dx * dx + dy * dy < least) return; }
        last = at;
        shown.push(p);
      });
    });
    dots = L.layerGroup(shown.map(function (p) {
      return L.circleMarker(p, { renderer: dotCanvas, radius: 5, color: "#fff", weight: 1, fillColor: "#10212b", fillOpacity: 0.95, interactive: false });
    })).addTo(map);
  }

  /* Show Timeline Events: what was recorded during the matched Effort (weather readings, log
     entries, sightings), each a dot that opens a pop-up, as on the Explore and Effort maps. */
  var events = null, eventsFor = null;
  var EVENT_KINDS = { condition: ["Weather Reading", "amber-fg"], event: ["Log Entry", "sea-400"], sighting: ["Sighting", "accent"] };
  function drawEvents() {
    var want = active && $("events").checked ? active.f.timeline || [] : null;
    if (eventsFor === want) return;
    eventsFor = want;
    if (events) map.removeLayer(events);
    events = null;
    if (!want || !want.length) return;
    events = L.layerGroup(want.map(function (r) {
      var kind = EVENT_KINDS[r.kind] || [r.kind, "accent"];
      return L.circleMarker([r.lat, r.lon], { pane: "events", radius: 5, color: "#fff", weight: 1, fillColor: mapColour(kind[1]),
                                               fillOpacity: 0.95, bubblingMouseEvents: false })
        .bindPopup('<div class="tl-popup"><strong>' + esc(kind[0]) + "</strong>" + (r.at ? " at " + esc(r.at) : "") +
                   (r.label ? "<br>" + esc(r.label) : "") +
                   (r.url ? '<br><a href="' + esc(r.url) + '" data-modal-url="' + esc(r.url) + '">Open Sighting ' + esc(r.id) + "</a>" : "") +
                   '<br><span class="muted">' + esc(r.lat.toFixed(5)) + ", " + esc(r.lon.toFixed(5)) + "</span></div>");
    })).addTo(map);
  }

  /* Red: the selected rows drawn exactly as the track is, in red: the same line, the dashed
     joins between selected rows when gaps are shown, and the arrows on it. A whole file
     selected looks like the yellow track coloured red. A bare caret shows none. */
  function drawSelected(force) {
    if (!(picked && picked.start === ta.selectionStart && picked.end === ta.selectionEnd)) {
      var a = active ? selectedLines(ta.value, ta.selectionStart, ta.selectionEnd) : null;
      picked = null; ranges = a ? [a] : [];
    }
    var list = merge(ranges), key = JSON.stringify(list);
    if (!force && key === selKey) return;
    selKey = key; chosen = list;
    markGutter();
    if (red) map.removeLayer(red);
    red = null;
    drawArrowLayer();
    if (!chosen.length || !parsed || !parsed.points) return;
    var colour = mapColour("track-selected"), parts = [];
    var pieces = [].concat.apply([], chosen.map(function (r) { return pointsOnLines(parsed, r[0], r[1]); }));
    parts.push(trackLine(pieces, { color: colour, weight: TRACK_WEIGHT, interactive: false, pane: "selected" }));
    var joined = [];
    if ($("gaps").checked) {
      var ends = gapJoins(parsed.runLines);
      gapJoins(parsed.runs).forEach(function (j, i) { if (onSelection(ends[i])) joined.push(j); });
      if (joined.length) parts.push(gapLine(joined, { color: colour, pane: "selected" }));
    }
    /* Rows that make no line of their own (one row, or rows cut off by gaps on both sides)
       would show nothing, so their points are shown, but only then: a whole file selected
       must look like the yellow track. */
    if (!joined.length && !pieces.some(function (p) { return p.length > 1; })) {
      pieces.forEach(function (p) { p.forEach(function (q) {
        parts.push(L.circleMarker(q, { pane: "selected-dots", radius: 5, color: "#fff", weight: 1, fillColor: colour, fillOpacity: 1, interactive: false }));
      }); });
    }
    red = L.layerGroup(parts).addTo(map);
  }
  /* selectionchange does not fire for a textarea in every browser, so keys and the mouse ask too. */
  var selecting;
  function selectionMoved() {
    if (selecting) return;
    selecting = setTimeout(function () { selecting = null; drawSelected(false); }, 120);
  }
  document.addEventListener("selectionchange", function () { if (document.activeElement === ta) selectionMoved(); });
  ["keyup", "mouseup", "select"].forEach(function (e) { ta.addEventListener(e, selectionMoved); });

  /* ---- choosing rows without the browser's own text selection, which can leap for a moment
     to the start or end of the file when the pointer strays. Both ways below always choose
     whole rows, and the red follows as they move. */
  var anchorRow = null, rowDrag = false, starts = null, startsFor = null;
  /* Where each line starts in the text, worked out once for each version of it. */
  function lineStarts() {
    if (startsFor === ta.value) return starts;
    starts = [0];
    for (var i = ta.value.indexOf("\n"); i !== -1; i = ta.value.indexOf("\n", i + 1)) starts.push(i + 1);
    startsFor = ta.value;
    return starts;
  }
  /* Show what was picked: the editor selects the last range picked (it can hold one only; the
     line numbers show the rest), and the red is drawn. `reveal` is a row to bring to the middle. */
  function showPicked(reveal, caretRow) {
    var at = lineStarts(), r = ranges[ranges.length - 1];
    var top = reveal ? Math.max(0, (reveal - 1) * 18 - ta.clientHeight / 2) : ta.scrollTop;
    ta.focus({ preventScroll: true });
    if (r) {
      var first = Math.max(1, Math.min(r[0], r[1])), last = Math.min(at.length, Math.max(r[0], r[1]));
      var end = last < at.length ? at[last] - 1 : ta.value.length;
      ta.setSelectionRange(at[first - 1], Math.max(at[first - 1], end));
    } else {
      var c = at[Math.min(at.length, caretRow || 1) - 1];
      ta.setSelectionRange(c, c);
    }
    picked = { start: ta.selectionStart, end: ta.selectionEnd };
    ta.scrollTop = top; gutter.scrollTop = ta.scrollTop;
    drawSelected(false);
  }
  /* One pick at row n. A plain pick replaces what is chosen; Shift stretches the last range
     from where it started; Ctrl (Cmd on a Mac) adds the row, or takes it out if it is already
     chosen. Returns whether a drag may go on to stretch the range just started. */
  function pick(n, e, reveal) {
    var adding = e.ctrlKey || e.metaKey;
    if (!picked) ranges = chosen.map(function (r) { return r.slice(); });
    if (e.shiftKey && anchorRow && ranges.length) {
      ranges[ranges.length - 1] = [anchorRow, n];
    } else if (adding && chosen.some(function (r) { return n >= r[0] && n <= r[1]; })) {
      ranges = [].concat.apply([], merge(ranges).map(function (r) {
        return n < r[0] || n > r[1] ? [r] : [[r[0], n - 1], [n + 1, r[1]]].filter(function (x) { return x[0] <= x[1]; });
      }));
      anchorRow = null;
      showPicked(reveal, n);
      return false;
    } else {
      anchorRow = n;
      ranges = adding ? ranges.concat([[n, n]]) : [[n, n]];
    }
    showPicked(reveal);
    return true;
  }

  /* The line numbers: a click takes that row, Shift and a click takes every row from the last
     one chosen, and a drag down the numbers takes the rows it passes. The row is worked out
     from the pointer's height (every row is 18px), and past the top or bottom of the editor
     the drag scrolls it instead of jumping. */
  function rowAt(y) {
    var box = gutter.getBoundingClientRect(), pad = parseFloat(getComputedStyle(gutter).paddingTop) || 0;
    if (y > box.bottom) ta.scrollTop += Math.min(54, y - box.bottom);
    if (y < box.top) ta.scrollTop -= Math.min(54, box.top - y);
    gutter.scrollTop = ta.scrollTop;
    y = Math.min(Math.max(y, box.top + pad), box.bottom - 1);
    return Math.max(1, Math.min(lineStarts().length, Math.floor((y - box.top - pad + gutter.scrollTop) / 18) + 1));
  }
  gutter.addEventListener("mousedown", function (e) {
    if (e.button !== 0 || !active) return;
    e.preventDefault();
    rowDrag = pick(rowAt(e.clientY), e);
  });
  document.addEventListener("mousemove", function (e) {
    if (!rowDrag || !anchorRow || !ranges.length) return;
    ranges[ranges.length - 1] = [anchorRow, rowAt(e.clientY)];
    showPicked();
  });
  document.addEventListener("mouseup", function () { rowDrag = false; });
  /* Fit the map to the open file without animating: an animated fit is cut short when the map
     is resized under it, which happens as the panels below it fill in. */
  var fitAt = 0;
  function fitLine() { if (line) { map.fitBounds(line.getBounds(), { padding: [30, 30], animate: false }); fitAt = Date.now(); } }
  function fitSoon() { setTimeout(function () { map.invalidateSize({ pan: false }); fitLine(); }, 60); }
  ta.addEventListener("input", function () { picked = null; active.text = ta.value; clearTimeout(refresh.t); refresh.t = setTimeout(refresh, 250); });
  ta.addEventListener("scroll", function () { gutter.scrollTop = ta.scrollTop; });
  $("errs").addEventListener("click", function (e) {
    var a = e.target.closest("[data-line]"); if (!a) return; e.preventDefault();
    var n = +a.dataset.line, pos = 0, ls = ta.value.split("\n");
    for (var i = 0; i < n - 1; i++) pos += ls[i].length + 1;
    ta.focus(); ta.setSelectionRange(pos, pos + (ls[n - 1] || "").length); ta.scrollTop = Math.max(0, (n - 4) * 18);
  });
  $("revert").onclick = function () { ta.value = active.text = active.draft ? active.original : active.saved; $("msg").hidden = true; refresh(); };

  /* Take what the server says about a file after a change. */
  function adopt(t, data) {
    ["state", "blank", "effort", "efforts", "history", "checks", "timeline"].forEach(function (k) { if (k in data) t.f[k] = data[k]; });
    if (data.text !== undefined) { t.saved = t.text = data.text; }
    if (mode !== "positions") rows.forEach(function (r) { if (r.id === t.id) r.state = data.state; });
    if (t === active) { ta.value = t.text; effort(); history(); checks(); refresh(); }
  }

  $("save").onclick = function () {
    var t = active; $("save").disabled = true;
    call(t.id + "/save/", { text: ta.value }).then(function (data) {
      if (data.ok) { adopt(t, data); msg("success", data.message); return; }
      msg("error", data.message + (data.errors && data.errors.length ? " First: line " + data.errors[0][0] + ", " + data.errors[0][1] : ""));
      refresh();
    });
  };

  /* Save As Track File: the server checks everything again, then the draft's tab becomes the saved track's. */
  $("save-new").onclick = function () {
    var t = active; $("save-new").disabled = true;
    call("positions/" + t.effort + "/save/", { text: ta.value }).then(function (data) {
      if (!data.ok) {
        msg("error", data.message + (data.errors && data.errors.length ? " First: line " + data.errors[0][0] + ", " + data.errors[0][1] : ""));
        refresh(); return;
      }
      tabs = []; active = null;
      load(true);
      openFile(data.id).then(function () { msg("success", data.message); });
    });
  };

  $("fill").onclick = function () {
    if (active.text !== active.saved && !window.confirm("Fill From File replaces this file, and your unsaved changes would be lost. Continue?")) return;
    var a = document.createElement("a"); a.href = "#"; a.dataset.modalUrl = API.replace(/api\/$/, "") + active.id + "/fill/";
    document.body.appendChild(a); a.click(); a.remove();
  };
  $("delete").onclick = function () {
    var t = active;
    if (!window.confirm("Delete " + t.f.name + "? The file is kept, and it can be restored.")) return;
    call(t.id + "/delete/", {}).then(function (data) {
      if (!data.ok) { msg("error", data.message); return; }
      closeOpen();
      load(true);
      msg("success", data.message + " ", '<button class="btn btn-small" type="button" data-restore-id="' + t.id + '">Restore</button>');
    });
  };
  $("restore").onclick = function () { restore(active.id); };
  $("msg").addEventListener("click", function (e) { var b = e.target.closest("[data-restore-id]"); if (b) restore(+b.dataset.restoreId); });
  function restore(id) {
    call(id + "/restore/", {}).then(function (data) {
      if (!data.ok) { msg("error", data.message); return; }
      if (active && active.id === id) { tabs = []; active = null; }
      load(true); openFile(id).then(function () { msg("success", data.message); });
    });
  }

  /* The Fill From File pop-up has replaced a file's points. */
  window.addEventListener("track-changed", function (e) {
    var t = tabs.filter(function (x) { return x.id === e.detail.id; })[0];
    if (!t) return;
    call(t.id + "/").then(function (f) { adopt(t, f); });
  });
  /* The Import Files pop-up has added some. */
  window.addEventListener("tracks-imported", function (e) {
    load(true);
    if (e.detail && e.detail.id) openFile(e.detail.id);
  });

  /* ---- map */
  /* Half zoom steps, so a track can fill the map rather than stop a whole step short. */
  /* Shift and a click on the map chooses rows, so Shift does not also start a box zoom. */
  map = L.map("map", { zoomSnap: 0.5, boxZoom: false }); basemap(map); map.setView([47.5, -123], 6);
  /* The blue and the red have a layer of their own above the track's line, so the red line
     always shows over the yellow one whichever was drawn first. */
  map.createPane("marks").style.zIndex = 450;
  map.getPane("marks").style.pointerEvents = "none";
  canvas = L.canvas({ padding: 0.5, pane: "marks" });
  /* From the bottom: the yellow line, the red one over it, then the arrows over both, then the
     blue points, then the point of a single selected row, which nothing may hide. */
  [["selected", 420], ["arrows", 440], ["selected-dots", 460]].forEach(function (p) {
    map.createPane(p[0]).style.zIndex = p[1];
    map.getPane(p[0]).style.pointerEvents = "none";
  });
  map.createPane("events").style.zIndex = 470;
  /* Show Points has a canvas of its own, over the yellow line and under the red. */
  map.createPane("points").style.zIndex = 410;
  map.getPane("points").style.pointerEvents = "none";
  dotCanvas = L.canvas({ padding: 0.5, pane: "points" });
  map.on("zoomend", function () { drawExtras(); drawPoints(); });
  /* The two bars beside and under the map resize it; the sizes are kept for next time, and a
     double-click puts a bar back where it started. */
  var SIZES_KEY = "track-manager-sizes", sizes = {};
  try { sizes = JSON.parse(window.localStorage.getItem(SIZES_KEY) || "{}") || {}; } catch (e) { sizes = {}; }
  function setSize(name, px) {
    if (px) root.style.setProperty(name, Math.round(px) + "px"); else root.style.removeProperty(name);
    sizes[name] = px ? Math.round(px) : null;
    try { window.localStorage.setItem(SIZES_KEY, JSON.stringify(sizes)); } catch (e) { /* no storage */ }
  }
  ["--ws-side", "--ws-map"].forEach(function (name) { if (sizes[name]) root.style.setProperty(name, sizes[name] + "px"); });
  function splitter(bar, name, measure, sign, low, high) {
    bar.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      e.preventDefault();
      var from = measure(), start = sign.axis === "x" ? e.clientX : e.clientY, centre = map.getCenter();
      bar.setPointerCapture(e.pointerId); bar.classList.add("on"); root.classList.add("dragging");
      function move(ev) {
        var moved = (sign.axis === "x" ? ev.clientX : ev.clientY) - start;
        setSize(name, Math.min(high(), Math.max(low, from + sign.by * moved)));
      }
      function stop() {
        bar.removeEventListener("pointermove", move); bar.removeEventListener("pointerup", stop); bar.removeEventListener("pointercancel", stop);
        bar.classList.remove("on"); root.classList.remove("dragging");
        /* The map kept its top left corner while it grew; put back what was in its middle, at once. */
        map.invalidateSize({ pan: false });
        map.setView(centre, map.getZoom(), { animate: false });
      }
      bar.addEventListener("pointermove", move); bar.addEventListener("pointerup", stop); bar.addEventListener("pointercancel", stop);
    });
    bar.addEventListener("dblclick", function () { setSize(name, null); });
  }
  /* Dragging the side bar left widens the map; the text keeps at least 360px. */
  splitter($("split-side"), "--ws-side", function () { return root.querySelector(".ws-side").getBoundingClientRect().width; },
           { axis: "x", by: -1 }, 320, function () { return root.getBoundingClientRect().width - 320 - 6 - 360; });
  /* Dragging the bar under the map down makes it taller. */
  splitter($("split-map"), "--ws-map", function () { return root.querySelector(".ws-map").getBoundingClientRect().height; },
           { axis: "y", by: 1 }, 200, function () { return Math.max(200, window.innerHeight - 160); });

  /* A click on the track chooses the row nearest it (within 20px) and brings it to the middle
     of the editor. Shift and Ctrl work as they do on the line numbers. */
  map.on("click", function (e) {
    if (!active || !parsed || !parsed.points) return;
    var at = e.containerPoint, best = null, nearest = 20 * 20;
    parsed.runs.forEach(function (r, i) {
      var nos = parsed.runLines[i];
      for (var k = 0; k < r.length; k++) {
        var p = map.latLngToContainerPoint(r[k]), dx = p.x - at.x, dy = p.y - at.y, d = dx * dx + dy * dy;
        if (d < nearest) { nearest = d; best = nos[k]; }
      }
    });
    if (best !== null) pick(best, e.originalEvent, best);
  });

  /* ---- playing the track: the whole file in PLAY_SECONDS, with the time between any two
     points squeezed by the same amount, so a minute spent in one place takes as long as a
     minute spent moving. The points are taken in time order. Across a gap (no point for more
     than 30 minutes) the marker waits, hollow, where the GPS went quiet. */
  var PLAY_SECONDS = 20, GAP_MS = 30 * 60 * 1000, HEADING_METRES = 25;
  var timeline = null, timelineFor = null, playAt = 0, playing = null, marker = null, zooming = false;
  map.on("zoomanim", function () { zooming = true; });
  map.on("zoomend", function () { zooming = false; if (marker) drawPlayer(); });
  /* Metres between two [lat, lon] points, flat: close enough over a few hundred metres. */
  function apart(a, b) {
    var dy = (b[0] - a[0]) * 111320, dx = (b[1] - a[1]) * 111320 * Math.cos(a[0] * Math.PI / 180);
    return Math.sqrt(dx * dx + dy * dy);
  }
  function bearing(a, b) {
    var dy = b[0] - a[0], dx = (b[1] - a[1]) * Math.cos(a[0] * Math.PI / 180);
    return Math.atan2(dx, dy) * 180 / Math.PI;
  }
  /* The points in time order, each with the way the boat faces there: towards the first later
     point at least 25 m away, so a second of GPS jitter does not spin it. Where it does not
     move it keeps the way it last faced. */
  function points() {
    if (timelineFor === parsed) return timeline;
    timelineFor = parsed; timeline = [];
    if (parsed && parsed.points) {
      parsed.runs.forEach(function (r, i) {
        var times = parsed.runTimes[i];
        for (var k = 0; k < r.length; k++) timeline.push({ t: times[k], at: r[k] });
      });
      timeline.sort(function (a, b) { return a.t - b.t; });
      var facing = 0;
      for (var i = 0; i < timeline.length; i++) {
        for (var j = i + 1; j < timeline.length && j < i + 200 && timeline[j].t - timeline[j - 1].t <= GAP_MS; j++) {
          if (apart(timeline[i].at, timeline[j].at) >= HEADING_METRES) { facing = bearing(timeline[i].at, timeline[j].at); break; }
        }
        timeline[i].h = facing;
      }
    }
    return timeline;
  }
  /* Where the vessel was at time t: between the two points either side, or waiting at the
     last one before a gap. */
  function placeAt(t) {
    var list = points(), lo = 0, hi = list.length - 1;
    while (lo < hi) { var mid = (lo + hi + 1) >> 1; if (list[mid].t <= t) lo = mid; else hi = mid - 1; }
    var a = list[lo], b = list[lo + 1];
    if (!b || t <= a.t) return { at: a.at, h: a.h, quiet: false };
    if (b.t - a.t > GAP_MS) return { at: a.at, h: a.h, quiet: true };
    var f = (t - a.t) / (b.t - a.t);
    return { at: [a.at[0] + (b.at[0] - a.at[0]) * f, a.at[1] + (b.at[1] - a.at[1]) * f], h: a.h, quiet: false };
  }
  function span() {
    var list = points();
    return list.length > 1 ? [list[0].t, list[list.length - 1].t] : null;
  }
  function clock(ms) { return new Date(ms).toISOString().slice(11, 19); }
  function lasting(ms) {
    var minutes = Math.round(ms / 60000), h = Math.floor(minutes / 60), m = minutes % 60;
    return h ? h + " h " + m + " min" : Math.max(1, m) + " min";
  }
  /* A boat seen from above, bow up; turned to the way it faces. */
  var BOAT = '<svg width="16" height="16" viewBox="0 0 16 16"><path d="M8 .8C10.6 3.4 11.3 7 11 15.2H5C4.7 7 5.4 3.4 8 .8z" ' +
             'fill="#fff" stroke="#10212b" stroke-width="1.4" stroke-linejoin="round"/><path d="M6.2 11.2h3.6" stroke="#10212b" stroke-width="1.2"/></svg>';
  /* Put the boat, the slider and the clock where playAt (0 to 1) says. */
  function drawPlayer() {
    var s = span();
    if (!s) return;
    var t = s[0] + (s[1] - s[0]) * playAt, here = placeAt(t);
    if (!marker) {
      marker = L.marker(here.at, { icon: L.divIcon({ className: "track-boat", html: BOAT, iconSize: [16, 16], iconAnchor: [8, 8] }),
                                   interactive: false, keyboard: false, zIndexOffset: 1000 }).addTo(map);
    }
    /* While the map zooms, a marker moved is placed for the zoom it is leaving, far from the
       track for a moment, so the boat waits until the zoom ends (see zoomend below). */
    if (!zooming) marker.setLatLng(here.at);
    var el = marker.getElement();
    if (el) {
      el.classList.toggle("quiet", here.quiet);
      el.firstChild.style.transform = "rotate(" + here.h.toFixed(1) + "deg)";
    }
    $("scrub").value = Math.round(playAt * 10000);
    $("scrub").style.setProperty("--p", (playAt * 100).toFixed(2) + "%");
    $("play-time").textContent = clock(t);
  }
  /* Called after every redraw: a file with points can be played, anything else cannot. */
  function player(t) {
    var s = t && t.points ? span() : null;
    $("play").disabled = $("scrub").disabled = !s;
    if (!s) {
      pause();
      if (marker) { map.removeLayer(marker); marker = null; }
      $("play-time").textContent = "--:--:--"; $("play-end").textContent = "--:--:-- UTC";
      $("scrub").value = 0; $("scrub").style.setProperty("--p", "0%");
      $("play").title = t ? "This file has fewer than two points with times, so it cannot be played." : "Open a file to play its track.";
      return;
    }
    $("play-end").textContent = clock(s[1]) + " UTC";
    $("play").title = "Play the " + lasting(s[1] - s[0]) + " track in " + PLAY_SECONDS + " seconds";
    drawPlayer();
  }
  function playButton(on) {
    $("play").classList.toggle("on", on);
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
  }
  function pause() {
    if (playing) cancelAnimationFrame(playing.frame);
    playing = null;
    playButton(false);
  }
  function play() {
    if (playAt >= 1) playAt = 0;
    var from = playAt, began = performance.now();
    playing = {};
    playButton(true);
    (function frame(now) {
      if (!playing) return;
      playAt = Math.min(1, from + (now - began) / (PLAY_SECONDS * 1000));
      drawPlayer();
      if (playAt >= 1) { pause(); return; }
      playing.frame = requestAnimationFrame(frame);
    })(began);
  }
  $("play").addEventListener("click", function () { if (playing) pause(); else play(); });
  $("scrub").addEventListener("input", function () { pause(); playAt = +$("scrub").value / 10000; drawPlayer(); });

  /* The map is measured again whenever its size changes: a bar dragged or the window resized. */
  if (window.ResizeObserver) new ResizeObserver(function () {
    map.invalidateSize({ pan: false });
    /* Just opened, so nobody has moved the map yet: fit the file to the size it has now. */
    if (Date.now() - fitAt < 2000) fitLine();
  }).observe($("map"));
  /* The three ticks under the map, each kept for next time, all off at first. */
  [["gaps", GAPS_KEY, function () { drawExtras(); drawSelected(true); }],
   ["points", "track-manager-points", function () { drawPoints(); }],
   ["events", "track-manager-events", function () { drawEvents(); }]].forEach(function (x) {
    try { $(x[0]).checked = window.localStorage.getItem(x[1]) === "1"; } catch (e) { /* no storage */ }
    $(x[0]).addEventListener("change", function () {
      try { window.localStorage.setItem(x[1], $(x[0]).checked ? "1" : "0"); } catch (e) { /* no storage */ }
      x[2]();
    });
  });

  /* ---- effort: an Effort has one track file at most */
  function stateHtml() {
    var f = active.f;
    if (f.state === "deleted") return '<span class="pill pill-red">Deleted</span>';
    if (f.draft) return '<span class="pill pill-amber">Not Saved</span>';
    if (f.blank) return '<span class="pill pill-grey">Blank</span>';
    return f.effort ? '<span class="pill pill-green">Matched</span>' : '<span class="pill pill-amber">Not Matched</span>';
  }
  function pair(k, v) { return '<div class="pair"><dt>' + k + "</dt><dd>" + v + "</dd></div>"; }
  function effort(picking) {
    if (!active) return;
    var el = $("effort"), f = active.f;
    if (f.state === "deleted") {
      el.innerHTML = '<p class="small muted">Deleted by ' + esc(f.deleted.who) + " on " + esc(f.deleted.at.slice(0, 10)) +
        ". Restore brings back the file and its Effort match.</p>";
      return;
    }
    if (f.draft) {
      var d = f.effort;
      el.innerHTML = '<div class="detail-grid">' + pair("Effort", '<a href="' + d.url + '" data-modal-url="' + d.url + '">' + d.id + "</a>") +
        pair("Date", esc(d.date || "-")) + pair("Vessel", esc(d.vessel || "-")) + pair("Locality", esc(d.locality || "-")) + "</div>" +
        '<p class="small muted">Not saved yet. These are the positions recorded on this Effort. Save As Track File creates its track file.</p>';
      return;
    }
    if (f.effort && !picking) {
      var e = f.effort;
      el.innerHTML = '<div class="detail-grid">' + pair("Effort", '<a href="' + e.url + '" data-modal-url="' + e.url + '">' + e.id + "</a>") +
        pair("Date", esc(e.date || "-")) + pair("Vessel", esc(e.vessel || "-")) + pair("Locality", esc(e.locality || "-")) + "</div>" +
        (f.shared.length ? '<p class="small muted">Another track record names this file too, so changes here apply to both.</p>' : "") +
        '<div class="row-actions"><button class="btn btn-small" type="button" id="e-change">Change</button><button class="btn btn-small" type="button" id="e-remove">Remove Match</button></div>';
      $("e-change").onclick = function () { effort(true); };
      $("e-remove").onclick = function () {
        call(active.id + "/unmatch/", {}).then(function (data) {
          if (data.ok) { adopt(active, data); msg("success", data.message); } else msg("error", data.message);
        });
      };
      return;
    }
    var list = f.efforts.slice().sort(function (a, b) { return (b.vessel === f.vessel) - (a.vessel === f.vessel); });
    el.innerHTML = '<p class="small muted">' + (f.group ? esc(f.group) + " Efforts" : "Efforts") + " on " + esc(f.date || "an unknown date") + ". An Effort has one track file at most.</p>" +
      '<table class="data pick"><tbody>' + (list.map(function (x) {
        var taken = x.taken && !(f.effort && x.id === f.effort.id);
        return '<tr class="' + (taken ? "taken" : "") + '"><td><input type="radio" name="eff" value="' + x.id + '"' + (taken ? " disabled" : "") + ' aria-label="Effort ' + x.id + '"></td><td>' + x.id + "</td><td>" + esc(x.vessel || "-") + '</td><td class="right">' +
          (taken ? '<span class="small">Has a track file</span>' : x.vessel && x.vessel === f.vessel ? '<span class="pill pill-green">Same Vessel</span>' : "") + "</td></tr>";
      }).join("") || '<tr><td class="muted">No Effort on this date.</td></tr>') + "</tbody></table>" +
      '<div class="row-actions"><button class="btn btn-primary btn-small" type="button" id="e-save" disabled>Match To Effort</button>' +
      (f.effort ? '<button class="btn btn-small" type="button" id="e-cancel">Cancel</button>' : "") + "</div>";
    el.querySelector("tbody").addEventListener("change", function () { $("e-save").disabled = false; });
    $("e-save").onclick = function () {
      var r = el.querySelector("input:checked"); if (!r) return;
      call(active.id + "/match/", { effort: r.value }).then(function (data) {
        if (data.ok) { adopt(active, data); msg("success", data.message); } else msg("error", data.message);
      });
    };
    if ($("e-cancel")) $("e-cancel").onclick = function () { effort(); };
  }

  /* ---- history: each Save keeps the earlier file */
  function history() {
    if (!active) return;
    $("history").innerHTML = historyHtml(active.f.history, esc);
  }
  /* ---- data checks: what the server found in the saved file (survey/track_checks.py) */
  /* A stretch of rows as a link that chooses it: "1,204" or "1,204 to 1,205". */
  function rangeLink(r) {
    return '<a href="#" data-rows="' + r[0] + "-" + r[1] + '">' + fmt(r[0]) + (r[1] !== r[0] ? " to " + fmt(r[1]) : "") + "</a>";
  }
  function rangeLinks(ranges, shown) {
    return ranges.slice(0, shown).map(rangeLink).join(", ") + (ranges.length > shown ? ", and more" : "");
  }
  function hours(minutes) {
    var h = Math.floor(minutes / 60), m = Math.round(minutes % 60);
    return h ? h + " h " + m + " min" : m + " min";
  }
  function checks() {
    var el = $("checks");
    if (!active) { el.innerHTML = '<p class="muted small">No file open.</p>'; return; }
    var f = active.f, c = f.checks;
    if (f.state === "deleted") { el.innerHTML = '<p class="muted small">Not checked: this file is deleted.</p>'; return; }
    if (f.draft) { el.innerHTML = '<p class="muted small">Checked once it is saved as a track file.</p>'; return; }
    if (!c) { el.innerHTML = '<p class="muted small">Not checked yet. Files are checked when saved or imported, and every night at 2am.</p>'; return; }
    var facts = [["Health", c.problems.length ? esc(c.problems.map(function (p) { return p.label; }).join(", ")) : "Good"]];
    c.problems.forEach(function (p) {
      facts.push([esc(p.label), esc(p.detail) + '<span class="rows">Rows ' + rangeLinks(p.ranges, 6) + "</span>"]);
    });
    facts.push(["Points", fmt(c.points)]);
    if (c.first) {
      facts.push(["Time", esc(c.first.slice(0, 16)) + " to " + esc(c.first.slice(0, 10) === c.last.slice(0, 10) ? c.last.slice(11, 16) : c.last.slice(0, 16)) + " UTC"]);
      facts.push(["Duration", hours(c.minutes)]);
    }
    facts.push(["Distance", c.distance_nm.toFixed(1) + " nm"]);
    if (c.average_knots !== null) facts.push(["Average Speed", c.average_knots.toFixed(1) + " knots"]);
    if (c.top_knots !== null) facts.push(["Top Speed", c.top_knots.toFixed(1) + " knots, rows " + rangeLink(c.top_knots_rows)]);
    facts.push(["Gaps Over 30 Min", c.gaps ? c.gaps + ", the longest " + hours(c.longest_gap_minutes) : "None"]);
    if (c.same_time_rows) facts.push(["Rows Sharing a Time", fmt(c.same_time_rows)]);
    if (c.repeated_rows) facts.push(["Repeated Rows", fmt(c.repeated_rows)]);
    var html = '<dl class="ws-facts">' + facts.map(function (x) { return "<dt>" + x[0] + "</dt><dd>" + x[1] + "</dd>"; }).join("") + "</dl>";
    html += '<p class="ws-checked">Checked ' + esc(c.checked_at.slice(0, 16).replace("T", " ")) + " UTC" +
      (changed(active) ? ". These are the figures of the saved file, not of the unsaved changes." : ".") + "</p>";
    el.innerHTML = html;
  }
  /* A stretch in Track Health chooses those rows, as a drag down their line numbers does. */
  $("checks").addEventListener("click", function (e) {
    var a = e.target.closest("[data-rows]"); if (!a || !active) return;
    e.preventDefault();
    var r = a.dataset.rows.split("-").map(Number);
    ranges = [r]; anchorRow = r[0];
    showPicked(r[0]);
  });

  $("history").addEventListener("click", function (e) {
    var b = e.target.closest("[data-version]"); if (!b) return;
    var x = active.f.history[+b.dataset.version];
    fetch(API + active.id + "/version/?key=" + encodeURIComponent(x.version), { credentials: "same-origin" })
      .then(function (r) { return r.json(); }).then(function (data) {
        if (!data.ok) { msg("error", "That version could not be loaded."); return; }
        ta.value = active.text = data.text; refresh(); msg("info", "That version is loaded. Save to keep it.");
      });
  });

  document.addEventListener("click", function (e) { if (e.target.closest("[data-close-modal]")) document.querySelector("#modal .modal-close").click(); });
  window.addEventListener("beforeunload", function (e) {
    if (tabs.some(changed)) { e.preventDefault(); e.returnValue = ""; }
  });

  load(true);
  /* ?open=<id> opens that file; ?import_effort=<id> opens Import Files for that Effort;
     ?positions_effort=<id> opens that Effort's draft made from its positions. */
  if (root.dataset.open && /^\d+$/.test(root.dataset.open)) openFile(+root.dataset.open);
  if (root.dataset.positionsEffort && /^\d+$/.test(root.dataset.positionsEffort)) openDraft(+root.dataset.positionsEffort);
  if (root.dataset.importEffort && /^\d+$/.test(root.dataset.importEffort)) {
    var a = document.createElement("a"); a.href = "#"; a.dataset.modalUrl = root.dataset.importUrl + "?effort=" + root.dataset.importEffort;
    document.body.appendChild(a); setTimeout(function () { a.click(); a.remove(); }, 50);
  }
})();

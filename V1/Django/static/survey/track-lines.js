/*
 * A track file's text, read the way the server reads it (gps/tracks.py), so the
 * editor can mark bad lines and redraw the map as you type, and the pop-ups can
 * draw a file before anything is saved. The server checks again on Save.
 */
(function () {
  var TIME = { datetimeutc: 1, datetime: 1, datetime_utc: 1 };
  var LAT = { latitude: 1, lat: 1 };
  var LON = { longitude: 1, lon: 1 };
  var GAP = 30 * 60 * 1000;   /* a silence this long ends one line and starts another */

  /* "2013-01-04 9:57" is "2013-01-04 09:57:00"; null if it cannot be a time. */
  function stamp(value) {
    var halves = value.split(" ");
    if (halves.length !== 2) return null;
    var d = halves[0].split("-"), c = halves[1].split(":");
    if (d.length !== 3 || (c.length !== 2 && c.length !== 3)) return null;
    if (c.length === 2) c.push("0");
    var n = d.concat(c).map(function (x) { return /^\d+$/.test(x) ? +x : NaN; });
    if (n.some(isNaN)) return null;
    if (!(n[1] >= 1 && n[1] <= 12 && n[2] >= 1 && n[2] <= 31 && n[3] <= 23 && n[4] <= 59 && n[5] <= 59 && n[0] > 1970)) return null;
    function p(x, w) { return ("0000" + x).slice(-w); }
    return p(n[0], 4) + "-" + p(n[1], 2) + "-" + p(n[2], 2) + " " + p(n[3], 2) + ":" + p(n[4], 2) + ":" + p(n[5], 2);
  }

  /* With `withLines` set, the result also has `runLines`: for each run, the
     line number in the text of each of its points, so the editor can tie a
     selection or an unsaved row to a place on the map, and `runTimes`, each
     point's time in milliseconds, for playing the track. Callers that do not
     ask get exactly what they always did. */
  window.parseTrack = function (text, withLines) {
    var lines = text.split(/\r?\n/), index = {}, errs = [], bad = {}, runs = [], run = null, last = null;
    var runLines = [], runNos = null, runTimes = [], runAt = null;
    var points = 0, first = null, finalTime = null, nm = 0;
    if (lines.length && lines[lines.length - 1] === "") lines.pop();
    (lines[0] || "").split(",").forEach(function (name, i) {
      var k = name.trim().toLowerCase();
      if (TIME[k] && index.time === undefined) index.time = i;
      else if (LAT[k]) index.lat = i;
      else if (LON[k]) index.lon = i;
    });
    if (index.time === undefined || index.lat === undefined || index.lon === undefined) {
      errs.push([1, "The first line must be datetime_utc,latitude,longitude"]); bad[1] = 1;
      var none = { points: 0, errors: errs, bad: bad, lines: Math.max(lines.length, 1), nm: 0, first: null, last: null, runs: [] };
      if (withLines) { none.runLines = []; none.runTimes = []; }
      return none;
    }
    for (var i = 1; i < lines.length; i++) {
      if (lines[i] === "") continue;
      var f = lines[i].split(","), n = i + 1, why = null, when = null, lat = NaN, lon = NaN;
      if (f.length <= Math.max(index.time, index.lat, index.lon)) why = "Needs three values: date and time, latitude, longitude";
      else {
        when = stamp(f[index.time].trim());
        lat = f[index.lat].trim() === "" ? NaN : +f[index.lat]; lon = f[index.lon].trim() === "" ? NaN : +f[index.lon];
        if (when === null) why = "Date and time must look like 2024-09-24 16:05:27";
        else if (isNaN(lat) || isNaN(lon)) why = "Latitude and longitude must be numbers";
        else if (!(Math.abs(lat) <= 90)) why = "Latitude " + f[index.lat].trim() + " is outside -90 to 90";
        else if (!(Math.abs(lon) <= 180)) why = "Longitude " + f[index.lon].trim() + " is outside -180 to 180";
        else if (lon >= 0) why = "Longitude " + f[index.lon].trim() + " must be west of 0 (negative)";
      }
      if (why) { errs.push([n, why]); bad[n] = 1; continue; }
      var at = Date.UTC(+when.slice(0, 4), +when.slice(5, 7) - 1, +when.slice(8, 10), +when.slice(11, 13), +when.slice(14, 16), +when.slice(17, 19));
      var gap = last && at - last.at > GAP;
      if (!run || gap) { run = []; runs.push(run); runNos = []; runLines.push(runNos); runAt = []; runTimes.push(runAt); }
      else {
        var r = 3440.065, q = Math.PI / 180;
        var x = Math.pow(Math.sin((lat - last.lat) * q / 2), 2) + Math.cos(last.lat * q) * Math.cos(lat * q) * Math.pow(Math.sin((lon - last.lon) * q / 2), 2);
        nm += 2 * r * Math.asin(Math.sqrt(x));
      }
      run.push([lat, lon]); runNos.push(n); runAt.push(at);
      last = { at: at, lat: lat, lon: lon };
      points++; if (!first) first = when; finalTime = when;
    }
    var out = { points: points, errors: errs, bad: bad, lines: Math.max(lines.length, 1), nm: nm, first: first, last: finalTime, runs: runs };
    if (withLines) { out.runLines = runLines; out.runTimes = runTimes; }
    return out;
  };

  /* The line numbers beside the editor: one block per number, every one a
     single 18px row (app.css, .gutter .n), a bad line's marked. There is no
     text between them, so nothing can add a row. */
  window.gutterHtml = function (count, bad) {
    var rows = [];
    for (var i = 1; i <= count; i++) rows.push('<span class="n' + (bad[i] ? ' bad' : '') + '">' + i + '</span>');
    return rows.join("");
  };

  /* The History panel: a row for each change, a Restore button on the ones
     that kept the earlier file, and the sentence about Restore only when one
     does. `esc` makes text safe for HTML. */
  window.historyHtml = function (h, esc) {
    if (!h.length) return '<p class="small muted">No changes have been made to this file yet.</p>';
    var rows = h.map(function (x, i) {
      return '<tr><td class="nowrap small">' + (x.at ? esc(x.at.slice(0, 16).replace("T", " ")) : "") + '</td><td class="small">' + esc(x.who || "") +
        '<div class="muted">' + esc(x.what) + (x.note && x.what !== "Earlier Version" ? ": " + esc(x.note) : "") + '</div></td><td class="right">' +
        (x.version ? '<button class="btn btn-small" type="button" data-version="' + i + '">Restore</button>' : "") + "</td></tr>";
    }).join("");
    var kept = h.some(function (x) { return x.version; });
    return '<table class="data"><tbody>' + rows + '</tbody></table>' + (kept
      ? '<p class="small muted" style="margin:8px 0 0">Restore loads the file as it was before that change into the editor. Save to keep it.</p>' : "");
  };

  window.fmt = function (n) { return n.toLocaleString("en-US"); };

  /* The runs of a parsed file as one line on the map. A long file is thinned
     to every few points, which the eye cannot tell from the real line. */
  window.drawLine = function (map, runs, style) {
    return trackLine(runs, style).addTo(map);
  };
  /* The same line, not yet on a map. */
  window.trackLine = function (runs, style) {
    var total = runs.reduce(function (a, r) { return a + r.length; }, 0), step = Math.max(1, Math.ceil(total / 6000));
    var shown = runs.map(function (r) {
      var kept = r.filter(function (_, i) { return i % step === 0 || i === r.length - 1; });
      return kept;
    });
    return L.polyline(shown, style);
  };

  /* The dashed joins the Effort page draws: from where each run ends to where
     the next begins. Nothing between the two was recorded, which is why the
     line breaks there, so the join is thin and dashed. */
  window.gapJoins = function (runs) {
    var joins = [];
    for (var i = 1; i < runs.length; i++) {
      var before = runs[i - 1];
      joins.push([before[before.length - 1], runs[i][0]]);
    }
    return joins;
  };
  window.drawGaps = function (map, runs, style) {
    var joins = gapJoins(runs);
    return joins.length ? gapLine(joins, style).addTo(map) : null;
  };
  /* Joins drawn as dashes, not yet on a map. */
  window.gapLine = function (joins, style) {
    return L.polyline(joins, {
      color: style.color, weight: 1.6, opacity: 0.75, dashArray: "5 6", interactive: false, pane: style.pane || "overlayPane"
    });
  };

  /* Where the arrowheads go along the runs, pointing the way the vessel went.
     They are spaced by distance on the screen, so they are worked out for the
     zoom the map is at and again when it changes. A run shorter than one
     spacing still gets one, in its middle, if it is long enough to hold it.
     With `nos`, the editor line numbers of each run's points, every arrow also
     carries the two lines its stretch runs between, so a selection can colour
     exactly the arrows that sit on it. */
  window.arrowMarks = function (map, runs, nos) {
    var SPACING = 90, SHORTEST = 18, MOST = 240;
    var zoom = map.getZoom(), paths = [], total = 0;
    runs.forEach(function (r, ri) {
      if (r.length < 2) return;
      var step = Math.max(1, Math.ceil(r.length / 6000)), pts = [], at = [];
      for (var i = 0; i < r.length; i += step) { pts.push(map.project(r[i], zoom)); at.push(i); }
      if ((r.length - 1) % step) { pts.push(map.project(r[r.length - 1], zoom)); at.push(r.length - 1); }
      var length = 0;
      for (var k = 1; k < pts.length; k++) length += pts[k].distanceTo(pts[k - 1]);
      paths.push({ pts: pts, at: at, nos: nos ? nos[ri] : null, length: length });
      total += length;
    });
    var spacing = Math.max(SPACING, total / MOST), marks = [];
    paths.forEach(function (path) {
      if (path.length < SHORTEST) return;
      var next = path.length < spacing ? path.length / 2 : spacing / 2, gone = 0;
      for (var k = 1; k < path.pts.length; k++) {
        var a = path.pts[k - 1], b = path.pts[k], d = b.distanceTo(a);
        while (d > 0 && gone + d >= next) {
          var f = (next - gone) / d;
          marks.push({ at: map.unproject(L.point(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f), zoom),
                       turn: Math.atan2(b.x - a.x, a.y - b.y) * 180 / Math.PI,
                       lines: path.nos ? [path.nos[path.at[k - 1]], path.nos[path.at[k]]] : null });
          next += spacing;
        }
        gone += d;
      }
    });
    return marks;
  };

  /* The arrowheads themselves, each in the colour `colourOf` gives it. */
  window.drawArrows = function (map, marks, colourOf, pane) {
    if (!marks.length) return null;
    return L.layerGroup(marks.map(function (m) {
      return L.marker(m.at, {
        interactive: false, keyboard: false, pane: pane || "markerPane",
        icon: L.divIcon({
          className: "track-arrow", iconSize: [14, 14], iconAnchor: [7, 7],
          html: '<svg width="14" height="14" viewBox="0 0 14 14" style="transform:rotate(' + m.turn.toFixed(1) + 'deg)">' +
            '<path d="M7 1 L12.5 12.5 L7 9.5 L1.5 12.5 Z" fill="' + colourOf(m) + '" stroke="#10212b" stroke-width="1.2" stroke-linejoin="round"/></svg>'
        })
      });
    })).addTo(map);
  };

  /* The editor lines a selection touches, first and last (1-based), or null for
     a bare caret. A selection that ends at the very start of a line does not
     take that line. */
  window.selectedLines = function (text, start, end) {
    if (end <= start) return null;
    function lineAt(pos) {
      var n = 1, at = -1;
      while ((at = text.indexOf("\n", at + 1)) !== -1 && at < pos) n++;
      return n;
    }
    return [lineAt(start), lineAt(end - 1)];
  };

  /* The pieces of the line that fall on lines first..last: one array of
     [lat, lon] for each run that has points there. A run is one unbroken
     stretch, so nothing is joined across a gap. */
  window.pointsOnLines = function (parsed, first, last) {
    var out = [];
    parsed.runs.forEach(function (r, i) {
      var nos = parsed.runLines[i], piece = [];
      for (var k = 0; k < r.length; k++) if (nos[k] >= first && nos[k] <= last) piece.push(r[k]);
      if (piece.length) out.push(piece);
    });
    return out;
  };

  /* The points whose whole row (trimmed) is not among the saved text's rows. */
  window.unsavedPoints = function (parsed, text, saved) {
    var had = Object.create(null), rows = text.split(/\r?\n/), out = [];
    saved.split(/\r?\n/).forEach(function (l) { had[l.trim()] = 1; });
    parsed.runs.forEach(function (r, i) {
      var nos = parsed.runLines[i];
      for (var k = 0; k < r.length; k++) if (!(rows[nos[k] - 1].trim() in had)) out.push(r[k]);
    });
    return out;
  };

  /* No more than `cap` of the items, spread evenly, first and last kept. */
  window.thin = function (items, cap) {
    if (items.length <= cap) return items;
    var step = (items.length - 1) / (cap - 1), out = [];
    for (var i = 0; i < cap; i++) out.push(items[Math.round(i * step)]);
    return out;
  };
})();

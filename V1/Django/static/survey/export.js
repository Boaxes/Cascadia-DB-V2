/*
 * The Export page. The page is an ordinary form: every choice is a real field,
 * so Download works without this file. This adds what a form cannot do: the
 * live preview of each ticked sheet, the counts beside Choose Columns, and the
 * notes that follow the chosen format.
 */
(function () {
  var form = document.getElementById("export-form");
  if (!form) return;

  var tabs = document.getElementById("tabs");
  var preview = document.getElementById("preview");
  var note = document.getElementById("pv-note");
  var tab = tabs.dataset.first || "";
  var request = 0;

  function params() { return new URLSearchParams(new FormData(form)); }
  function ticked() {
    return Array.prototype.map.call(form.querySelectorAll('input[name="sheet"]:checked'), function (box) {
      return { key: box.value, title: box.dataset.title };
    });
  }
  /* The notes and the sheets a format holds are written on its option by the page. */
  function chosenFormat() { return form.elements.format.selectedOptions[0]; }
  function holds(key) {
    return chosenFormat().dataset.holds.split(",").indexOf(key) >= 0;
  }
  function number(n) { return Number(n).toLocaleString("en-US"); }

  function drawTabs() {
    var shown = ticked();
    if (!shown.some(function (s) { return s.key === tab; })) tab = shown.length ? shown[0].key : "";
    tabs.innerHTML = "";
    shown.forEach(function (s) {
      var b = document.createElement("button");
      b.type = "button"; b.dataset.tab = s.key; b.textContent = s.title;
      if (s.key === tab) b.className = "active";
      tabs.appendChild(b);
    });
  }

  function message(text) {
    preview.innerHTML = "";
    var body = preview.createTBody();
    var cell = body.insertRow().insertCell();
    cell.className = "empty"; cell.textContent = text;
    note.textContent = "";
  }

  function drawPreview() {
    drawTabs();
    if (!tab) { message("Tick a sheet to preview it."); return; }
    var mine = ++request;
    var query = params();
    query.set("preview", tab);
    fetch(form.dataset.preview + "?" + query.toString(), { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        if (mine !== request) return;
        preview.innerHTML = "";
        var head = preview.createTHead().insertRow();
        data.columns.forEach(function (c) {
          var th = document.createElement("th");
          th.textContent = c.label;
          if (c.appended) th.className = "appended";
          head.appendChild(th);
        });
        var body = preview.createTBody();
        if (!data.rows.length) {
          var cell = body.insertRow().insertCell();
          cell.colSpan = data.columns.length; cell.className = "empty";
          cell.textContent = "No rows. Add a query that gives " + data.title + ".";
        }
        data.rows.forEach(function (row) {
          var tr = body.insertRow();
          row.forEach(function (value, i) {
            var td = tr.insertCell();
            if (data.columns[i].appended) td.className = "appended";
            if (value === "") {
              var dash = document.createElement("span");
              dash.className = "none"; dash.textContent = "-";
              td.appendChild(dash);
            } else {
              td.textContent = value;
            }
          });
        });
        note.textContent = "First " + data.rows.length + " of " + number(data.total) +
          " rows. Shaded columns are appended from a related table.";
      })
      .catch(function () { if (mine === request) message("The preview could not be loaded."); });
  }

  function summary() {
    var names = ticked().filter(function (s) { return holds(s.key); });
    var skipped = ticked().length - names.length;
    var text = names.length + (names.length === 1 ? " sheet" : " sheets") +
      (names.length ? ": " + names.map(function (s) { return s.title; }).join(", ") : "");
    if (skipped) text += ". " + skipped + (skipped === 1 ? " ticked sheet has" : " ticked sheets have") + " no place in this format.";
    document.getElementById("summary").textContent = text;
    var button = document.getElementById("dl");
    if (!button.dataset.locked) button.disabled = !names.length;
  }

  function counts() {
    form.querySelectorAll("[data-chosen]").forEach(function (el) {
      var key = el.dataset.chosen;
      var boxes = form.querySelectorAll('input[name="col_' + key + '"]');
      var n = 0;
      boxes.forEach(function (b) { if (b.checked || b.disabled) n++; });
      el.textContent = n;
    });
  }

  /* A format that is not a zip becomes one when the raw files come with it. */
  function zipNote() {
    document.getElementById("raw-zip").hidden = !form.elements.raw.checked || !!chosenFormat().dataset.zipped;
  }

  function format() {
    var f = form.elements.format.value;
    document.getElementById("fmt-note").textContent = chosenFormat().dataset.note;
    form.elements.tz.disabled = f === "gpx";
    form.elements.df.disabled = f === "gpx" || f === "gpkg";
    zipNote();
    summary();
  }

  /* Nothing can be downloaded with no query, or with one that cannot be read. */
  var download = document.getElementById("dl");
  if (download.disabled) download.dataset.locked = "1";

  form.addEventListener("click", function (e) {
    var b = e.target.closest("[data-cols]");
    if (b) {
      var row = form.querySelector('[data-cols-row="' + b.dataset.cols + '"]');
      row.hidden = !row.hidden;
      b.textContent = row.hidden ? "Choose Columns" : "Done";
      return;
    }
    b = e.target.closest("[data-tab]");
    if (b) { tab = b.dataset.tab; drawPreview(); }
  });
  form.addEventListener("change", function (e) {
    var t = e.target;
    if (t.name === "sheet") { summary(); drawPreview(); }
    else if (t.name && t.name.indexOf("col_") === 0) { counts(); drawPreview(); }
    else if (t.name === "format") { format(); drawPreview(); }
    else if (t.name === "tz" || t.name === "df") { drawPreview(); }
    else if (t.name === "raw") { zipNote(); }
    else if (t.dataset.related) { relate(t); }
  });

  /* A query's related records change its counts and every sheet, so the page
     reloads with the other choices kept, as removing a query does. */
  function relate(box) {
    var post = document.getElementById("related-form");
    post.elements.next.value = location.pathname + "?" + params().toString();
    post.elements.index.value = box.dataset.related;
    post.elements.related.value = box.checked ? "1" : "0";
    post.submit();
  }

  /* Removing a query reloads the page, so the choices go with it. */
  document.querySelectorAll('button[form="remove-form"]').forEach(function (b) {
    b.addEventListener("click", function () {
      document.getElementById("remove-form").elements.next.value = location.pathname + "?" + params().toString();
    });
  });

  format();
  counts();
  drawPreview();
})();

/*
 * Tag picker: a <select multiple data-tagpicker> shown as tags plus a
 * drop-down of checkboxes you can type to narrow. The select stays in the
 * form, hidden, and holds the real value, so submitting and the URL work
 * exactly as before.
 *
 * Species arrive in <optgroup>s. Each becomes a folded group with an arrow to
 * open it and a box that ticks the whole group; a fully ticked group shows as
 * one "All Dolphins" tag. Colours come from the server, the same ones the map
 * uses.
 */
(function () {
  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function dot(colour) {
    return colour ? '<i class="tp-dot" style="background:' + colour + '"></i>' : "";
  }

  function build(select) {
    var opts = Array.prototype.slice.call(select.options);
    var optgroups = Array.prototype.slice.call(select.querySelectorAll("optgroup"));
    var groups = optgroups.length ? optgroups : [select];

    var menu = groups.map(function (g, gi) {
      var items = Array.prototype.map.call(g.children, function (o) {
        o.dataset.g = gi;
        return '<label class="tp-opt">' + '<input type="checkbox" data-i="' + opts.indexOf(o) + '">' +
          dot(o.dataset.colour) + "<span>" + esc(o.text) + "</span><small>" +
          Number(o.dataset.count || 0).toLocaleString() + "</small></label>";
      }).join("");
      if (!g.label) return '<div class="tp-group open">' + items + "</div>";
      var total = Array.prototype.reduce.call(g.children, function (n, o) {
        return n + Number(o.dataset.count || 0);
      }, 0);
      return '<div class="tp-group" data-g="' + gi + '"><div class="tp-head">' +
        '<button type="button" class="tp-arrow" aria-label="Show ' + esc(g.label) + '"></button>' +
        '<input type="checkbox" class="tp-all" data-g="' + gi + '" aria-label="All ' + esc(g.label) + '">' +
        dot(g.dataset.colour) + "<span>" + esc(g.label) + "</span><small>" +
        total.toLocaleString() + "</small></div>" +
        '<div class="tp-items">' + items + "</div></div>";
    }).join("");

    var root = document.createElement("div");
    root.className = "tp";
    root.innerHTML = '<div class="tp-field"><span class="tp-tags"></span>' +
      '<input class="tp-search" type="text" autocomplete="off" aria-label="Search">' +
      '</div><div class="tp-menu" hidden>' + menu + "</div>";
    select.hidden = true;
    select.after(root);

    var tags = root.querySelector(".tp-tags");
    var search = root.querySelector(".tp-search");
    var list = root.querySelector(".tp-menu");
    var boxes = list.querySelectorAll("input[data-i]");

    function members(gi) { return opts.filter(function (o) { return o.dataset.g == gi; }); }

    /* Told to the page as a change on the select, so other controls (the
       All Research Groups box) can follow a pick. */
    function set(list_, on) {
      list_.forEach(function (o) { o.selected = on; });
      render();
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function render() {
      boxes.forEach(function (b) { b.checked = opts[b.dataset.i].selected; });
      var html = "";
      groups.forEach(function (g, gi) {
        var all = members(gi), on = all.filter(function (o) { return o.selected; });
        var head = list.querySelector('.tp-all[data-g="' + gi + '"]');
        if (head) {
          head.checked = on.length === all.length;
          head.indeterminate = on.length > 0 && on.length < all.length;
        }
        var whole = g.label && all.length > 1 && on.length === all.length;
        (whole ? [null] : on).forEach(function (o) {
          var colour = o ? o.dataset.colour : g.dataset.colour;
          html += '<span class="tp-tag"' + (colour ? ' style="--c:' + colour + '"' : "") + ">" +
            esc(o ? o.text : "All " + g.label) + '<button type="button" ' +
            (o ? 'data-i="' + opts.indexOf(o) + '"' : 'data-g="' + gi + '"') +
            ' aria-label="Remove">&times;</button></span>';
        });
      });
      tags.innerHTML = html;
      search.placeholder = select.selectedOptions.length ? "" : select.dataset.tagpicker;
    }

    function filter() {
      var q = search.value.trim().toLowerCase();
      root.classList.toggle("searching", !!q);
      list.querySelectorAll(".tp-group").forEach(function (g) {
        var head = g.querySelector(".tp-head");
        var groupHit = !!q && !!head && head.textContent.toLowerCase().indexOf(q) !== -1;
        var any = !q || groupHit;
        g.querySelectorAll(".tp-items .tp-opt, .tp-group.open > .tp-opt").forEach(function (l) {
          var hit = !q || groupHit || l.textContent.toLowerCase().indexOf(q) !== -1;
          l.hidden = !hit;
          any = any || hit;
        });
        g.hidden = !any;
      });
    }

    function open(on) {
      list.hidden = !on;
      root.classList.toggle("open", on);
      if (!on) { search.value = ""; filter(); }
    }

    /* The heading opens its group; only its box ticks the whole group. */
    list.addEventListener("click", function (e) {
      var head = e.target.closest(".tp-head");
      if (head && e.target.tagName !== "INPUT") head.parentNode.classList.toggle("open");
    });
    list.addEventListener("change", function (e) {
      var t = e.target;
      if (t.dataset.i) set([opts[t.dataset.i]], t.checked);
      else set(members(t.dataset.g), t.checked);
      search.focus();   // so typing after a click narrows the list again
    });
    root.querySelector(".tp-field").addEventListener("click", function (e) {
      var d = e.target.dataset;
      if (d.i) set([opts[d.i]], false);
      if (d.g) set(members(d.g), false);
      search.focus();
      open(true);
    });
    search.addEventListener("input", function () { open(true); filter(); });
    search.addEventListener("keydown", function (e) {
      if (e.key === "Escape") open(false);
      if (e.key === "Backspace" && !search.value && select.selectedOptions.length) {
        set([select.selectedOptions[select.selectedOptions.length - 1]], false);
      }
      if (e.key === "Enter" && search.value) {   // pick the first match, not submit
        e.preventDefault();
        var first = list.querySelector(".tp-group:not([hidden]) .tp-opt:not([hidden]) input[data-i]");
        if (first) set([opts[first.dataset.i]], !first.checked);
      }
    });
    /* Redrawn on request after the page changes the select itself. */
    select.addEventListener("tagpicker:refresh", render);
    document.addEventListener("mousedown", function (e) { if (!root.contains(e.target)) open(false); });
    document.addEventListener("focusin", function (e) { if (!root.contains(e.target)) open(false); });

    render();
  }

  document.querySelectorAll("select[data-tagpicker]").forEach(build);
})();

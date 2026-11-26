/*
 * What the Explore, Effort and Sighting maps share beyond the basemap: the
 * popup a GPS track opens when clicked, and the control that saves a picture
 * of the map.
 *
 * Loaded in the page head, so it is already here when a record opens in the
 * pop-over and its map script runs. Some pages load Leaflet after it, so
 * nothing here touches L until it is called.
 */
(function () {
  function esc(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function orDash(value) {
    return value === null || value === undefined || value === ""
      ? '<span class="none">-</span>' : esc(value);
  }

  /* ---------------------------------------------------------- track popup */

  /* The popup for one track, from the fields /api/tracks/ sends (the Effort
     page writes the same fields into the page). `options.effortLink` adds
     Open Effort; `options.managerUrl` is the Track File Manager's address,
     given only to people who may open it. */
  function trackPopup(p, options) {
    options = options || {};
    var file = p.object_key ? String(p.object_key).split("/").pop() : null;
    var length = p.length_nm === null || p.length_nm === undefined ? null
      : p.length_nm.toLocaleString() + " nm";
    var rows = [
      ["Effort Date", orDash(p.date)],
      ["Vessel", orDash(p.vessel)],
      ["Research Group", orDash(p.group)],
      ["File", orDash(file)],
      ["Points", orDash(p.points === null || p.points === undefined ? null : p.points.toLocaleString())],
      ["Length", orDash(length) + (p.suspect
        ? ' <span class="pill pill-red" title="The track\'s own times make this length impossible">Suspect</span>' : "")]
    ];
    var links = [];
    if (options.effortLink && p.effort) {
      links.push('<a href="/efforts/' + p.effort + '/" data-modal-url="/efforts/' +
                 p.effort + '/">Open Effort</a>');
    }
    if (options.managerUrl && p.track) {
      links.push('<a href="' + options.managerUrl + "?open=" + encodeURIComponent(p.track) +
                 '">Open In Track File Manager</a>');
    }
    return '<div class="track-popup"><strong>Track ' + orDash(p.track) + "</strong>" +
      "<dl>" + rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("") +
      "</dl>" + (links.length ? '<div class="track-popup-links">' + links.join("") + "</div>" : "") +
      "</div>";
  }

  /* Clicking a track opens its popup and draws it thicker, on top of the
     other tracks, until the popup closes. `layer` is one track, however many
     lines it is drawn as; `style` is how it looks when not selected. */
  window.clickableTrack = function (layer, style, properties, options) {
    layer.bindPopup(function () { return trackPopup(properties, options); },
                    { maxWidth: 300 });
    layer.on("popupopen", function () {
      if (layer.closeTooltip) layer.closeTooltip();
      layer.setStyle({ weight: style.weight + 3, opacity: 1 });
      layer.bringToFront();
    });
    layer.on("popupclose", function () {
      layer.setStyle(style);
      layer.bringToBack();
    });
    return layer;
  };

  /* ------------------------------------------------------------ screenshot */

  /* Loaded the first time somebody saves a picture, not with every map. */
  var LIBRARY = {
    src: "https://cdn.jsdelivr.net/npm/html-to-image@1.11.13/dist/html-to-image.js",
    integrity: "sha384-Tha/42qsYmpYmQ07pX+nJzkKumO0BzKJxK/uzVc7xyBQxVCUgQBhQIG8L7vXK+9C"
  };
  var loading = null;

  function library() {
    if (window.htmlToImage) return Promise.resolve(window.htmlToImage);
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = LIBRARY.src;
        script.integrity = LIBRARY.integrity;
        script.crossOrigin = "anonymous";
        script.onload = function () { resolve(window.htmlToImage); };
        script.onerror = function () { loading = null; reject(new Error("library")); };
        document.head.appendChild(script);
      });
    }
    return loading;
  }

  var CAMERA = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/>' +
    '<circle cx="12" cy="13.5" r="3.5"/></svg>';

  /* A short message over the map, gone after a while or when clicked. */
  function notice(map, text, keep) {
    var box = map.getContainer().querySelector(".map-notice");
    if (!box) {
      box = L.DomUtil.create("div", "map-notice", map.getContainer());
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.on(box, "click", function () { box.remove(); });
    }
    box.textContent = text;
    clearTimeout(box.timer);
    if (!keep) box.timer = setTimeout(function () { box.remove(); }, 9000);
    return box;
  }

  function canRead(url) {
    return fetch(url, { mode: "cors", credentials: "omit" })
      .then(function (r) { return r.ok; }, function () { return false; });
  }

  function tileLayers(map) {
    var layers = [];
    map.eachLayer(function (l) { if (l instanceof L.TileLayer) layers.push(l); });
    return layers;
  }

  /* A basemap whose server does not allow its tiles to be read back gives
     a blank picture, so each layer on the map is checked first with one of
     its own tiles. Resolves to a message for the reader, or null. */
  function checkLayers(map) {
    var showing = tileLayers(map);
    return Promise.all(showing.map(function (layer) {
      var tile = layer.getContainer() &&
        layer.getContainer().querySelector("img.leaflet-tile-loaded");
      return tile ? canRead(tile.src) : true;
    })).then(function (ok) {
      var blocked = showing.filter(function (layer, i) { return !ok[i]; });
      if (!blocked.length) return null;

      var bases = map.baseLayers || {};
      var base = blocked.filter(function (l) {
        return Object.keys(bases).some(function (k) { return bases[k] === l; });
      })[0];
      if (!base) {
        return "The " + (blocked[0].menuName || "map overlay") + " layer cannot be " +
          "saved in a picture. Turn it off in the layers menu (top right of the " +
          "map), then try again.";
      }
      /* Which basemap to suggest: one whose tiles can be read. */
      var others = Object.keys(bases).map(function (k) { return bases[k]; })
        .filter(function (l) { return l !== base; });
      return Promise.all(others.map(function (l) {
        return canRead(L.Util.template(l._url, { s: "a", r: "", x: 0, y: 0, z: 0 }));
      })).then(function (usable) {
        var names = others.filter(function (l, i) { return usable[i]; })
          .map(function (l) { return l.menuName; });
        return "The " + (base.menuName || "current") + " basemap cannot be saved in a " +
          "picture. " + (names.length
            ? "Switch to " + names.join(" or ") + " in the layers menu (top right of " +
              "the map), then try again."
            : "None of the basemaps can be saved at the moment.");
      });
    });
  }

  /* The picture of the map with a strip of text under it. */
  function addCaption(picture, lines, ratio) {
    var pad = 12 * ratio, size = 13 * ratio, lineHeight = 18 * ratio;
    var family = getComputedStyle(document.body).fontFamily || "sans-serif";
    var out = document.createElement("canvas");
    var ctx = out.getContext("2d");
    var width = picture.width - 2 * pad;

    /* Each line wrapped to the picture's width. */
    var rows = [];
    lines.forEach(function (line) {
      ctx.font = (line.bold ? "600 " : "") + size + "px " + family;
      var words = line.text.split(" "), current = "";
      words.forEach(function (word) {
        var next = current ? current + " " + word : word;
        if (current && ctx.measureText(next).width > width) {
          rows.push({ text: current, line: line });
          current = word;
        } else {
          current = next;
        }
      });
      rows.push({ text: current, line: line });
    });

    out.width = picture.width;
    out.height = picture.height + rows.length * lineHeight + 2 * pad;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(picture, 0, 0);
    ctx.fillStyle = mapColour("border") || "#d5dfe5";
    ctx.fillRect(0, picture.height, out.width, Math.max(1, ratio));
    ctx.textBaseline = "top";
    rows.forEach(function (row, i) {
      ctx.font = (row.line.bold ? "600 " : "") + size + "px " + family;
      ctx.fillStyle = row.line.muted ? (mapColour("muted") || "#56697a") : (mapColour("text") || "#1a2a33");
      ctx.fillText(row.text, pad, picture.height + pad + i * lineHeight + 2 * ratio);
    });
    return out;
  }

  function today() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
  }

  function download(canvas, name) {
    canvas.toBlob(function (blob) {
      var url = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
    }, "image/png");
  }

  /* A camera button that saves the map as a PNG: what is on screen, with the
     legend, scale bar and attribution, and a caption saying what it shows.
     Options:
       node      the element to picture, if more than the map (Explore's
                 legend sits beside the map, not in it)
       skip      a selector for anything in it to leave out
       title     the caption's first line
       caption   a function returning the caption's second line
       filename  the file's name, without ".png" */
  window.screenshotControl = function (map, options) {
    var busy = false;

    function save(link) {
      if (busy) return;
      busy = true;
      link.classList.add("busy");
      notice(map, "Saving the map as an image…", true);

      function finish(message) {
        busy = false;
        link.classList.remove("busy");
        if (message) notice(map, message);
        else {
          var box = map.getContainer().querySelector(".map-notice");
          if (box) box.remove();
        }
      }

      var node = options.node || map.getContainer();
      var ratio = Math.min(window.devicePixelRatio || 1, 2);
      var skip = ".leaflet-top, .map-notice" + (options.skip ? ", " + options.skip : "");

      checkLayers(map).then(function (problem) {
        if (problem) { finish(problem); return; }
        /* The picture copies attributes, not the live state of a checkbox. */
        node.querySelectorAll("input[type=checkbox]").forEach(function (box) {
          box.toggleAttribute("checked", box.checked);
        });
        return library().then(function (h2i) {
          return h2i.toCanvas(node, {
            pixelRatio: ratio,
            backgroundColor: "#ffffff",
            skipFonts: true,
            filter: function (el) { return !(el.matches && el.matches(skip)); }
          });
        }).then(function (picture) {
          var lines = [{ text: options.title, bold: true }];
          var detail = options.caption && options.caption();
          if (detail) lines.push({ text: detail });
          lines.push({ text: "Saved " + today() + " from the Sightings and Effort Explorer", muted: true });
          download(addCaption(picture, lines, ratio), options.filename + ".png");
          finish(null);
        });
      }).catch(function () {
        finish("The map could not be saved as an image. Try again, or switch basemap.");
      });
    }

    var Control = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var bar = L.DomUtil.create("div", "leaflet-bar leaflet-control leaflet-control-screenshot");
        var link = L.DomUtil.create("a", "", bar);
        link.href = "#";
        link.title = "Save Map As Image";
        link.setAttribute("role", "button");
        link.setAttribute("aria-label", link.title);
        link.innerHTML = CAMERA;
        L.DomEvent.disableClickPropagation(bar);
        L.DomEvent.on(link, "click", function (e) {
          L.DomEvent.preventDefault(e);
          save(link);
        });
        return bar;
      }
    });
    return new Control().addTo(map);
  };
})();

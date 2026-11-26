/*
 * Records open in a pop-over, without losing the URL.
 *
 * Opening a sighting or an effort fetches its ordinary page, lifts #detail out
 * of it, and shows that over whatever you were looking at. The record's real
 * URL goes in the address bar, so it can be copied or opened in a new tab, and
 * a shared link still opens as a full page. The server knows nothing about any
 * of this and renders one page.
 *
 * Inside the pop-over everything stays inside it: a record opened from another
 * record can be backed out of, and editing or deleting (a form, then a review
 * step) is submitted from here rather than leaving for a page of its own.
 */
(function () {
  var modal = document.getElementById("modal");
  if (!modal) return;

  var content = document.getElementById("modal-content");
  var back = modal.querySelector(".modal-back");
  var title = modal.querySelector(".modal-title");
  var underneath = window.location.href;   // the page the pop-over sits over
  var stack = [];                          // records opened, oldest first

  /* A record, its edit or delete step, or a change in the Audit Log. */
  var RECORD = /^\/((sightings|efforts)\/\d+\/(edit\/|delete\/)?|cascadia-admin\/audit\/\d+\/)$/;
  var changed = false;   /* something was saved: the page underneath is stale */

  function render(html, url) {
    var page = new DOMParser().parseFromString(html, "text/html");
    var detail = page.getElementById("detail");
    if (!detail) return false;

    content.innerHTML = detail.innerHTML;
    /* A short page (one change, one file) sizes the panel to itself rather
       than filling the window with empty space. */
    modal.classList.toggle("modal-fit", detail.hasAttribute("data-fit"));
    /* The title and tools go up into the pop-over's own bar. */
    var head = content.querySelector(".detail-head");
    title.innerHTML = "";
    if (head) title.appendChild(head);
    /* "2 fields changed" after a save sits outside #detail; bring it along. */
    var messages = page.querySelector(".messages");
    if (messages && !detail.contains(messages)) content.prepend(messages);
    /* innerHTML does not execute scripts, and a record draws a map. */
    content.querySelectorAll("script").forEach(function (old) {
      var fresh = document.createElement("script");
      if (old.src) fresh.src = old.src; else fresh.textContent = old.textContent;
      old.parentNode.replaceChild(fresh, old);
    });

    back.hidden = stack.length < 2;
    content.scrollTop = 0;
    if (!modal.classList.contains("open")) {
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      underneath = window.location.href;
      history.pushState({ modal: true }, "", url);
    } else {
      history.replaceState({ modal: true }, "", url);
    }
    return true;
  }

  function fetchPage(url, options) {
    return fetch(url, Object.assign({ credentials: "same-origin" }, options))
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text().then(function (html) {
          return { html: html, path: new URL(r.url).pathname, url: r.url };
        });
      });
  }

  /* Show a record, adding it to the stack so Back returns from it. */
  function open(url) {
    fetchPage(url)
      .then(function (page) {
        stack.push(page.path);
        if (!render(page.html, page.path)) window.location.href = url;
      })
      .catch(function () { window.location.href = url; });
  }

  function goBack() {
    stack.pop();
    var previous = stack[stack.length - 1];
    fetchPage(previous).then(function (page) { render(page.html, previous); });
  }

  function hide() {
    if (changed) { window.location.reload(); return; }
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    content.innerHTML = "";
    title.innerHTML = "";
    stack = [];
  }

  /* What a click should open: an element marked data-modal-url, or, inside
     the pop-over, any plain link to a record (Cancel, the effort link...).
     Modifier and middle clicks are left alone so "open in new tab" works. */
  document.addEventListener("click", function (e) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    var link = e.target.closest("a[href]");
    var url = null;
    if (link && link.hasAttribute("data-modal-url")) {
      url = link.dataset.modalUrl;
    } else if (link) {
      var path = new URL(link.href).pathname;
      if (new URL(link.href).origin === location.origin && RECORD.test(path) &&
          (content.contains(link) || link.closest("[data-modal-url]"))) url = path;
      else return;   /* an ordinary link: let it navigate */
    } else {
      var trigger = e.target.closest("[data-modal-url]");
      if (trigger) url = trigger.dataset.modalUrl;
    }
    if (!url) return;
    e.preventDefault();

    /* Cancel on an edit form points at the record it came from. */
    if (stack.length > 1 && url === stack[stack.length - 2]) { goBack(); return; }
    open(url);
  });

  /* Edit and delete submit here. The review step comes back to the same
     address; a save lands on the record; a delete lands on a list, because
     the record is gone, so the page underneath is reloaded. */
  content.addEventListener("submit", function (e) {
    var form = e.target;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
    e.preventDefault();
    changed = true;
    var current = stack[stack.length - 1];
    fetchPage(form.getAttribute("action") || current,
              { method: "POST", body: new FormData(form, e.submitter) })
      .then(function (page) {
        /* Saved from a record's own page: show that page, now changed. */
        if (page.path !== current && page.path === new URL(underneath).pathname) {
          window.location.href = underneath;
          return;
        }
        if (page.path !== current) {
          var at = stack.lastIndexOf(page.path);
          if (at >= 0) stack.length = at + 1; else stack[stack.length - 1] = page.path;
        }
        if (!render(page.html, page.path)) {
          var deletedHere = new URL(underneath).pathname === current.replace(/delete\/$/, "");
          window.location.href = deletedHere ? page.url : underneath;
        }
      })
      .catch(function () { form.submit(); });
  });

  back.addEventListener("click", goBack);
  modal.querySelector(".modal-close").addEventListener("click", function () {
    history.back();
  });
  modal.addEventListener("click", function (e) {
    if (e.target === modal) history.back();
  });
  document.addEventListener("keydown", function (e) {
    /* Escape closes the history window first, the record only after it. */
    if (document.querySelector("dialog[open]")) return;
    if (e.key === "Escape" && modal.classList.contains("open")) history.back();
  });
  window.addEventListener("popstate", function () {
    if (modal.classList.contains("open")) hide();
  });

  /* The History tool opens the record's history in a window of its own. */
  document.addEventListener("click", function (e) {
    var button = e.target.closest("[data-history-toggle]");
    if (!button) return;
    var root = button.closest("#modal") ? content : document.getElementById("detail");
    var win = root && root.querySelector("dialog.history");
    if (win) win.showModal();
  });
})();

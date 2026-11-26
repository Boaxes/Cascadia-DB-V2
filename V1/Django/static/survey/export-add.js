/*
 * Add To Export. The button is a form that posts to the export's stack; this
 * sends it without leaving the page, then moves the count on the Export link
 * and says what happened on the button itself.
 *
 * Delegated from the document, because a record opened in the pop-over is
 * built after this runs. In the capture phase, so the pop-over's own handler
 * for posted forms does not take the form first.
 */
(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target.closest && event.target.closest("form[data-add-export]");
    if (!form) return;
    event.preventDefault();
    event.stopPropagation();

    var button = form.querySelector("button");
    var note = form.querySelector(".add-export-note");
    if (note) note.remove();
    button.disabled = true;

    fetch(form.action, {
      method: "POST", body: new FormData(form), credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" }
    })
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) {
          button.disabled = false;
          note = document.createElement("span");
          note.className = "add-export-note";
          note.textContent = result.data.error || "That could not be added.";
          form.appendChild(note);
          return;
        }
        var link = document.getElementById("nav-export");
        if (link) link.textContent = "Export (" + result.data.count + ")";
        button.textContent = result.data.added ? "Added To Export" : "Already In Export";
      })
      /* Without a working script path, post the form the ordinary way. */
      .catch(function () { form.submit(); });
  }, true);
})();

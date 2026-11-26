// Cards fold away by clicking their heading.
//
// Delegated from the document so it also covers a detail page lifted into
// the modal, which is built after this runs. Nothing is remembered between
// pages: a card folded to get it out of the way should be open again the
// next time you arrive at that page.
(function () {
  document.addEventListener("click", function (event) {
    if (event.target.closest(".tip")) return;
    var heading = event.target.closest(".card > h2");
    if (heading) heading.parentElement.classList.toggle("collapsed");
  });

  /* The profile menu closes on a click anywhere else, or on Escape. */
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.profile[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.profile[open]").forEach(function (menu) { menu.open = false; });
  });

  /* A form marked data-needs-change keeps its submit button off until some
     field differs from what the page loaded with, so reviewing an edit that
     changes nothing is not possible. Delegated, because the edit form is
     built inside the pop-over after this runs. */
  function differs(el) {
    if (el.type === "checkbox" || el.type === "radio") return el.checked !== el.defaultChecked;
    if (el.tagName === "SELECT") {
      return Array.prototype.some.call(el.options, function (o) { return o.selected !== o.defaultSelected; });
    }
    return el.type !== "hidden" && "defaultValue" in el && el.value !== el.defaultValue;
  }
  function recheck(event) {
    var form = event.target.form;
    if (!form || !form.hasAttribute("data-needs-change")) return;
    form.querySelector('[type="submit"]').disabled =
      !Array.prototype.some.call(form.elements, differs);
  }
  document.addEventListener("input", recheck);
  document.addEventListener("change", recheck);
})();

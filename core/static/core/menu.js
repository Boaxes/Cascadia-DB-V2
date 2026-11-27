/* Opens and closes the sidebar behind the menu button on narrow screens (NAV-06). */
document.addEventListener("click", (event) => {
  if (event.target.closest("#menu-button")) document.body.classList.toggle("menu-open");
});

(() => {
  "use strict";
  const q = (selector, root = document) => root.querySelector(selector);
  const qa = (selector, root = document) => [...root.querySelectorAll(selector)];

  const menuButton = q(".menu-toggle");
  const nav = q("#nav-links");
  const languageSwitch = q(".language-menu");
  function closeMenu() {
    languageSwitch.open = false;
    nav.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", menuButton.dataset.openLabel);
  }
  menuButton.addEventListener("click", () => {
    const open = !nav.classList.contains("is-open");
    nav.classList.toggle("is-open", open);
    if (!open) languageSwitch.open = false;
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? menuButton.dataset.closeLabel : menuButton.dataset.openLabel);
  });
  qa("a", nav).forEach(link => link.addEventListener("click", closeMenu));
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if (languageSwitch.open) {
      languageSwitch.open = false;
      q("summary", languageSwitch).focus();
      return;
    }
    if (nav.classList.contains("is-open")) {
      closeMenu();
      menuButton.focus();
    }
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".language-menu")) languageSwitch.open = false;
    if (!event.target.closest(".navigation")) closeMenu();
  });
  const compactNavigation = window.matchMedia("(max-width: 800px)");
  compactNavigation.addEventListener("change", closeMenu);

  // Keep the four translated headline lines within the approved left column.
  const heading = q(".hero-timing-heading");
  function fitHeadline() {
    heading.style.removeProperty("--headline-fit");
    const available = heading.clientWidth;
    const widest = Math.max(...qa(".hero-line", heading).map(line => line.scrollWidth));
    if (widest > available && available > 0) {
      const size = parseFloat(getComputedStyle(heading).fontSize);
      heading.style.setProperty("--headline-fit", `${size * available / widest * .98}px`);
    }
  }
  new ResizeObserver(fitHeadline).observe(heading.parentElement);
  document.fonts.ready.then(fitHeadline);

  const imageDialog = q("#image-dialog");
  qa("[data-zoom]").forEach(button => button.addEventListener("click", () => {
    q("#image-dialog-img").src = button.dataset.zoom;
    q("#image-dialog-img").alt = button.dataset.caption;
    q("#image-dialog-caption").textContent = button.dataset.caption;
    imageDialog.showModal();
  }));
  qa("[data-close-dialog]").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  qa("dialog").forEach(dialog => dialog.addEventListener("click", event => {
    if (dialog === imageDialog) {
      dialog.close();
      return;
    }
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }));
})();

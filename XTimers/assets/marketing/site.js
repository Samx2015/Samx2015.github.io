(() => {
  "use strict";
  const q = (selector, root = document) => root.querySelector(selector);
  const qa = (selector, root = document) => [...root.querySelectorAll(selector)];

  // One campaign identifies the website; event properties distinguish its links.
  document.addEventListener("click", event => {
    const link = event.target.closest && event.target.closest("a[href]");
    if (!link || !window.umami) return;
    const href = link.getAttribute("href") || "";
    let eventName = link.dataset.ctaEvent || null;
    if (!eventName && href.includes("apps.apple.com")) eventName = "App Store Click";
    else if (!eventName && (/\.dmg(\?|#|$)/i.test(href) || href.includes("/releases/download/"))) eventName = "Download Click";
    else if (!eventName && href.startsWith("mailto:")) eventName = "Email Click";
    else if (!eventName && /support\.html/i.test(href)) eventName = "Support Click";
    else if (!eventName && /privacy\.html/i.test(href)) eventName = "Privacy Click";
    else if (!eventName && /eula\.html|terms\.html/i.test(href)) eventName = "Terms Click";
    if (eventName) {
      window.umami.track(eventName, {
        href: link.href || href,
        path: window.location.pathname,
        placement: link.dataset.ctaPlacement || (link.closest("header") ? "header" : link.closest("footer") ? "footer" : "content"),
        platform: link.dataset.platform || "unspecified",
        locale: link.dataset.locale || document.documentElement.lang || "en"
      });
    }
  });

  const menuButton = q(".menu-toggle");
  const nav = q("#nav-links");
  const languageSwitch = q(".language-menu");
  function closeMenu() {
    if (languageSwitch) languageSwitch.open = false;
    if (!nav || !menuButton) return;
    nav.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", menuButton.dataset.openLabel);
  }
  if (menuButton && nav) {
    menuButton.addEventListener("click", () => {
      const open = !nav.classList.contains("is-open");
      nav.classList.toggle("is-open", open);
      if (!open && languageSwitch) languageSwitch.open = false;
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.setAttribute("aria-label", open ? menuButton.dataset.closeLabel : menuButton.dataset.openLabel);
    });
    qa("a", nav).forEach(link => link.addEventListener("click", closeMenu));
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") return;
      if (languageSwitch && languageSwitch.open) {
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
      if (languageSwitch && !event.target.closest(".language-menu")) languageSwitch.open = false;
      if (!event.target.closest(".navigation")) closeMenu();
    });
    window.matchMedia("(max-width: 1000px)").addEventListener("change", closeMenu);
  }

  // Keep the four translated headline lines within the approved left column.
  const heading = q(".hero-timing-heading");
  if (heading) {
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
  }

  const imageDialog = q("#image-dialog");
  if (imageDialog) {
    qa("[data-zoom]").forEach(button => button.addEventListener("click", () => {
      q("#image-dialog-img").src = button.dataset.zoom;
      q("#image-dialog-img").alt = button.dataset.caption;
      q("#image-dialog-caption").textContent = button.dataset.caption;
      imageDialog.showModal();
    }));
  }
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

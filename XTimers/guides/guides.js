(() => {
  "use strict";
  const dialog = document.querySelector(".guide-dialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  const image = dialog.querySelector("img");
  const caption = dialog.querySelector("p");
  document.querySelectorAll("a[data-zoom]").forEach(link => {
    link.addEventListener("click", event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      image.src = link.href;
      image.alt = link.querySelector("img").alt;
      caption.textContent = link.dataset.caption;
      dialog.showModal();
    });
  });
  dialog.addEventListener("click", () => dialog.close());
})();

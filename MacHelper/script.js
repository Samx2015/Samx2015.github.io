const modes = {
  mirror: {
    title: "Built-in display darkened",
    detail: "your MacBook screen is duplicating the external display",
  },
  extend: {
    title: "Built-in display stays on",
    detail: "your MacBook screen is part of your extended workspace",
  },
  disabled: {
    title: "Automatic blackout is off",
    detail: "your built-in display remains available until you turn it back on",
  },
};

const buttons = Array.from(document.querySelectorAll("[data-mode]"));
const title = document.querySelector("#status-title");
const detail = document.querySelector("#status-detail");

function setMode(mode) {
  if (!title || !detail) {
    return;
  }

  const copy = modes[mode] || modes.mirror;
  document.body.dataset.demoMode = mode;
  title.textContent = copy.title;
  detail.textContent = copy.detail;

  for (const button of buttons) {
    const isActive = button.dataset.mode === mode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  }
}

for (const button of buttons) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}

if (buttons.length > 0 && title && detail) {
  setMode("mirror");
}

for (const link of document.querySelectorAll('a[href="#release"]')) {
  link.addEventListener("click", (event) => {
    const releaseSection = document.querySelector("#release");
    if (!releaseSection) {
      return;
    }

    event.preventDefault();
    releaseSection.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

const languageMenus = Array.from(document.querySelectorAll(".language-menu"));

document.addEventListener("pointerdown", (event) => {
  for (const menu of languageMenus) {
    if (event.target instanceof Node && menu.contains(event.target)) {
      continue;
    }

    menu.removeAttribute("open");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }

  for (const menu of languageMenus) {
    menu.removeAttribute("open");
  }
});

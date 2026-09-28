(function () {
  "use strict";
  var cards = Array.from(document.querySelectorAll(".option"));
  var ids = cards.map(function (card) { return card.dataset.id; });
  var byId = new Map(cards.map(function (card) { return [card.dataset.id, card]; }));
  var saved = new Set();
  var selected = null;
  var filter = "all";
  var activePreview = null;
  var storageKey = document.body.dataset.designStorage || "tonale-hero-designs-v1";
  var viewer = document.getElementById("context-viewer");
  var status = document.getElementById("choice-status");
  var allButton = document.getElementById("filter-all");
  var savedButton = document.getElementById("filter-saved");

  try {
    var stored = JSON.parse(localStorage.getItem(storageKey) || "{}");
    if (stored && Array.isArray(stored.saved)) {
      stored.saved.forEach(function (id) { if (byId.has(id)) saved.add(id); });
    }
    if (stored && byId.has(stored.selected)) selected = stored.selected;
  } catch (_) { /* The gallery works when storage is unavailable. */ }
  var linkedChoice = location.hash.indexOf("#look-") === 0 ? location.hash.slice(6) : "";
  if (byId.has(linkedChoice)) selected = linkedChoice;

  function persist() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ saved: Array.from(saved), selected: selected }));
    } catch (_) { /* Keep the current selection in memory. */ }
  }

  function render() {
    cards.forEach(function (card) {
      var id = card.dataset.id;
      var isSaved = saved.has(id);
      var isChosen = selected === id;
      card.hidden = filter === "saved" && !isSaved;
      card.classList.toggle("is-chosen", isChosen);
      var saveButton = card.querySelector('[data-action="save"]');
      saveButton.setAttribute("aria-pressed", String(isSaved));
      saveButton.setAttribute("aria-label", (isSaved ? "Remove " : "Add ") + card.dataset.name + (isSaved ? " from shortlist" : " to shortlist"));
      saveButton.title = isSaved ? "Remove from shortlist" : "Add to shortlist";
      var chooseButton = card.querySelector('[data-action="choose"]');
      chooseButton.setAttribute("aria-pressed", String(isChosen));
      chooseButton.textContent = isChosen ? "Chosen " + id + " ✓" : "Choose " + id;
    });
    allButton.setAttribute("aria-pressed", String(filter === "all"));
    savedButton.setAttribute("aria-pressed", String(filter === "saved"));
    savedButton.textContent = "Shortlist (" + saved.size + ")";
    document.getElementById("empty-state").hidden = filter !== "saved" || saved.size > 0;
    if (selected) {
      var label = document.createElement("strong");
      label.textContent = selected + " — " + byId.get(selected).dataset.name;
      status.replaceChildren(label, document.createTextNode(". Tell me “use " + selected + "” to apply it."));
    } else {
      status.textContent = "Choose a design, then tell me its number.";
    }
    if (activePreview) {
      document.getElementById("choose-preview").textContent = selected === activePreview ? "Chosen " + activePreview + " ✓" : "Choose " + activePreview;
    }
  }

  function choose(id) {
    selected = id;
    persist();
    history.replaceState(null, "", "#look-" + id);
    render();
  }

  function preview(id) {
    activePreview = id;
    var card = byId.get(id);
    document.getElementById("context-copy").replaceChildren(card.querySelector(".design").cloneNode(true));
    document.getElementById("context-title").textContent = id + " / " + card.dataset.name;
    document.getElementById("context-count").textContent = String(ids.indexOf(id) + 1).padStart(2, "0") + " / " + ids.length;
    document.getElementById("choose-preview").textContent = selected === id ? "Chosen " + id + " ✓" : "Choose " + id;
    if (!viewer.open) viewer.showModal();
    viewer.scrollTop = 0;
  }

  function step(amount) {
    var next = (ids.indexOf(activePreview) + amount + ids.length) % ids.length;
    preview(ids[next]);
  }

  document.getElementById("gallery").addEventListener("click", function (event) {
    var button = event.target.closest("button[data-action]");
    if (!button) return;
    var id = button.closest(".option").dataset.id;
    if (button.dataset.action === "preview") {
      preview(id);
    } else if (button.dataset.action === "choose") {
      choose(id);
    } else {
      if (saved.has(id)) saved.delete(id); else saved.add(id);
      persist();
      render();
    }
  });
  allButton.addEventListener("click", function () { filter = "all"; render(); });
  savedButton.addEventListener("click", function () { filter = "saved"; render(); });
  document.getElementById("close-preview").addEventListener("click", function () { viewer.close(); });
  document.getElementById("previous-design").addEventListener("click", function () { step(-1); });
  document.getElementById("next-design").addEventListener("click", function () { step(1); });
  document.getElementById("choose-preview").addEventListener("click", function () { choose(activePreview); viewer.close(); });
  viewer.addEventListener("click", function (event) { if (event.target === viewer) viewer.close(); });
  viewer.addEventListener("keydown", function (event) {
    if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
    if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
  });
  render();
})();

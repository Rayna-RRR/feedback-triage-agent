const uploadRow = document.querySelector("#upload-row");
const sourceInputs = document.querySelectorAll('input[name="data_source"]');
const ruleOnly = document.querySelector('input[name="rule_only"]');
const useLlm = document.querySelector('input[name="use_llm"]');
const selectableCards = document.querySelectorAll(".source-card, .check-card");

function syncSelectedCards() {
  selectableCards.forEach((card) => {
    const input = card.querySelector("input");
    card.classList.toggle("is-selected", Boolean(input && input.checked));
  });
}

function updateUploadVisibility() {
  const selected = document.querySelector('input[name="data_source"]:checked');
  if (!uploadRow || !selected) return;
  uploadRow.hidden = selected.value !== "upload";
  syncSelectedCards();
}

sourceInputs.forEach((input) => {
  input.addEventListener("change", updateUploadVisibility);
});

if (ruleOnly && useLlm) {
  ruleOnly.addEventListener("change", () => {
    if (ruleOnly.checked) useLlm.checked = false;
    syncSelectedCards();
  });
  useLlm.addEventListener("change", () => {
    if (useLlm.checked) ruleOnly.checked = false;
    syncSelectedCards();
  });
}

selectableCards.forEach((card) => {
  const input = card.querySelector("input");
  if (!input) return;
  input.addEventListener("change", syncSelectedCards);
});

function updateSidebarActive() {
  const currentPath = window.location.pathname;
  const currentHash = window.location.hash || "";
  const defaultLink = document.querySelector(".sidebar-link[data-default-active]");
  document.querySelectorAll(".sidebar-link").forEach((link) => {
    const url = new URL(link.getAttribute("href"), window.location.href);
    let active = false;
    if (currentHash) {
      active = url.pathname === currentPath && url.hash === currentHash;
    } else if (defaultLink) {
      active = link === defaultLink;
    } else {
      active = url.pathname === currentPath && !url.hash;
    }
    link.classList.toggle("is-active", active);
  });
}

document.querySelectorAll("button, .button, .download-grid a").forEach((control) => {
  control.addEventListener("pointerdown", () => control.classList.add("is-pressed"));
  control.addEventListener("pointerup", () => control.classList.remove("is-pressed"));
  control.addEventListener("pointerleave", () => control.classList.remove("is-pressed"));
});

updateUploadVisibility();
syncSelectedCards();
updateSidebarActive();
window.addEventListener("hashchange", updateSidebarActive);

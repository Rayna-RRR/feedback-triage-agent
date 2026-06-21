const uploadRow = document.querySelector("#upload-row");
const sourceInputs = document.querySelectorAll('input[name="data_source"]');
const ruleOnly = document.querySelector('input[name="rule_only"]');
const useLlm = document.querySelector('input[name="use_llm"]');
const selectableCards = document.querySelectorAll(".source-card, .check-card");
const fileInputs = document.querySelectorAll(".file-input-native");
const startupOverlay = document.querySelector(".startup-overlay");

if (startupOverlay) {
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let overlayHidden = false;
  const removeOverlay = () => {
    if (overlayHidden) return;
    overlayHidden = true;
    startupOverlay.classList.add("is-hidden");
    startupOverlay.setAttribute("aria-hidden", "true");
    window.setTimeout(() => startupOverlay.remove(), prefersReducedMotion ? 20 : 360);
  };

  if (prefersReducedMotion) {
    requestAnimationFrame(removeOverlay);
  } else {
    window.addEventListener("load", () => window.setTimeout(removeOverlay, 960), { once: true });
    window.setTimeout(removeOverlay, 1200);
  }
}

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

function syncFilePicker(input) {
  const picker = input.nextElementSibling;
  const fileName = picker && picker.querySelector(".file-picker-name");
  if (!fileName) return;
  const fallback = fileName.dataset.emptyLabel || "未选择任何文件";
  fileName.textContent = input.files && input.files.length ? input.files[0].name : fallback;
}

fileInputs.forEach((input) => {
  input.addEventListener("change", () => syncFilePicker(input));
  syncFilePicker(input);
});

const sidebarLinks = Array.from(document.querySelectorAll(".sidebar-link"));
const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

function getSidebarLinkUrl(link) {
  return new URL(link.getAttribute("href"), window.location.href);
}

function getCurrentSectionItems() {
  return sidebarLinks
    .map((link) => {
      const url = getSidebarLinkUrl(link);
      const target = url.hash ? document.querySelector(url.hash) : null;
      return { link, target, url };
    })
    .filter((item) => item.url.pathname === window.location.pathname && item.target);
}

function setActiveSidebarLink(activeLink) {
  sidebarLinks.forEach((link) => {
    link.classList.toggle("is-active", link === activeLink);
  });
}

function updateSidebarActiveFromLocation() {
  const currentPath = window.location.pathname;
  const currentHash = window.location.hash || "";
  const defaultLink = document.querySelector(".sidebar-link[data-default-active]");
  const locationMatch = sidebarLinks.find((link) => {
    const url = getSidebarLinkUrl(link);
    return url.pathname === currentPath && url.hash && url.hash === currentHash;
  });
  if (locationMatch) {
    setActiveSidebarLink(locationMatch);
    return;
  }
  if (defaultLink) {
    setActiveSidebarLink(defaultLink);
    return;
  }
  const pathMatch = sidebarLinks.find((link) => {
    const url = getSidebarLinkUrl(link);
    return url.pathname === currentPath && !url.hash;
  });
  if (pathMatch) setActiveSidebarLink(pathMatch);
}

function updateSidebarActiveFromScroll() {
  const sectionItems = getCurrentSectionItems();
  if (!sectionItems.length) {
    updateSidebarActiveFromLocation();
    return;
  }
  const topbarHeight = parseInt(
    getComputedStyle(document.documentElement).getPropertyValue("--topbar-height"),
    10,
  ) || 64;
  const activationLine = topbarHeight + 36;
  let activeItem = sectionItems[0];

  sectionItems.forEach((item) => {
    const rect = item.target.getBoundingClientRect();
    if (rect.top <= activationLine) activeItem = item;
  });

  const pageBottom = window.scrollY + window.innerHeight;
  const documentHeight = document.documentElement.scrollHeight;
  if (pageBottom >= documentHeight - 4) {
    activeItem = sectionItems[sectionItems.length - 1];
  }

  setActiveSidebarLink(activeItem.link);
}

let sidebarScrollFrame = null;
function scheduleSidebarScrollSync() {
  if (sidebarScrollFrame !== null) return;
  sidebarScrollFrame = window.requestAnimationFrame(() => {
    sidebarScrollFrame = null;
    updateSidebarActiveFromScroll();
  });
}

sidebarLinks.forEach((link) => {
  link.addEventListener("click", (event) => {
    const url = getSidebarLinkUrl(link);
    if (url.pathname !== window.location.pathname || !url.hash) return;
    const target = document.querySelector(url.hash);
    if (!target) return;
    event.preventDefault();
    target.scrollIntoView({
      behavior: reduceMotionQuery.matches ? "auto" : "smooth",
      block: "start",
    });
    window.history.pushState(null, "", url.hash);
    setActiveSidebarLink(link);
  });
});

document.querySelectorAll("button, .button, .download-grid a").forEach((control) => {
  control.addEventListener("pointerdown", () => control.classList.add("is-pressed"));
  control.addEventListener("pointerup", () => control.classList.remove("is-pressed"));
  control.addEventListener("pointerleave", () => control.classList.remove("is-pressed"));
});

updateUploadVisibility();
syncSelectedCards();
updateSidebarActiveFromScroll();
window.addEventListener("hashchange", updateSidebarActiveFromLocation);
window.addEventListener("scroll", scheduleSidebarScrollSync, { passive: true });
window.addEventListener("resize", scheduleSidebarScrollSync);

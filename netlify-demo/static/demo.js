(() => {
  "use strict";

  const reviewLink = document.querySelector("[data-demo-review-link]");
  const openReviewPanel = (hash) => {
    const panel = document.getElementById(hash.slice(1));
    if (panel?.matches(".risk-action-panel")) panel.open = true;
  };
  reviewLink.addEventListener("click", () => openReviewPanel(reviewLink.hash));
  window.addEventListener("hashchange", () => openReviewPanel(location.hash));
  openReviewPanel(location.hash);

  const fieldLabels = [
    ["risk_level", "风险等级"],
    ["owner", "负责人"],
    ["work_status", "处理状态"],
    ["next_action", "下一步动作"],
    ["result", "处理结果"],
    ["note", "操作说明"],
  ];
  const reviewStatuses = {
    confirm: "已确认",
    reject: "已驳回",
    keep_open: "保持观察",
  };

  for (const form of document.querySelectorAll("[data-cluster-action-form]")) {
    const action = form.elements.action;
    const note = form.elements.note;
    const output = form.querySelector("[data-demo-review-result]");
    const syncReason = () => {
      note.required = action.value === "reject";
      note.setCustomValidity("");
    };
    action.addEventListener("change", syncReason);
    note.addEventListener("input", () => note.setCustomValidity(""));
    syncReason();

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (note.required && !note.value.trim()) {
        note.setCustomValidity("请填写驳回理由。");
        note.reportValidity();
        return;
      }

      const values = new FormData(form);
      const preview = document.createElement("div");
      preview.className = "risk-inline-empty";
      const heading = document.createElement("strong");
      heading.textContent = `本页预览 · ${action.selectedOptions[0].textContent}`;
      preview.append(heading);
      const status = document.createElement("p");
      const before = form.dataset.reviewStatus;
      const after = reviewStatuses[action.value] || before;
      status.textContent = `复核状态：${before === after ? after : `${before} → ${after}`}`;
      preview.append(status);
      for (const [name, label] of fieldLabels) {
        const value = values.get(name)?.trim();
        if (!value) continue;
        const line = document.createElement("p");
        line.textContent = `${label}：${value}`;
        preview.append(line);
      }
      const next = document.createElement("a");
      next.className = "risk-button risk-button-secondary";
      next.href = form.dataset.followup;
      next.textContent = "查看后续窗口验证";
      preview.append(next);
      output.replaceChildren(preview);
    });
    form.querySelector('button[type="submit"]').disabled = false;
  }
})();

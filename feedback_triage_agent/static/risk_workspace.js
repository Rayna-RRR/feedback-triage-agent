(() => {
  "use strict";

  const sidebar = document.querySelector("#risk-sidebar");
  const sidebarToggle = document.querySelector("[data-sidebar-toggle]");

  function setSidebarOpen(isOpen) {
    if (!sidebar || !sidebarToggle) return;
    sidebar.classList.toggle("is-open", isOpen);
    sidebarToggle.setAttribute("aria-expanded", String(isOpen));
    const label = sidebarToggle.querySelector(".sr-only");
    if (label) label.textContent = isOpen ? "关闭导航" : "打开导航";
  }

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", () => {
      setSidebarOpen(!sidebar.classList.contains("is-open"));
    });

    sidebar.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setSidebarOpen(false));
    });

    document.addEventListener("click", (event) => {
      if (
        window.innerWidth <= 920
        && sidebar.classList.contains("is-open")
        && !sidebar.contains(event.target)
        && !sidebarToggle.contains(event.target)
      ) {
        setSidebarOpen(false);
      }
    });
  }

  const comparisonBasis = document.querySelector("[data-comparison-basis]");
  const comparisonNote = document.querySelector("[data-comparison-note]");

  function syncComparisonNote() {
    if (!comparisonBasis || !comparisonNote) return;
    const showNote = !["equal_window", "equivalent_window"].includes(comparisonBasis.value);
    comparisonNote.hidden = !showNote;
    const textarea = comparisonNote.querySelector('textarea[name="comparison_note"]');
    if (textarea) textarea.required = showNote;
  }

  if (comparisonBasis) {
    comparisonBasis.addEventListener("change", syncComparisonNote);
    syncComparisonNote();
  }

  document.querySelectorAll("[data-risk-file]").forEach((input) => {
    const label = input.parentElement && input.parentElement.querySelector("[data-file-name]");
    const syncFileName = () => {
      if (!label) return;
      label.textContent = input.files && input.files.length
        ? `已选择：${input.files[0].name}`
        : "未选择文件";
    };
    input.addEventListener("change", syncFileName);
    syncFileName();
  });

  const importMode = document.querySelector("[data-import-mode]");
  const importGuidance = document.querySelector("[data-import-guidance]");

  function syncImportGuidance() {
    if (!importMode || !importGuidance) return;
    importGuidance.textContent = importMode.value === "incremental"
      ? "增量数据：只上传所选独立窗口上次导入后新增的反馈；完全相同的既有记录会明确计为跳过。"
      : "累计快照：上传所选独立窗口截至当前时点的完整反馈集合；重复的既有记录会明确计为跳过，不会覆盖其他窗口。";
  }

  if (importMode) {
    importMode.addEventListener("change", syncImportGuidance);
    syncImportGuidance();
  }

  function syncActionForm(form) {
    const actionSelect = form.querySelector("[data-cluster-action]");
    if (!actionSelect) return;
    const selectedAction = actionSelect.value;

    form.querySelectorAll("[data-action-group]").forEach((group) => {
      const actions = (group.dataset.actionGroup || "").split(/\s+/).filter(Boolean);
      const visible = actions.includes(selectedAction);
      group.hidden = !visible;
      group.querySelectorAll("input, select, textarea").forEach((control) => {
        control.disabled = !visible;
      });
    });

    const mergeTarget = form.querySelector('input[name="target_cluster_id"]');
    if (mergeTarget) mergeTarget.required = selectedAction === "merge";

    const splitIds = form.querySelector('textarea[name="feedback_ids"]');
    if (splitIds) splitIds.required = selectedAction === "split";
  }

  document.querySelectorAll("[data-cluster-action-form]").forEach((form) => {
    const actionSelect = form.querySelector("[data-cluster-action]");
    if (!actionSelect) return;
    actionSelect.addEventListener("change", () => syncActionForm(form));
    syncActionForm(form);
  });
})();

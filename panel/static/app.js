const state = {
  token: "",
  skills: [],
  trash: [],
  filters: {
    query: "",
    category: "",
    usage: "",
    health: "",
    view: "all",
  },
  selectedPath: "",
  currentPreview: null,
  lastFocus: null,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  rows: $("#skillRows"),
  empty: $("#emptyState"),
  resultCount: $("#resultCount"),
  search: $("#globalSearch"),
  category: $("#categoryFilter"),
  usage: $("#usageFilter"),
  health: $("#healthFilter"),
  sort: $("#sortSelect"),
  tabs: $("#statusTabs"),
  inspector: $("#detailInspector"),
  inspectorContent: $("#inspectorContent"),
  trashDrawer: $("#trashDrawer"),
  trashScrim: $("#trashScrim"),
  trashContent: $("#trashContent"),
  trashCount: $("#trashCount"),
  modal: $("#actionModal"),
  modalTitle: $("#modalTitle"),
  modalStatus: $("#modalStatus"),
  plan: $("#planOutput"),
  confirmationField: $("#confirmationField"),
  confirmationPhrase: $("#confirmationPhrase"),
  confirmationInput: $("#confirmationInput"),
  apply: $("#applyButton"),
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function safeUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (_error) {
    return "";
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-Skill-Manager-Token": state.token };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function toast(message, error = false) {
  const element = document.createElement("div");
  element.className = `toast${error ? " error" : ""}`;
  element.textContent = message;
  $("#toastRegion").append(element);
  setTimeout(() => element.remove(), 4200);
}

function compactWarning(value) {
  const lines = [...new Set(String(value || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
  if (lines.some((line) => /rate limit|HTTP (403|429)/i.test(line))) {
    return "GitHub API 访问额度已用完，Stars 刷新已停止；现有缓存数据保持不变。请稍后重试，或为本地服务配置 GITHUB_TOKEN。";
  }
  const visible = lines.slice(0, 3);
  return `${visible.join("\n")}${lines.length > visible.length ? `\n另有 ${lines.length - visible.length} 条警告` : ""}`;
}

function metric(value) {
  return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
}

function formatDate(value) {
  if (!value) return "未观测到显式调用";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "未获取"
    : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function sourceLabel(skill) {
  if (skill.github_repo) return skill.github_repo;
  if (skill.source_url) return "已声明非 GitHub 来源";
  return "本地 Skill（未声明仓库）";
}

function starsLabel(skill) {
  if (!skill.github_repo) return "不适用";
  return skill.stars == null ? "待获取" : metric(skill.stars);
}

function skillStatus(skill) {
  const update = String(skill.update || "");
  if (update.startsWith("git pull")) {
    return { key: "update", label: "可更新", reason: "Git 来源已识别，可先预览变更" };
  }
  return { key: "attention", label: "仅可卸载", reason: "未识别可更新仓库，但可安全移入回收站" };
}

function statusIcon(status) {
  if (status.key === "attention") return "/icons/warning.svg";
  if (status.key === "update") return "/icons/arrows-clockwise.svg";
  return "/icons/check-circle.svg";
}

function statusCounts() {
  return {
    all: state.skills.length,
    attention: state.skills.filter((skill) => skillStatus(skill).key === "attention").length,
    update: state.skills.filter((skill) => skillStatus(skill).key === "update").length,
    unused: state.skills.filter((skill) => Number(skill.usage_90d) === 0).length,
  };
}

function renderTabs() {
  const counts = statusCounts();
  $("#allCount").textContent = metric(counts.all);
  $("#attentionCount").textContent = metric(counts.attention);
  $("#updateCount").textContent = metric(counts.update);
  $("#unusedCount").textContent = metric(counts.unused);
  els.tabs.querySelectorAll("[data-view]").forEach((tab) => {
    const active = tab.dataset.view === state.filters.view;
    tab.classList.toggle("active", active);
    active ? tab.setAttribute("aria-current", "page") : tab.removeAttribute("aria-current");
  });
}

function populateSelect(select, values, current) {
  const first = select.options[0]?.outerHTML || '<option value="">全部</option>';
  select.innerHTML = first + values.map(([value, count]) => `<option value="${escapeHtml(value)}">${escapeHtml(value)} (${count})</option>`).join("");
  select.value = values.some(([value]) => value === current) ? current : "";
}

function rebuildFilterOptions() {
  const counts = (key) => [...state.skills.reduce((map, skill) => {
    const value = skill[key] || "未知";
    map.set(value, (map.get(value) || 0) + 1);
    return map;
  }, new Map()).entries()].sort((a, b) => a[0].localeCompare(b[0], "zh-CN"));
  populateSelect(els.category, counts("category"), state.filters.category);
}

function visibleSkills() {
  const query = state.filters.query.trim().toLowerCase();
  const output = state.skills.filter((skill) => {
    const status = skillStatus(skill);
    const matchesQuery = !query || [skill.name, skill.description, skill.github_repo, skill.path]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
    const matchesCategory = !state.filters.category || skill.category === state.filters.category;
    const matchesHealth = !state.filters.health || status.key === state.filters.health;
    const matchesUsage = !state.filters.usage
      || (state.filters.usage === "active30" && Number(skill.usage_30d) > 0)
      || (state.filters.usage === "active90" && Number(skill.usage_90d) > 0)
      || (state.filters.usage === "unused" && Number(skill.usage_90d) === 0);
    const matchesView = state.filters.view === "all"
      || (state.filters.view === "unused" && Number(skill.usage_90d) === 0)
      || status.key === state.filters.view;
    return matchesQuery && matchesCategory && matchesHealth && matchesUsage && matchesView;
  });

  output.sort((a, b) => {
    if (els.sort.value === "usage") return Number(b.usage_90d) - Number(a.usage_90d) || a.name.localeCompare(b.name);
    if (els.sort.value === "recent") return String(b.last_used || "").localeCompare(String(a.last_used || "")) || a.name.localeCompare(b.name);
    if (els.sort.value === "stars") return Number(b.stars ?? -1) - Number(a.stars ?? -1) || a.name.localeCompare(b.name);
    return a.name.localeCompare(b.name, "en");
  });
  return output;
}

function renderRows() {
  const skills = visibleSkills();
  els.resultCount.textContent = `共 ${metric(state.skills.length)} 个可管理技能 · 当前显示 ${metric(skills.length)} 个`;
  els.empty.hidden = skills.length !== 0;
  els.rows.innerHTML = skills.map((skill) => {
    const status = skillStatus(skill);
    const canUpdate = String(skill.update || "").startsWith("git pull");
    const canUninstall = skill.uninstall !== "protected";
    const selected = skill.path === state.selectedPath;
    return `<tr data-path="${escapeHtml(skill.path)}" tabindex="0" aria-selected="${selected}" class="${selected ? "selected" : ""}">
      <td class="skill-name"><strong title="${escapeHtml(skill.name)}">${escapeHtml(skill.name)}</strong><span title="${escapeHtml(skill.description || "暂无描述")}">${escapeHtml(skill.description || "暂无描述")}</span></td>
      <td><span class="tag category">${escapeHtml(skill.category || "其他")}</span></td>
      <td><span class="stars ${skill.stars == null ? "unknown" : ""}">${starsLabel(skill)}</span></td>
      <td class="usage-cell"><span class="usage-main">${metric(skill.usage_30d)} / ${metric(skill.usage_90d)} / ${metric(skill.usage_all)}</span><small>30 / 90 / 累计</small></td>
      <td><div class="health ${status.key}"><img src="${statusIcon(status)}" alt="" /><div><strong>${escapeHtml(status.label)}</strong><span title="${escapeHtml(status.reason)}">${escapeHtml(status.reason)}</span></div></div></td>
      <td><div class="row-actions">
        <button class="mini-button" type="button" data-action="detail">详情</button>
        ${canUpdate
    ? '<button class="mini-button update" type="button" data-action="update">更新</button>'
    : '<button class="mini-button uninstall" type="button" data-action="uninstall">卸载</button>'}
        ${canUpdate && canUninstall ? '<details class="action-menu"><summary aria-label="更多操作"><img src="/icons/dots-three.svg" alt="" /></summary><div class="menu-popover"><button type="button" data-action="uninstall">移入回收站</button></div></details>' : ""}
      </div></td>
    </tr>`;
  }).join("");
  renderTabs();

  if (skills.length && !state.selectedPath) selectSkill(skills.find((skill) => skill.name === "codex-skill-manager") || skills[0]);
}

function updateSelectedRow(focus = false) {
  els.rows.querySelectorAll("tr[data-path]").forEach((row) => {
    const selected = row.dataset.path === state.selectedPath;
    row.classList.toggle("selected", selected);
    row.setAttribute("aria-selected", String(selected));
    if (selected && focus) row.focus({ preventScroll: false });
  });
}

function renderInspector(skill) {
  if (!skill) return;
  const status = skillStatus(skill);
  const canUpdate = String(skill.update || "").startsWith("git pull");
  const canUninstall = skill.uninstall !== "protected";
  const sourceUrl = safeUrl(skill.source_url);
  els.inspectorContent.innerHTML = `
    <section class="detail-hero">
      <div class="detail-heading"><h3>${escapeHtml(skill.name)}</h3><span class="status-chip ${status.key}"><img src="${statusIcon(status)}" alt="" />${escapeHtml(status.label)}</span></div>
      <div class="detail-meta">${escapeHtml(skill.category || "其他")}</div>
      <p class="detail-description">${escapeHtml(skill.description || "暂无描述")}</p>
    </section>
    <section class="detail-section">
      <div class="info-row"><img src="/icons/folder.svg" alt="" /><span>本地路径</span><code title="${escapeHtml(skill.path)}">${escapeHtml(skill.path)}</code><button class="inline-icon" type="button" data-copy="${escapeHtml(skill.path)}" aria-label="复制安装路径"><img src="/icons/copy.svg" alt="" /></button></div>
      <div class="info-row"><img src="/icons/github.svg" alt="" /><span>来源仓库</span><strong title="${escapeHtml(sourceLabel(skill))}">${escapeHtml(sourceLabel(skill))}</strong>${sourceUrl ? `<a class="inline-icon" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer" aria-label="打开来源仓库"><img src="/icons/arrow-square-out.svg" alt="" /></a>` : "<span></span>"}</div>
      <div class="info-row"><img src="/icons/star.svg" alt="" /><span>Stars</span><strong>${starsLabel(skill)}</strong><span></span></div>
      <div class="info-row"><img src="/icons/info.svg" alt="" /><span>最近使用</span><strong>${escapeHtml(formatDate(skill.last_used))}</strong><span></span></div>
    </section>
    <section class="detail-section">
      <h4>显式使用情况</h4>
      <div class="usage-grid"><div><span>近 30 天</span><strong>${metric(skill.usage_30d)}</strong></div><div><span>近 90 天</span><strong>${metric(skill.usage_90d)}</strong></div><div><span>累计</span><strong>${metric(skill.usage_all)}</strong></div></div>
    </section>
    <section class="detail-section">
      <h4>维护方式</h4>
      <div class="maintenance-note"><img src="${statusIcon(status)}" alt="" /><span>${escapeHtml(status.reason)}。${escapeHtml(skill.update || "未获取更新策略")}</span></div>
    </section>
    <footer class="detail-footer">
      ${canUpdate
    ? '<button class="button primary" type="button" data-detail-action="update"><img src="/icons/arrows-clockwise.svg" alt="" />预览更新</button>'
    : '<button class="button danger" type="button" data-detail-action="uninstall"><img src="/icons/trash.svg" alt="" />预览卸载</button>'}
      ${canUpdate && canUninstall ? '<details class="action-menu"><summary class="icon-button" aria-label="更多维护操作"><img src="/icons/dots-three.svg" alt="" /></summary><div class="menu-popover"><button type="button" data-detail-action="uninstall">移入回收站</button></div></details>' : ""}
    </footer>`;

  const copyButton = els.inspectorContent.querySelector("[data-copy]");
  if (copyButton) copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(copyButton.dataset.copy);
      toast("安装路径已复制");
    } catch (_error) {
      toast("无法复制，请手动选择路径", true);
    }
  });
  els.inspectorContent.querySelectorAll("[data-detail-action]").forEach((button) => {
    button.addEventListener("click", () => beginAction(button.dataset.detailAction, skill));
  });
}

function selectSkill(skill, { focus = false, open = false } = {}) {
  if (!skill) return;
  state.selectedPath = skill.path;
  updateSelectedRow(focus);
  renderInspector(skill);
  if (open) document.body.classList.add("inspector-open");
}

function resetFilters() {
  state.filters = { query: "", category: "", usage: "", health: "", view: "all" };
  els.search.value = "";
  els.category.value = "";
  els.usage.value = "";
  els.health.value = "";
  renderRows();
}

async function loadInventory(mode = "local") {
  const refreshAllStars = mode === "all";
  const refreshMissingStars = mode === "missing";
  if (!refreshMissingStars) $("#refreshButton").disabled = true;
  $("#starsButton").disabled = true;
  $("#starsButton").textContent = refreshMissingStars ? "正在补齐…" : refreshAllStars ? "正在刷新…" : "刷新 Stars";
  if (!refreshMissingStars) els.resultCount.textContent = refreshAllStars ? "正在刷新 GitHub Stars…" : "正在扫描本机 Skills…";
  try {
    const params = new URLSearchParams({ refresh_stars: refreshAllStars ? "1" : refreshMissingStars ? "missing" : "0" });
    const data = await api(`/api/inventory?${params}`);
    state.skills = Array.isArray(data.skills) ? data.skills : [];
    rebuildFilterOptions();
    if (!state.skills.some((skill) => skill.path === state.selectedPath)) state.selectedPath = "";
    renderRows();
    const selected = state.skills.find((skill) => skill.path === state.selectedPath);
    if (selected) renderInspector(selected);
    if (data.warnings && !refreshMissingStars) toast(compactWarning(data.warnings), true);
  } catch (error) {
    if (!refreshMissingStars) {
      els.resultCount.textContent = "读取失败，可重新扫描";
      toast(error.message, true);
    }
  } finally {
    $("#refreshButton").disabled = false;
    $("#starsButton").disabled = false;
    $("#starsButton").textContent = "刷新 Stars";
  }
}

function openTrashDrawer() {
  els.trashScrim.hidden = false;
  els.trashDrawer.setAttribute("aria-hidden", "false");
  requestAnimationFrame(() => els.trashDrawer.classList.add("open"));
  setTimeout(() => els.trashDrawer.querySelector("[data-close]")?.focus(), 0);
}

function closeTrashDrawer() {
  els.trashDrawer.classList.remove("open");
  els.trashDrawer.setAttribute("aria-hidden", "true");
  setTimeout(() => { els.trashScrim.hidden = true; }, 280);
}

async function loadTrash(open = false) {
  try {
    const data = await api("/api/trash");
    state.trash = data.entries || [];
    els.trashCount.textContent = state.trash.filter((entry) => entry.restorable).length;
    els.trashContent.innerHTML = state.trash.length ? state.trash.map((entry) => `
      <article class="trash-item">
        <strong>${escapeHtml(entry.skill)}</strong>
        <p>${escapeHtml(entry.original_path || "未知路径")}<br />移入时间：${escapeHtml(formatDate(entry.trashed_at))}</p>
        <button class="mini-button" type="button" data-restore="${escapeHtml(entry.trash_id)}" ${entry.restorable ? "" : "disabled"}>预览恢复</button>
      </article>`).join("") : '<div class="empty-state"><img src="/icons/trash.svg" alt="" /><strong>回收站为空</strong><span>移除的 Skill 会保存在这里，便于恢复。</span></div>';
    els.trashContent.querySelectorAll("[data-restore]").forEach((button) => {
      button.addEventListener("click", () => beginAction("restore", { trash_id: button.dataset.restore }));
    });
    if (open) openTrashDrawer();
  } catch (error) {
    toast(error.message, true);
  }
}

function closeModal() {
  els.modal.hidden = true;
  state.currentPreview = null;
  els.confirmationInput.value = "";
  state.lastFocus?.focus?.();
  state.lastFocus = null;
}

async function beginAction(action, target) {
  state.lastFocus = document.activeElement;
  els.modal.hidden = false;
  els.modalTitle.textContent = action === "update" ? `更新 ${target.name}` : action === "uninstall" ? `移除 ${target.name}` : "恢复 Skill";
  els.modalStatus.className = "callout";
  els.modalStatus.textContent = "正在生成只读预览…";
  els.plan.hidden = true;
  els.confirmationField.hidden = true;
  els.apply.disabled = true;
  const payload = action === "restore"
    ? { action, trash_id: target.trash_id }
    : { action, name: target.name, path: target.path };
  try {
    const data = await api("/api/preview", { method: "POST", body: JSON.stringify(payload) });
    state.currentPreview = data;
    state.currentPreview.action = action;
    els.modalStatus.textContent = "请核对影响范围。预览凭证 5 分钟后失效，且只能使用一次。";
    els.plan.textContent = JSON.stringify(data.plan, null, 2);
    els.plan.hidden = false;
    els.confirmationPhrase.textContent = data.confirmation_phrase;
    els.confirmationField.hidden = false;
    els.confirmationInput.focus();
  } catch (error) {
    els.modalStatus.className = "callout error";
    els.modalStatus.textContent = `${error.message}。请关闭后重新扫描，再次尝试。`;
    $("#modalClose").focus();
  }
}

async function applyAction() {
  if (!state.currentPreview) return;
  const completedAction = state.currentPreview.action;
  els.apply.disabled = true;
  els.modalStatus.textContent = "正在执行并验证结果…";
  try {
    const data = await api("/api/apply", {
      method: "POST",
      body: JSON.stringify({ preview_id: state.currentPreview.preview_id, confirmation: els.confirmationInput.value }),
    });
    closeModal();
    closeTrashDrawer();
    document.body.classList.remove("inspector-open");
    toast(completedAction === "restore" ? "已恢复 Skill，清单已重新扫描" : "操作完成，技能清单已重新扫描");
    await Promise.all([loadInventory("local"), loadTrash(false)]);
    void loadInventory("missing");
    if (data.warnings) toast(data.warnings, true);
  } catch (error) {
    els.modalStatus.className = "callout error";
    els.modalStatus.textContent = `${error.message}。请检查确认短语或重新生成预览。`;
    els.apply.disabled = false;
  }
}

function trapModalFocus(event) {
  if (els.modal.hidden || event.key !== "Tab") return false;
  const focusable = [...els.modal.querySelectorAll('button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])')].filter((element) => !element.hidden);
  if (!focusable.length) return false;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); return true; }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); return true; }
  return false;
}

function bindEvents() {
  els.search.addEventListener("input", () => { state.filters.query = els.search.value; renderRows(); });
  els.category.addEventListener("change", () => { state.filters.category = els.category.value; renderRows(); });
  els.usage.addEventListener("change", () => { state.filters.usage = els.usage.value; renderRows(); });
  els.health.addEventListener("change", () => { state.filters.health = els.health.value; renderRows(); });
  els.sort.addEventListener("change", renderRows);

  els.tabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-view]");
    if (!tab) return;
    state.filters.view = tab.dataset.view;
    renderRows();
  });

  els.rows.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-path]");
    if (!row) return;
    const skill = state.skills.find((item) => item.path === row.dataset.path);
    if (!skill) return;
    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) { selectSkill(skill, { open: window.innerWidth <= 1120 }); return; }
    if (actionButton.dataset.action === "detail") selectSkill(skill, { open: true });
    else beginAction(actionButton.dataset.action, skill);
  });

  els.rows.addEventListener("keydown", (event) => {
    const row = event.target.closest("tr[data-path]");
    if (!row) return;
    const rows = [...els.rows.querySelectorAll("tr[data-path]")];
    const index = rows.indexOf(row);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      const next = rows[Math.min(index + 1, rows.length - 1)];
      selectSkill(state.skills.find((skill) => skill.path === next.dataset.path), { focus: true });
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const previous = rows[Math.max(index - 1, 0)];
      selectSkill(state.skills.find((skill) => skill.path === previous.dataset.path), { focus: true });
    } else if (event.key === "Enter") {
      event.preventDefault();
      selectSkill(state.skills.find((skill) => skill.path === row.dataset.path), { open: true });
    } else if (event.key.toLowerCase() === "u") {
      const skill = state.skills.find((item) => item.path === row.dataset.path);
      if (skill && String(skill.update || "").startsWith("git pull")) beginAction("update", skill);
    }
  });

  $("#refreshButton").addEventListener("click", async () => {
    await loadInventory("local");
    void loadInventory("missing");
  });
  $("#starsButton").addEventListener("click", () => loadInventory("all"));
  $("#trashButton").addEventListener("click", () => loadTrash(true));
  $("#clearFilters").addEventListener("click", resetFilters);
  $("#inspectorClose").addEventListener("click", () => document.body.classList.remove("inspector-open"));
  document.querySelector("[data-close='trash']").addEventListener("click", closeTrashDrawer);
  els.trashScrim.addEventListener("click", closeTrashDrawer);
  $("#modalClose").addEventListener("click", closeModal);
  $("#modalCancel").addEventListener("click", closeModal);
  els.confirmationInput.addEventListener("input", () => {
    els.apply.disabled = !state.currentPreview || els.confirmationInput.value !== state.currentPreview.confirmation_phrase;
  });
  els.apply.addEventListener("click", applyAction);

  document.addEventListener("keydown", (event) => {
    if (trapModalFocus(event)) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      els.search.focus();
    }
    if (event.key === "Escape") {
      if (!els.modal.hidden) closeModal();
      else if (els.trashDrawer.getAttribute("aria-hidden") === "false") closeTrashDrawer();
      else document.body.classList.remove("inspector-open");
    }
  });
}

async function init() {
  bindEvents();
  try {
    const response = await fetch("/api/config");
    const config = await response.json();
    state.token = config.token;
    await Promise.all([loadInventory("local"), loadTrash(false)]);
    void loadInventory("missing");
  } catch (error) {
    els.resultCount.textContent = "无法连接本机服务";
    toast(error.message, true);
  }
}

init();

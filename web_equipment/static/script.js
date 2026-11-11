/**
 * Клиентский скрипт модуля «Оборудование и инструмент» (РТПС).
 * Поддерживает официальный журнал «ДОМКРАТЫ» со всеми столбцами и периодическими испытаниями,
 * а также журнал электроинструмента и оснастки.
 */

// Глобальное состояние
let currentTab = "jacks"; // 'jacks' или 'tools'
let jacksItems = [];
let toolsItems = [];
let undoStack = [];
let redoStack = [];
let hasUnsavedChanges = false;
let selectedRowIndex = null;
let activeKpiFilter = "";
let serverToday = new Date();

// Инициализация при загрузке документа
document.addEventListener("DOMContentLoaded", () => {
  initDateHelpers();
  initCategoryFilterOptions();
  loadData();
  setupKeyboardShortcuts();
  setupWindowUnloadWarning();
});

/**
 * Инициализация работы с датами
 */
function initDateHelpers() {
  serverToday = new Date();
  serverToday.setHours(0, 0, 0, 0);
}

/**
 * Заполнение селекта категорий для вкладки инструмента
 */
function initCategoryFilterOptions() {
  const catSelect = document.getElementById("categoryFilter");
  if (!catSelect || !window.APP_CONFIG.CATEGORIES) return;

  catSelect.innerHTML = '<option value="">Все категории</option>';
  window.APP_CONFIG.CATEGORIES.forEach(cat => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    catSelect.appendChild(opt);
  });
}

/**
 * Переключение главного раздела (Домкраты / Инструмент)
 */
function switchMainTab(tab) {
  if (currentTab === tab) return;

  if (hasUnsavedChanges) {
    if (!confirm("В текущем журнале есть несохранённые изменения. Переключить без сохранения?")) {
      return;
    }
    setUnsavedChanges(false);
  }

  currentTab = tab;
  selectedRowIndex = null;
  undoStack = [];
  redoStack = [];
  updateUndoRedoButtons();

  const tabJacks = document.getElementById("tabJacks");
  const tabTools = document.getElementById("tabTools");
  const jacksContainer = document.getElementById("jacksTableContainer");
  const toolsContainer = document.getElementById("toolsTableContainer");
  const catGroup = document.getElementById("categoryFilterGroup");
  const pageTitle = document.getElementById("pageTitle");
  const pageSub = document.getElementById("pageSubtitle");
  const kpiSub = document.getElementById("kpiTotalSub");

  if (tab === "jacks") {
    tabJacks.classList.add("active");
    tabTools.classList.remove("active");
    jacksContainer.style.display = "block";
    toolsContainer.style.display = "none";
    if (catGroup) catGroup.style.display = "none";
    if (pageTitle) pageTitle.textContent = "Журнал учета домкратов";
    if (pageSub) pageSub.textContent = "Учет, периодические статические и динамические испытания домкратов (1 раз в 12 месяцев)";
    if (kpiSub) kpiSub.textContent = "домкратов на участке";
  } else {
    tabJacks.classList.remove("active");
    tabTools.classList.add("active");
    jacksContainer.style.display = "none";
    toolsContainer.style.display = "block";
    if (catGroup) catGroup.style.display = "flex";
    if (pageTitle) pageTitle.textContent = "Электроинструмент и оснастка";
    if (pageSub) pageSub.textContent = "Учет проверок изоляции электроинструмента и испытаний оснастки";
    if (kpiSub) kpiSub.textContent = "единиц инструмента";
  }

  populateFilterDropdowns();
  renderTable();
  updateKpis();
}

/**
 * Загрузка актуальных данных из базы
 */
async function loadData() {
  try {
    const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/state`);
    if (!res.ok) {
      if (res.status === 401) {
        window.location.href = `${window.APP_CONFIG.MAIN_SITE_URL}/login?next=/equipment`;
        return;
      }
      throw new Error(`Ошибка сервера: ${res.status}`);
    }
    const data = await res.json();
    jacksItems = Array.isArray(data.jacks) ? data.jacks : [];
    toolsItems = Array.isArray(data.tools) ? data.tools : [];

    undoStack = [];
    redoStack = [];
    setUnsavedChanges(false);
    updateUndoRedoButtons();

    populateFilterDropdowns();
    renderTable();
    updateKpis();
    showToast("Данные успешно загружены", "info");
  } catch (err) {
    console.error("Ошибка загрузки:", err);
    showToast("Ошибка при загрузке данных: " + err.message, "error");
  }
}

/**
 * Безопасный парсинг даты из строки формата ДД.ММ.ГГГГ или ГГГГ-ММ-ДД
 */
function parseDate(dateStr) {
  if (!dateStr) return null;
  const s = String(dateStr).trim();
  if (!s) return null;

  if (s.includes(".")) {
    const parts = s.split(".");
    if (parts.length === 3) {
      const d = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10) - 1;
      let y = parseInt(parts[2], 10);
      // Поддержка короткого года из журнала (например '25' -> 2025)
      if (y < 100) y += 2000;
      if (!isNaN(d) && !isNaN(m) && !isNaN(y)) {
        return new Date(y, m, d);
      }
    }
  } else if (s.includes("-")) {
    const parts = s.split("-");
    if (parts.length === 3) {
      const y = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10) - 1;
      const d = parseInt(parts[2], 10);
      if (!isNaN(d) && !isNaN(m) && !isNaN(y)) {
        return new Date(y, m, d);
      }
    }
  }
  return null;
}

/**
 * Форматирование объекта даты в строку ДД.ММ.ГГГГ
 */
function formatDate(date) {
  if (!date || isNaN(date.getTime())) return "";
  const d = String(date.getDate()).padStart(2, "0");
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const y = date.getFullYear();
  return `${d}.${m}.${y}`;
}

/**
 * Прибавление месяцев к дате с корректным учетом конца месяца
 */
function addMonths(date, months) {
  if (!date) return null;
  const target = new Date(date.getTime());
  const curDay = target.getDate();
  target.setDate(1);
  target.setMonth(target.getMonth() + months);
  const maxDays = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(curDay, maxDays));
  return target;
}

/**
 * Получение последнего дня следующего календарного месяца
 */
function getEndOfNextMonth(date) {
  const d = new Date(date.getTime());
  const nextMonth = new Date(d.getFullYear(), d.getMonth() + 2, 0);
  nextMonth.setHours(23, 59, 59, 999);
  return nextMonth;
}

/**
 * Расчет статуса проверки для единицы
 */
function calculateItemStatus(item) {
  const isRepair = item.in_repair === 1 || item.in_repair === "1" || item.in_repair === true;
  if (isRepair) {
    return {
      status: "repair",
      badgeClass: "badge-repair",
      text: "🔧 В ремонте",
      rowClass: "row-repair",
      daysDiff: 0,
    };
  }

  const nextDate = parseDate(item.next_test_date);
  if (!nextDate) {
    return {
      status: "no_date",
      badgeClass: "badge-repair",
      text: "⚪ Дата не задана",
      rowClass: "",
      daysDiff: 9999,
    };
  }

  const today = new Date(serverToday);
  const diffTime = nextDate.getTime() - today.getTime();
  const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));
  const endOfNextMonth = getEndOfNextMonth(today);

  if (nextDate < today) {
    const overdueDays = Math.abs(diffDays);
    return {
      status: "overdue",
      badgeClass: "badge-overdue",
      text: `🔴 Просрочено (${overdueDays} дн.)`,
      rowClass: "row-overdue",
      daysDiff: diffDays,
    };
  } else if (nextDate <= endOfNextMonth) {
    return {
      status: "upcoming",
      badgeClass: "badge-upcoming",
      text: `🟡 Срок через ${diffDays} дн.`,
      rowClass: "row-upcoming",
      daysDiff: diffDays,
    };
  } else {
    return {
      status: "ok",
      badgeClass: "badge-ok",
      text: `🟢 В норме (${diffDays} дн.)`,
      rowClass: "",
      daysDiff: diffDays,
    };
  }
}

/**
 * Получение текущего рабочего массива данных
 */
function getCurrentItems() {
  return currentTab === "jacks" ? jacksItems : toolsItems;
}

/**
 * Пересчет и отображение индикаторов KPI в шапке
 */
function updateKpis() {
  const items = getCurrentItems();
  let total = items.length;
  let okCount = 0;
  let upcomingCount = 0;
  let overdueCount = 0;
  let repairCount = 0;

  items.forEach(item => {
    const st = calculateItemStatus(item);
    if (st.status === "repair") {
      repairCount++;
    } else if (st.status === "overdue") {
      overdueCount++;
    } else if (st.status === "upcoming") {
      upcomingCount++;
    } else if (st.status === "ok") {
      okCount++;
    }
  });

  document.getElementById("kpiTotal").textContent = total;
  document.getElementById("kpiOk").textContent = okCount;
  document.getElementById("kpiUpcoming").textContent = upcomingCount;
  document.getElementById("kpiOverdue").textContent = overdueCount;
  document.getElementById("kpiRepair").textContent = repairCount;
}

/**
 * Заполнение выпадающих списков фильтров
 */
function populateFilterDropdowns() {
  const monthSelect = document.getElementById("monthFilter");
  if (!monthSelect) return;

  const currentMonth = monthSelect.value;
  const items = getCurrentItems();
  const months = new Set();

  items.forEach(item => {
    const nd = parseDate(item.next_test_date);
    if (nd) {
      const monthKey = `${String(nd.getMonth() + 1).padStart(2, "0")}.${nd.getFullYear()}`;
      months.add(monthKey);
    }
  });

  monthSelect.innerHTML = '<option value="">Все месяцы</option>';
  Array.from(months).sort().forEach(m => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    monthSelect.appendChild(opt);
  });
  monthSelect.value = currentMonth;
}

/**
 * Отрисовка активной таблицы
 */
function renderTable() {
  if (currentTab === "jacks") {
    renderJacksTable();
  } else {
    renderToolsTable();
  }
}

/**
 * Отрисовка журнала домкратов (13 столбцов строго по журналу)
 */
function renderJacksTable() {
  const tbody = document.getElementById("jacksTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const searchVal = (document.getElementById("searchFilter")?.value || "").toLowerCase().trim();
  const statusVal = activeKpiFilter || (document.getElementById("statusFilter")?.value || "").trim();
  const monthVal = (document.getElementById("monthFilter")?.value || "").trim();

  let visibleCount = 0;
  const canEdit = window.APP_CONFIG.CAN_EDIT;
  const disabledAttr = canEdit ? "" : "disabled";

  jacksItems.forEach((item, index) => {
    const st = calculateItemStatus(item);

    // Фильтрация
    if (searchVal) {
      const combined = `${item.name || ""} ${item.inv_number || ""} ${item.capacity || ""} ${item.inspector || ""} ${item.notes || ""}`.toLowerCase();
      if (!combined.includes(searchVal)) return;
    }

    if (statusVal) {
      if (statusVal === "repair" && st.status !== "repair") return;
      if (statusVal === "overdue" && st.status !== "overdue") return;
      if (statusVal === "upcoming" && st.status !== "upcoming") return;
      if (statusVal === "ok" && st.status !== "ok") return;
    }

    if (monthVal) {
      const nd = parseDate(item.next_test_date);
      if (!nd) return;
      const itemMonth = `${String(nd.getMonth() + 1).padStart(2, "0")}.${nd.getFullYear()}`;
      if (itemMonth !== monthVal) return;
    }

    visibleCount++;
    const row = document.createElement("tr");
    row.dataset.index = index;
    if (st.rowClass) row.classList.add(st.rowClass);
    if (selectedRowIndex === index) row.classList.add("row-selected");

    row.onclick = (e) => onRowClick(index, e);

    row.innerHTML = `
      <td style="text-align: center; color: var(--muted); font-weight: 600;">${visibleCount}</td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.name)}" 
               placeholder="УДС-160(1)..." onchange="updateJackField(${index}, 'name', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.inv_number)}" 
               placeholder="Хоз. №" onchange="updateJackField(${index}, 'inv_number', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.capacity)}" 
               placeholder="тн." onchange="updateJackField(${index}, 'capacity', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.prev_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="updateJackField(${index}, 'prev_test_date', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.test_reason)}" 
               placeholder="очередное..." onchange="updateJackField(${index}, 'test_reason', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.repair_info)}" 
               placeholder="Сведения о ремонте..." onchange="updateJackField(${index}, 'repair_info', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.inspection_result || 'удовл.')}" 
               placeholder="удовл." onchange="updateJackField(${index}, 'inspection_result', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.static_test_result || 'удовл.')}" 
               placeholder="удовл." onchange="updateJackField(${index}, 'static_test_result', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.dynamic_test_result || 'удовл.')}" 
               placeholder="удовл." onchange="updateJackField(${index}, 'dynamic_test_result', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="onJackTestDateChange(${index}, this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.next_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="updateJackField(${index}, 'next_test_date', this.value)">
      </td>
      <td style="text-align: center;">
        <span class="status-badge ${st.badgeClass}">${st.text}</span>
      </td>
      <td style="text-align: center;">
        <input type="checkbox" class="repair-check" ${disabledAttr} ${item.in_repair ? "checked" : ""} 
               onchange="onJackRepairChange(${index}, this.checked)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.inspector)}" 
               placeholder="Ф.И.О." onchange="updateJackField(${index}, 'inspector', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.notes)}" 
               placeholder="Примечание..." onchange="updateJackField(${index}, 'notes', this.value)">
      </td>
      ${canEdit ? `
      <td style="text-align: center;">
        <button type="button" class="row-delete-btn" title="Удалить строку" onclick="deleteRowByIndex(${index}, event)">✕</button>
      </td>` : ""}
    `;

    tbody.appendChild(row);
  });

  document.getElementById("visibleRowCount").textContent = visibleCount;
  document.getElementById("totalRowCount").textContent = jacksItems.length;

  if (visibleCount === 0) {
    const emptyTr = document.createElement("tr");
    emptyTr.innerHTML = `
      <td colspan="${canEdit ? 17 : 16}" style="text-align: center; padding: 30px; color: var(--muted);">
        В журнале домкратов нет записей, соответствующих критериям фильтрации
      </td>
    `;
    tbody.appendChild(emptyTr);
  }
}

/**
 * Отрисовка журнала инструмента
 */
function renderToolsTable() {
  const tbody = document.getElementById("toolsTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const searchVal = (document.getElementById("searchFilter")?.value || "").toLowerCase().trim();
  const catVal = (document.getElementById("categoryFilter")?.value || "").trim();
  const statusVal = activeKpiFilter || (document.getElementById("statusFilter")?.value || "").trim();
  const monthVal = (document.getElementById("monthFilter")?.value || "").trim();

  let visibleCount = 0;
  const canEdit = window.APP_CONFIG.CAN_EDIT;
  const disabledAttr = canEdit ? "" : "disabled";

  toolsItems.forEach((item, index) => {
    const st = calculateItemStatus(item);

    if (searchVal) {
      const combined = `${item.name || ""} ${item.inv_number || ""} ${item.location || ""} ${item.responsible || ""}`.toLowerCase();
      if (!combined.includes(searchVal)) return;
    }

    if (catVal && item.category !== catVal) return;

    if (statusVal) {
      if (statusVal === "repair" && st.status !== "repair") return;
      if (statusVal === "overdue" && st.status !== "overdue") return;
      if (statusVal === "upcoming" && st.status !== "upcoming") return;
      if (statusVal === "ok" && st.status !== "ok") return;
    }

    if (monthVal) {
      const nd = parseDate(item.next_test_date);
      if (!nd) return;
      const itemMonth = `${String(nd.getMonth() + 1).padStart(2, "0")}.${nd.getFullYear()}`;
      if (itemMonth !== monthVal) return;
    }

    visibleCount++;
    const row = document.createElement("tr");
    row.dataset.index = index;
    if (st.rowClass) row.classList.add(st.rowClass);
    if (selectedRowIndex === index) row.classList.add("row-selected");

    row.onclick = (e) => onRowClick(index, e);

    row.innerHTML = `
      <td style="text-align: center; color: var(--muted); font-weight: 600;">${visibleCount}</td>
      <td>
        <select class="cell-editable" ${disabledAttr} onchange="updateToolField(${index}, 'category', this.value)">
          ${getCategoriesOptionsHtml(item.category)}
        </select>
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.name)}" 
               placeholder="Наименование..." onchange="updateToolField(${index}, 'name', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.inv_number)}" 
               placeholder="Инв. №" onchange="updateToolField(${index}, 'inv_number', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.location)}" 
               placeholder="Место / участок..." onchange="updateToolField(${index}, 'location', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.responsible)}" 
               placeholder="Ответственный..." onchange="updateToolField(${index}, 'responsible', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.test_type)}" 
               placeholder="Вид проверки..." onchange="updateToolField(${index}, 'test_type', this.value)">
      </td>
      <td>
        <input type="number" min="1" max="60" class="cell-editable cell-center" ${disabledAttr} 
               value="${esc(item.periodicity || '6')}" onchange="onToolPeriodicityChange(${index}, this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.last_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="onToolLastDateChange(${index}, this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.next_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="updateToolField(${index}, 'next_test_date', this.value)">
      </td>
      <td style="text-align: center;">
        <span class="status-badge ${st.badgeClass}">${st.text}</span>
      </td>
      <td style="text-align: center;">
        <input type="checkbox" class="repair-check" ${disabledAttr} ${item.in_repair ? "checked" : ""} 
               onchange="onToolRepairChange(${index}, this.checked)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.protocol_num)}" 
               placeholder="№ протокола..." onchange="updateToolField(${index}, 'protocol_num', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.notes)}" 
               placeholder="Примечание..." onchange="updateToolField(${index}, 'notes', this.value)">
      </td>
      ${canEdit ? `
      <td style="text-align: center;">
        <button type="button" class="row-delete-btn" title="Удалить строку" onclick="deleteRowByIndex(${index}, event)">✕</button>
      </td>` : ""}
    `;

    tbody.appendChild(row);
  });

  document.getElementById("visibleRowCount").textContent = visibleCount;
  document.getElementById("totalRowCount").textContent = toolsItems.length;

  if (visibleCount === 0) {
    const emptyTr = document.createElement("tr");
    emptyTr.innerHTML = `
      <td colspan="${canEdit ? 15 : 14}" style="text-align: center; padding: 30px; color: var(--muted);">
        В журнале инструмента нет записей, соответствующих критериям фильтрации
      </td>
    `;
    tbody.appendChild(emptyTr);
  }
}

/**
 * Опции селекта категорий
 */
function getCategoriesOptionsHtml(selectedCat) {
  const categories = window.APP_CONFIG.CATEGORIES || [];
  return categories.map(cat => {
    const sel = cat === selectedCat ? "selected" : "";
    return `<option value="${esc(cat)}" ${sel}>${esc(cat)}</option>`;
  }).join("");
}

/**
 * Экранирование HTML
 */
function esc(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Выбор строки кликом
 */
function onRowClick(index, event) {
  if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT" || event.target.tagName === "BUTTON") {
    selectedRowIndex = index;
    return;
  }
  selectedRowIndex = index;
  const tableSelector = currentTab === "jacks" ? "#jacksTable tbody tr" : "#toolsTable tbody tr";
  document.querySelectorAll(tableSelector).forEach(tr => {
    tr.classList.remove("row-selected");
    if (parseInt(tr.dataset.index, 10) === index) {
      tr.classList.add("row-selected");
    }
  });
}

/**
 * Фильтрация по KPI
 */
function filterByKpi(status) {
  document.querySelectorAll(".kpi-card").forEach(c => c.classList.remove("active-kpi"));
  
  if (activeKpiFilter === status) {
    activeKpiFilter = "";
  } else {
    activeKpiFilter = status;
    const cardMap = { "": 0, "ok": 1, "upcoming": 2, "overdue": 3, "repair": 4 };
    const idx = cardMap[status];
    const cards = document.querySelectorAll(".kpi-card");
    if (cards[idx]) cards[idx].classList.add("active-kpi");
  }

  const statusSelect = document.getElementById("statusFilter");
  if (statusSelect) statusSelect.value = activeKpiFilter;

  applyFilters();
}

/**
 * Применение фильтров
 */
function applyFilters() {
  renderTable();
}

/**
 * Сброс фильтров
 */
function resetFilters() {
  document.getElementById("searchFilter").value = "";
  const catSel = document.getElementById("categoryFilter");
  if (catSel) catSel.value = "";
  document.getElementById("statusFilter").value = "";
  document.getElementById("monthFilter").value = "";
  activeKpiFilter = "";

  document.querySelectorAll(".kpi-card").forEach(c => c.classList.remove("active-kpi"));
  renderTable();
}

/**
 * Сохранение в стек отмены (Undo)
 */
function pushHistory() {
  const stateCopy = {
    tab: currentTab,
    jacks: JSON.parse(JSON.stringify(jacksItems)),
    tools: JSON.parse(JSON.stringify(toolsItems)),
  };
  undoStack.push(stateCopy);
  if (undoStack.length > 50) undoStack.shift();
  redoStack = [];
  setUnsavedChanges(true);
  updateUndoRedoButtons();
}

/**
 * Установка флага несохраненных изменений
 */
function setUnsavedChanges(val) {
  hasUnsavedChanges = val;
  const saveBtn = document.getElementById("saveBtn");
  if (saveBtn) {
    if (val) {
      saveBtn.classList.add("primary");
      saveBtn.textContent = "Сохранить *";
    } else {
      saveBtn.textContent = "Сохранить";
    }
  }
}

/**
 * Обновление кнопок Undo / Redo
 */
function updateUndoRedoButtons() {
  const cancelBtn = document.getElementById("cancelBtn");
  const restoreBtn = document.getElementById("restoreBtn");
  if (cancelBtn) cancelBtn.disabled = undoStack.length === 0;
  if (restoreBtn) restoreBtn.disabled = redoStack.length === 0;
}

/**
 * Отмена (Ctrl+Z)
 */
function cancelChanges() {
  if (undoStack.length === 0) return;
  const curState = {
    tab: currentTab,
    jacks: JSON.parse(JSON.stringify(jacksItems)),
    tools: JSON.parse(JSON.stringify(toolsItems)),
  };
  redoStack.push(curState);
  const prevState = undoStack.pop();
  jacksItems = prevState.jacks;
  toolsItems = prevState.tools;
  setUnsavedChanges(true);
  updateUndoRedoButtons();
  renderTable();
  updateKpis();
  showToast("Действие отменено", "info");
}

/**
 * Повтор (Ctrl+Y)
 */
function restoreChanges() {
  if (redoStack.length === 0) return;
  const curState = {
    tab: currentTab,
    jacks: JSON.parse(JSON.stringify(jacksItems)),
    tools: JSON.parse(JSON.stringify(toolsItems)),
  };
  undoStack.push(curState);
  const nextState = redoStack.pop();
  jacksItems = nextState.jacks;
  toolsItems = nextState.tools;
  setUnsavedChanges(true);
  updateUndoRedoButtons();
  renderTable();
  updateKpis();
  showToast("Действие возвращено", "info");
}

/**
 * Изменение поля домкрата
 */
function updateJackField(index, field, value) {
  if (!jacksItems[index]) return;
  if (jacksItems[index][field] === value) return;

  pushHistory();
  jacksItems[index][field] = value;
  jacksItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Автоматический пересчет следующего освидетельствования домкрата (+12 месяцев)
 */
function onJackTestDateChange(index, newTestDateStr) {
  if (!jacksItems[index]) return;
  pushHistory();
  jacksItems[index].test_date = newTestDateStr;

  const d = parseDate(newTestDateStr);
  if (d) {
    const nextDate = addMonths(d, 12);
    jacksItems[index].next_test_date = formatDate(nextDate);
  }
  jacksItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

function onJackRepairChange(index, isChecked) {
  if (!jacksItems[index]) return;
  pushHistory();
  jacksItems[index].in_repair = isChecked ? 1 : 0;
  jacksItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Функции изменения инструмента
 */
function updateToolField(index, field, value) {
  if (!toolsItems[index]) return;
  if (toolsItems[index][field] === value) return;

  pushHistory();
  toolsItems[index][field] = value;
  toolsItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

function onToolLastDateChange(index, newDateStr) {
  if (!toolsItems[index]) return;
  pushHistory();
  toolsItems[index].last_test_date = newDateStr;

  const d = parseDate(newDateStr);
  const p = parseInt(toolsItems[index].periodicity || "6", 10) || 6;
  if (d) {
    toolsItems[index].next_test_date = formatDate(addMonths(d, p));
  }
  toolsItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

function onToolPeriodicityChange(index, newPeriodicity) {
  if (!toolsItems[index]) return;
  pushHistory();
  toolsItems[index].periodicity = newPeriodicity;

  const d = parseDate(toolsItems[index].last_test_date);
  const p = parseInt(newPeriodicity || "6", 10) || 6;
  if (d) {
    toolsItems[index].next_test_date = formatDate(addMonths(d, p));
  }
  toolsItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

function onToolRepairChange(index, isChecked) {
  if (!toolsItems[index]) return;
  pushHistory();
  toolsItems[index].in_repair = isChecked ? 1 : 0;
  toolsItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Добавление новой строки
 */
function addRow() {
  if (!window.APP_CONFIG.CAN_EDIT) return;
  pushHistory();

  const nowFormatted = formatDate(serverToday);
  const nextYearFormatted = formatDate(addMonths(serverToday, 12));

  if (currentTab === "jacks") {
    const newJack = {
      sort_order: jacksItems.length + 1,
      name: "",
      inv_number: "",
      capacity: "40",
      prev_test_date: nowFormatted,
      test_reason: "очередное",
      repair_info: "",
      inspection_result: "удовл.",
      static_test_result: "удовл.",
      dynamic_test_result: "удовл.",
      test_date: nowFormatted,
      next_test_date: nextYearFormatted,
      inspector: "Шварчков С. А.",
      in_repair: 0,
      notes: "",
      updated_at: new Date().toLocaleString("ru-RU"),
    };
    jacksItems.unshift(newJack);
  } else {
    const newTool = {
      sort_order: toolsItems.length + 1,
      category: "Электроинструмент",
      name: "",
      inv_number: "",
      location: "Участок РТПС",
      responsible: "",
      test_type: "Проверка изоляции (мегомметром)",
      periodicity: "6",
      last_test_date: nowFormatted,
      next_test_date: formatDate(addMonths(serverToday, 6)),
      in_repair: 0,
      test_result: "Годен",
      protocol_num: "",
      notes: "",
      updated_at: new Date().toLocaleString("ru-RU"),
    };
    toolsItems.unshift(newTool);
  }

  selectedRowIndex = 0;
  renderTable();
  updateKpis();
  populateFilterDropdowns();
  showToast("Добавлена новая строка в журнал", "info");
}

/**
 * Удаление выбранной строки
 */
function removeSelectedRow() {
  if (!window.APP_CONFIG.CAN_EDIT) return;
  if (selectedRowIndex === null) {
    showToast("Выберите строку для удаления кликом", "info");
    return;
  }
  deleteRowByIndex(selectedRowIndex);
}

function deleteRowByIndex(index, event) {
  if (event) event.stopPropagation();
  if (!window.APP_CONFIG.CAN_EDIT) return;

  const items = getCurrentItems();
  if (!items[index]) return;

  const name = items[index].name || items[index].inv_number || "выбранную запись";
  if (!confirm(`Удалить из журнала «${name}»?`)) {
    return;
  }

  pushHistory();
  items.splice(index, 1);
  selectedRowIndex = null;

  renderTable();
  updateKpis();
  populateFilterDropdowns();
  showToast("Запись удалена", "info");
}

/**
 * Сохранение изменений в базу данных
 */
async function saveData() {
  if (!window.APP_CONFIG.CAN_EDIT) return;
  const saveBtn = document.getElementById("saveBtn");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = "Сохранение...";
  }

  try {
    const endpoint = currentTab === "jacks" ? "/api/jacks" : "/api/tools";
    const items = getCurrentItems();

    const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });

    if (!res.ok) {
      throw new Error(`Ошибка сервера: ${res.status}`);
    }

    setUnsavedChanges(false);
    showToast("Журнал успешно сохранён!", "success");
  } catch (err) {
    console.error("Ошибка сохранения:", err);
    showToast("Не удалось сохранить: " + err.message, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Сохранить";
    }
  }
}

/**
 * Экспорт активного журнала в CSV (Excel)
 */
function exportActiveCsv() {
  window.location.href = `${window.APP_CONFIG.APP_PREFIX}/export/csv?tab=${currentTab}`;
}

/**
 * Копирование выделенной или всех строк в буфер обмена (TSV для Excel)
 */
function copySelectedRows() {
  const items = getCurrentItems();
  if (items.length === 0) {
    showToast("Нет записей для копирования", "info");
    return;
  }

  const rowsToCopy = (selectedRowIndex !== null && items[selectedRowIndex])
    ? [items[selectedRowIndex]]
    : items;

  let headers = [];
  let tsvRows = [];

  if (currentTab === "jacks") {
    headers = [
      "Наименование грузоподъемных механизмов (1)", "Хоз. № (2)", "Грузоподъемность, тн. (3)",
      "Дата посл. испытания (4)", "Причина (5)", "Сведения о ремонте (6)",
      "Осмотр (7)", "Статическое испытание (8)", "Динамическое испытание (9)",
      "Дата испытания (10)", "Дата след. освидетельствования (11)", "В ремонте",
      "Ф.И.О. (12)", "Примечание"
    ];
    tsvRows = rowsToCopy.map(item => [
      item.name || "",
      item.inv_number || "",
      item.capacity || "",
      item.prev_test_date || "",
      item.test_reason || "",
      item.repair_info || "",
      item.inspection_result || "",
      item.static_test_result || "",
      item.dynamic_test_result || "",
      item.test_date || "",
      item.next_test_date || "",
      item.in_repair ? "Да" : "Нет",
      item.inspector || "",
      item.notes || "",
    ]);
  } else {
    headers = [
      "Категория", "Наименование", "Инв. №", "Место", "Ответственный",
      "Вид проверки", "Периодичность (мес.)", "Дата проверки", "След. дата",
      "В ремонте", "Результат", "№ акта", "Примечание"
    ];
    tsvRows = rowsToCopy.map(item => [
      item.category || "",
      item.name || "",
      item.inv_number || "",
      item.location || "",
      item.responsible || "",
      item.test_type || "",
      item.periodicity || "",
      item.last_test_date || "",
      item.next_test_date || "",
      item.in_repair ? "Да" : "Нет",
      item.test_result || "",
      item.protocol_num || "",
      item.notes || "",
    ]);
  }

  let tsv = headers.join("\t") + "\n";
  tsvRows.forEach(r => {
    tsv += r.join("\t") + "\n";
  });

  navigator.clipboard.writeText(tsv).then(() => {
    showToast(`Скопировано (${rowsToCopy.length} строк). Можно вставить в Excel!`, "success");
  }).catch(() => {
    showToast("Не удалось скопировать в буфер обмена", "error");
  });
}

/**
 * Горячие клавиши
 */
function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveData();
    } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
      e.preventDefault();
      cancelChanges();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      restoreChanges();
    } else if (e.key === "Delete" && selectedRowIndex !== null) {
      if (e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault();
        removeSelectedRow();
      }
    }
  });
}

function setupWindowUnloadWarning() {
  window.addEventListener("beforeunload", (e) => {
    if (hasUnsavedChanges) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

let targetNavUrl = "";
function requestHomeClick(event) {
  if (!hasUnsavedChanges) return true;
  event.preventDefault();
  targetNavUrl = `${window.APP_CONFIG.MAIN_SITE_URL}/`;
  const modal = document.getElementById("unsavedChangesModal");
  if (modal) modal.style.display = "flex";
  return false;
}

function closeUnsavedModal() {
  const modal = document.getElementById("unsavedChangesModal");
  if (modal) modal.style.display = "none";
}

async function confirmSaveAndLeave() {
  await saveData();
  closeUnsavedModal();
  window.location.href = targetNavUrl || `${window.APP_CONFIG.MAIN_SITE_URL}/`;
}

function confirmLeaveWithoutSaving() {
  hasUnsavedChanges = false;
  closeUnsavedModal();
  window.location.href = targetNavUrl || `${window.APP_CONFIG.MAIN_SITE_URL}/`;
}

let toastTimeout = null;
function showToast(message, type = "info") {
  const toast = document.getElementById("toastNotification");
  if (!toast) return;

  toast.textContent = message;
  toast.className = `toast ${type} show`;

  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    toast.className = "toast";
  }, 2800);
}

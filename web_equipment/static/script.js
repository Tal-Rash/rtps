/**
 * Клиентский скрипт модуля «Оборудование и инструмент» (РТПС).
 * Реализует интерактивную таблицу, фильтрацию, авторасчет сроков испытаний,
 * историю изменений (Undo/Redo), копирование в буфер и сохранение в базу данных.
 */

// Глобальное состояние приложения
let equipmentItems = [];
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
 * Инициализация работы с датами и определение текущей даты
 */
function initDateHelpers() {
  serverToday = new Date();
  serverToday.setHours(0, 0, 0, 0);
}

/**
 * Заполнение селекта категорий начальными данными
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
 * Загрузка актуальных данных из базы через API
 */
async function loadData() {
  try {
    const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/items`);
    if (!res.ok) {
      if (res.status === 401) {
        window.location.href = `${window.APP_CONFIG.MAIN_SITE_URL}/login?next=/equipment`;
        return;
      }
      throw new Error(`Ошибка сервера: ${res.status}`);
    }
    const data = await res.json();
    equipmentItems = Array.isArray(data.items) ? data.items : [];
    
    // Сбрасываем историю изменений после загрузки
    undoStack = [];
    redoStack = [];
    setUnsavedChanges(false);
    updateUndoRedoButtons();

    // Обновляем фильтры, KPI и таблицу
    populateFilterDropdowns();
    renderTable();
    updateKpis();
    showToast("Данные успешно загружены", "info");
  } catch (err) {
    console.error("Ошибка загрузки данных оборудования:", err);
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
      const y = parseInt(parts[2], 10);
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
 * Расчет статуса проверки для единицы оборудования
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
 * Пересчет и отображение индикаторов KPI в шапке
 */
function updateKpis() {
  let total = equipmentItems.length;
  let okCount = 0;
  let upcomingCount = 0;
  let overdueCount = 0;
  let repairCount = 0;

  equipmentItems.forEach(item => {
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
 * Заполнение выпадающих списков фильтров по местонахождению и месяцам
 */
function populateFilterDropdowns() {
  const locSelect = document.getElementById("locationFilter");
  const monthSelect = document.getElementById("monthFilter");
  if (!locSelect || !monthSelect) return;

  const currentLoc = locSelect.value;
  const currentMonth = monthSelect.value;

  const locations = new Set();
  const months = new Set();

  equipmentItems.forEach(item => {
    if (item.location && item.location.trim()) {
      locations.add(item.location.trim());
    }
    const nd = parseDate(item.next_test_date);
    if (nd) {
      const monthKey = `${String(nd.getMonth() + 1).padStart(2, "0")}.${nd.getFullYear()}`;
      months.add(monthKey);
    }
  });

  // Заполняем места
  locSelect.innerHTML = '<option value="">Все места</option>';
  Array.from(locations).sort().forEach(loc => {
    const opt = document.createElement("option");
    opt.value = loc;
    opt.textContent = loc;
    locSelect.appendChild(opt);
  });
  locSelect.value = currentLoc;

  // Заполняем месяцы
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
 * Отрисовка основной таблицы оборудования с учетом фильтров
 */
function renderTable() {
  const tbody = document.getElementById("tableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const searchVal = (document.getElementById("searchFilter")?.value || "").toLowerCase().trim();
  const catVal = (document.getElementById("categoryFilter")?.value || "").trim();
  const statusVal = activeKpiFilter || (document.getElementById("statusFilter")?.value || "").trim();
  const monthVal = (document.getElementById("monthFilter")?.value || "").trim();
  const locVal = (document.getElementById("locationFilter")?.value || "").trim();

  let visibleCount = 0;

  equipmentItems.forEach((item, index) => {
    const st = calculateItemStatus(item);

    // Фильтрация по поисковой строке
    if (searchVal) {
      const combined = `${item.name || ""} ${item.inv_number || ""} ${item.location || ""} ${item.responsible || ""} ${item.protocol_num || ""} ${item.notes || ""}`.toLowerCase();
      if (!combined.includes(searchVal)) return;
    }

    // Фильтрация по категории
    if (catVal && item.category !== catVal) return;

    // Фильтрация по статусу
    if (statusVal) {
      if (statusVal === "repair" && st.status !== "repair") return;
      if (statusVal === "overdue" && st.status !== "overdue") return;
      if (statusVal === "upcoming" && st.status !== "upcoming") return;
      if (statusVal === "ok" && st.status !== "ok") return;
    }

    // Фильтрация по месяцу следующей проверки
    if (monthVal) {
      const nd = parseDate(item.next_test_date);
      if (!nd) return;
      const itemMonth = `${String(nd.getMonth() + 1).padStart(2, "0")}.${nd.getFullYear()}`;
      if (itemMonth !== monthVal) return;
    }

    // Фильтрация по месту нахождения
    if (locVal && (item.location || "").trim() !== locVal) return;

    visibleCount++;
    const row = document.createElement("tr");
    row.dataset.index = index;
    if (st.rowClass) row.classList.add(st.rowClass);
    if (selectedRowIndex === index) row.classList.add("row-selected");

    row.onclick = (e) => onRowClick(index, e);

    const canEdit = window.APP_CONFIG.CAN_EDIT;
    const disabledAttr = canEdit ? "" : "disabled";

    // Формируем HTML колонок таблицы
    row.innerHTML = `
      <td style="text-align: center; color: var(--muted); font-weight: 600;">${visibleCount}</td>
      <td>
        <select class="cell-editable" ${disabledAttr} onchange="updateItemField(${index}, 'category', this.value)">
          ${getCategoriesOptionsHtml(item.category)}
        </select>
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.name)}" 
               placeholder="Наименование..." onchange="updateItemField(${index}, 'name', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.inv_number)}" 
               placeholder="№..." onchange="updateItemField(${index}, 'inv_number', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.location)}" 
               placeholder="Место / цех..." onchange="updateItemField(${index}, 'location', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.responsible)}" 
               placeholder="Ответственный..." onchange="updateItemField(${index}, 'responsible', this.value)">
      </td>
      <td>
        <input type="text" list="testTypesList" class="cell-editable" ${disabledAttr} value="${esc(item.test_type)}" 
               placeholder="Вид испытания..." onchange="updateItemField(${index}, 'test_type', this.value)">
      </td>
      <td>
        <input type="number" min="1" max="120" class="cell-editable cell-center" ${disabledAttr} 
               value="${esc(item.periodicity || '12')}" 
               onchange="onPeriodicityChange(${index}, this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.last_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="onLastDateChange(${index}, this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable cell-center" ${disabledAttr} value="${esc(item.next_test_date)}" 
               placeholder="ДД.ММ.ГГГГ" onchange="updateItemField(${index}, 'next_test_date', this.value)">
      </td>
      <td style="text-align: center;">
        <span class="status-badge ${st.badgeClass}">${st.text}</span>
      </td>
      <td style="text-align: center;">
        <input type="checkbox" class="repair-check" ${disabledAttr} ${item.in_repair ? "checked" : ""} 
               onchange="onRepairChange(${index}, this.checked)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.protocol_num)}" 
               placeholder="№ протокола..." onchange="updateItemField(${index}, 'protocol_num', this.value)">
      </td>
      <td>
        <input type="text" class="cell-editable" ${disabledAttr} value="${esc(item.notes)}" 
               placeholder="Примечание..." onchange="updateItemField(${index}, 'notes', this.value)">
      </td>
      ${canEdit ? `
      <td style="text-align: center;">
        <button type="button" class="row-delete-btn" title="Удалить строку" onclick="deleteRowByIndex(${index}, event)">✕</button>
      </td>` : ""}
    `;

    tbody.appendChild(row);
  });

  document.getElementById("visibleRowCount").textContent = visibleCount;
  document.getElementById("totalRowCount").textContent = equipmentItems.length;

  // Если нет строк — отображаем заглушку
  if (visibleCount === 0) {
    const emptyTr = document.createElement("tr");
    emptyTr.innerHTML = `
      <td colspan="${window.APP_CONFIG.CAN_EDIT ? 15 : 14}" style="text-align: center; padding: 30px; color: var(--muted);">
        Нет записей, соответствующих выбранным критериям фильтрации
      </td>
    `;
    tbody.appendChild(emptyTr);
  }
}

/**
 * Генерация HTML опций для выбора категории
 */
function getCategoriesOptionsHtml(selectedCat) {
  const categories = window.APP_CONFIG.CATEGORIES || [];
  return categories.map(cat => {
    const sel = cat === selectedCat ? "selected" : "";
    return `<option value="${esc(cat)}" ${sel}>${esc(cat)}</option>`;
  }).join("");
}

/**
 * Экранирование спецсимволов HTML
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
    // Не сбиваем фокус инпута
    selectedRowIndex = index;
    return;
  }
  selectedRowIndex = index;
  document.querySelectorAll(".equipment-table tbody tr").forEach(tr => {
    tr.classList.remove("row-selected");
    if (parseInt(tr.dataset.index, 10) === index) {
      tr.classList.add("row-selected");
    }
  });
}

/**
 * Обработка изменения категории через верхние вкладки
 */
function selectCategoryTab(btn, cat) {
  document.querySelectorAll(".tabs .tab").forEach(t => t.classList.remove("active"));
  btn.classList.add("active");

  const catSelect = document.getElementById("categoryFilter");
  if (catSelect) catSelect.value = cat;

  applyFilters();
}

/**
 * Синхронизация верхних вкладок при выборе категории из выпадающего списка
 */
function onCategorySelectChange(cat) {
  document.querySelectorAll(".tabs .tab").forEach(t => {
    if (t.dataset.category === cat) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });
  applyFilters();
}

/**
 * Быстрая фильтрация кликом по KPI карточкам
 */
function filterByKpi(status) {
  document.querySelectorAll(".kpi-card").forEach(c => c.classList.remove("active-kpi"));
  
  if (activeKpiFilter === status) {
    activeKpiFilter = "";
  } else {
    activeKpiFilter = status;
    const cardMap = {
      "": 0, "ok": 1, "upcoming": 2, "overdue": 3, "repair": 4
    };
    const idx = cardMap[status];
    const cards = document.querySelectorAll(".kpi-card");
    if (cards[idx]) cards[idx].classList.add("active-kpi");
  }

  const statusSelect = document.getElementById("statusFilter");
  if (statusSelect) statusSelect.value = activeKpiFilter;

  applyFilters();
}

/**
 * Применение фильтров и перерисовка таблицы
 */
function applyFilters() {
  renderTable();
}

/**
 * Сброс всех фильтров
 */
function resetFilters() {
  document.getElementById("searchFilter").value = "";
  document.getElementById("categoryFilter").value = "";
  document.getElementById("statusFilter").value = "";
  document.getElementById("monthFilter").value = "";
  document.getElementById("locationFilter").value = "";
  activeKpiFilter = "";

  document.querySelectorAll(".kpi-card").forEach(c => c.classList.remove("active-kpi"));
  document.querySelectorAll(".tabs .tab").forEach((t, i) => {
    if (i === 0) t.classList.add("active");
    else t.classList.remove("active");
  });

  renderTable();
}

/**
 * Фиксация состояния в стеке отмены (Undo) перед изменениями
 */
function pushHistory() {
  undoStack.push(JSON.parse(JSON.stringify(equipmentItems)));
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
 * Обновление доступности кнопок ↺ и ↻
 */
function updateUndoRedoButtons() {
  const cancelBtn = document.getElementById("cancelBtn");
  const restoreBtn = document.getElementById("restoreBtn");
  if (cancelBtn) cancelBtn.disabled = undoStack.length === 0;
  if (restoreBtn) restoreBtn.disabled = redoStack.length === 0;
}

/**
 * Отмена последнего действия (Ctrl+Z)
 */
function cancelChanges() {
  if (undoStack.length === 0) return;
  redoStack.push(JSON.parse(JSON.stringify(equipmentItems)));
  equipmentItems = undoStack.pop();
  setUnsavedChanges(true);
  updateUndoRedoButtons();
  renderTable();
  updateKpis();
  showToast("Действие отменено", "info");
}

/**
 * Повтор отмененного действия (Ctrl+Y)
 */
function restoreChanges() {
  if (redoStack.length === 0) return;
  undoStack.push(JSON.parse(JSON.stringify(equipmentItems)));
  equipmentItems = redoStack.pop();
  setUnsavedChanges(true);
  updateUndoRedoButtons();
  renderTable();
  updateKpis();
  showToast("Действие возвращено", "info");
}

/**
 * Обновление значения произвольного поля объекта
 */
function updateItemField(index, field, value) {
  if (!equipmentItems[index]) return;
  if (equipmentItems[index][field] === value) return;

  pushHistory();
  equipmentItems[index][field] = value;
  equipmentItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Автоматический пересчет следующей даты при изменении даты последней проверки
 */
function onLastDateChange(index, newLastDateStr) {
  if (!equipmentItems[index]) return;
  pushHistory();
  equipmentItems[index].last_test_date = newLastDateStr;

  const lastDate = parseDate(newLastDateStr);
  const periodicity = parseInt(equipmentItems[index].periodicity || "12", 10) || 12;

  if (lastDate) {
    const nextDate = addMonths(lastDate, periodicity);
    equipmentItems[index].next_test_date = formatDate(nextDate);
  }
  equipmentItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Автоматический пересчет следующей даты при изменении периодичности
 */
function onPeriodicityChange(index, newPeriodicityStr) {
  if (!equipmentItems[index]) return;
  pushHistory();
  equipmentItems[index].periodicity = newPeriodicityStr;

  const lastDate = parseDate(equipmentItems[index].last_test_date);
  const periodicity = parseInt(newPeriodicityStr || "12", 10) || 12;

  if (lastDate) {
    const nextDate = addMonths(lastDate, periodicity);
    equipmentItems[index].next_test_date = formatDate(nextDate);
  }
  equipmentItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Обработка изменения признака нахождения в ремонте
 */
function onRepairChange(index, isChecked) {
  if (!equipmentItems[index]) return;
  pushHistory();
  equipmentItems[index].in_repair = isChecked ? 1 : 0;
  equipmentItems[index].updated_at = new Date().toLocaleString("ru-RU");

  renderTable();
  updateKpis();
}

/**
 * Добавление новой строки оборудования
 */
function addRow() {
  if (!window.APP_CONFIG.CAN_EDIT) return;
  pushHistory();

  const currentCat = document.getElementById("categoryFilter")?.value || "Домкраты и гидрооборудование";

  const newItem = {
    sort_order: equipmentItems.length + 1,
    category: currentCat,
    name: "",
    inv_number: "",
    location: "Участок РТПС",
    responsible: "",
    test_type: "Техническое освидетельствование (под нагрузкой)",
    periodicity: "12",
    last_test_date: formatDate(serverToday),
    next_test_date: formatDate(addMonths(serverToday, 12)),
    in_repair: 0,
    test_result: "Годен",
    protocol_num: "",
    notes: "",
    updated_at: new Date().toLocaleString("ru-RU"),
  };

  equipmentItems.unshift(newItem);
  selectedRowIndex = 0;

  renderTable();
  updateKpis();
  populateFilterDropdowns();

  showToast("Добавлена новая строка", "info");
}

/**
 * Удаление выбранной строки
 */
function removeSelectedRow() {
  if (!window.APP_CONFIG.CAN_EDIT) return;
  if (selectedRowIndex === null || !equipmentItems[selectedRowIndex]) {
    showToast("Выберите строку для удаления кликом", "info");
    return;
  }
  deleteRowByIndex(selectedRowIndex);
}

/**
 * Удаление строки по индексу
 */
function deleteRowByIndex(index, event) {
  if (event) event.stopPropagation();
  if (!window.APP_CONFIG.CAN_EDIT) return;
  if (!equipmentItems[index]) return;

  const item = equipmentItems[index];
  const name = item.name || item.inv_number || "выбранную единицу";

  if (!confirm(`Удалить оборудование «${name}»?`)) {
    return;
  }

  pushHistory();
  equipmentItems.splice(index, 1);
  selectedRowIndex = null;

  renderTable();
  updateKpis();
  populateFilterDropdowns();

  showToast("Строка удалена", "info");
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
    const payload = { items: equipmentItems };
    const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`Ошибка сохранения: ${res.status}`);
    }

    setUnsavedChanges(false);
    showToast("Все изменения успешно сохранены!", "success");
  } catch (err) {
    console.error("Ошибка при сохранении оборудования:", err);
    showToast("Не удалось сохранить: " + err.message, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Сохранить";
    }
  }
}

/**
 * Копирование выделенных или всех видимых строк в буфер обмена (TSV для Excel)
 */
function copySelectedRows() {
  if (equipmentItems.length === 0) {
    showToast("Нет данных для копирования", "info");
    return;
  }

  const rowsToCopy = (selectedRowIndex !== null && equipmentItems[selectedRowIndex]) 
    ? [equipmentItems[selectedRowIndex]] 
    : equipmentItems;

  const headers = [
    "Категория", "Наименование", "Инв. №", "Место", "Ответственный",
    "Вид проверки", "Периодичность (мес.)", "Дата проверки", "След. дата",
    "В ремонте", "Результат", "№ акта", "Примечание"
  ];

  let tsv = headers.join("\t") + "\n";
  rowsToCopy.forEach(item => {
    tsv += [
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
    ].join("\t") + "\n";
  });

  navigator.clipboard.writeText(tsv).then(() => {
    showToast(`Скопировано в буфер (${rowsToCopy.length} строк). Можно вставить в Excel!`, "success");
  }).catch(() => {
    showToast("Не удалось скопировать в буфер обмена", "error");
  });
}

/**
 * Настройка горячих клавиш: Ctrl+S, Ctrl+Z, Ctrl+Y, Delete
 */
function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Ctrl+S: Сохранение
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveData();
    }
    // Ctrl+Z: Отмена
    else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
      e.preventDefault();
      cancelChanges();
    }
    // Ctrl+Y: Повтор
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
      e.preventDefault();
      restoreChanges();
    }
    // Delete: Удаление выбранной строки, если фокус не в текстовом поле
    else if (e.key === "Delete" && selectedRowIndex !== null) {
      if (e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault();
        removeSelectedRow();
      }
    }
  });
}

/**
 * Предупреждение о несохраненных данных при закрытии страницы
 */
function setupWindowUnloadWarning() {
  window.addEventListener("beforeunload", (e) => {
    if (hasUnsavedChanges) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
}

/**
 * Запрос подтверждения при клике «На главную» при наличии несохраненных изменений
 */
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

/**
 * Всплывающие уведомления (Toast)
 */
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

const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = { locomotives: [], warehouse: [] };
let savedState = null;
let canceledState = null;
let currentTab = "locomotives";
let isDirty = false;
const MIN_LOCOMOTIVES = 5;
const WAREHOUSE_FIELDS = [
  "type",
  "number",
  "verification_date",
  "periodicity",
  "next_verification_date",
  "location",
  "updated_at"
];
let warehouseSelected = null;
let warehouseSelection = null;
let isWarehouseSelecting = false;
let selectionAnchor = null;
let didWarehouseDrag = false;
let warehouseFilters = {
  type: "",
  nextMonth: "",
  location: "",
  number: ""
};

document.addEventListener("DOMContentLoaded", () => {
  loadState();

  // Обработка событий мыши для выделения диапазона ячеек склада как в Excel
  const whBody = document.getElementById("whBody");
  if (whBody) {
    whBody.addEventListener("mousedown", handleWarehouseMouseDown);
    whBody.addEventListener("mouseover", handleWarehouseMouseOver);
  }
  window.addEventListener("mouseup", handleWarehouseMouseUp);

  // Копирование выделенного диапазона ячеек склада по Ctrl+C в формате TSV (как в Excel)
  document.addEventListener("copy", (e) => {
    if (currentTab === "warehouse") {
      const sel = getWarehouseSelection();
      if (sel) {
        const isMulti = sel.startRow !== sel.endRow || sel.startCol !== sel.endCol;
        const textSelected = window.getSelection()?.toString();
        if (isMulti || !textSelected) {
          copyWarehouseSelection(e);
        }
      }
    }
  });

  // Вставка данных в выделенный диапазон склада по Ctrl+V при неактивном текстовом курсоре
  document.addEventListener("paste", (e) => {
    if (currentTab === "warehouse") {
      const sel = getWarehouseSelection();
      if (sel && (!document.activeElement || !document.activeElement.classList.contains("warehouse-cell"))) {
        handleWarehousePaste(e, sel.startRow, sel.startCol);
      }
    }
  });

  // Горячие клавиши для сохранения (Ctrl+S), отмены (Ctrl+Z), возврата (Ctrl+Y / Ctrl+Shift+Z) и выделения всего (Ctrl+A)
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      saveState();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      if (document.activeElement && document.activeElement.tagName === "INPUT") return;
      e.preventDefault();
      cancelChanges();
    } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
      if (document.activeElement && document.activeElement.tagName === "INPUT") return;
      e.preventDefault();
      restoreChanges();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
      if (currentTab === "warehouse") {
        const activeEl = document.activeElement;
        const isEditingInput = activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "SELECT");
        if (!isEditingInput && appState.warehouse.length > 0) {
          e.preventDefault();
          setWarehouseSelection(
            { row: 0, col: 0 },
            { row: appState.warehouse.length - 1, col: WAREHOUSE_FIELDS.length - 1 }
          );
        }
      }
    }
  });

  initUnsavedChangesModal();

  // Предупреждение о несохраненных данных при закрытии страницы
  window.addEventListener("beforeunload", (e) => {
    syncLocomotivesFromDom();
    syncWarehouseFromDom();
    markDirty();
    if (isDirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
});

/* Создание пустых строк для приборов */
function blankDeviceRows(count = 5) {
  return Array.from({ length: Math.max(1, count) }, () => ({ type: "", number: "" }));
}

/* Нормализация строки локомотива */
function normalizeLocRow(row) {
  const devices = Array.isArray(row?.devices)
    ? row.devices.map((device) => ({
        type: String(device?.type ?? ""),
        number: String(device?.number ?? "")
      }))
    : [];
  return {
    series: String(row?.series ?? ""),
    number: String(row?.number ?? ""),
    inventory_num: String(row?.inventory_num ?? ""),
    note: String(row?.note ?? ""),
    devices: devices.length ? devices : blankDeviceRows()
  };
}

/* Нормализация строки склада */
function normalizeWhRow(row) {
  return {
    type: String(row?.type ?? ""),
    number: String(row?.number ?? ""),
    verification_date: String(row?.verification_date ?? ""),
    periodicity: String(row?.periodicity ?? ""),
    next_verification_date: String(row?.next_verification_date ?? ""),
    location: String(row?.location ?? ""),
    updated_at: String(row?.updated_at ?? "")
  };
}

/* Нормализация номера прибора: получение формы без ведущих нулей для надёжного сопоставления */
function cleanDeviceNumber(num) {
  const s = String(num ?? "").trim();
  const unpadded = s.replace(/^0+/, "");
  return unpadded || s;
}

/* Построение быстрого индекса приборов локомотивов для O(1) поиска местонахождения */
function buildLocoDeviceIndex() {
  const index = new Map();
  for (const loco of appState.locomotives) {
    const locoNum = String(loco?.number ?? "").trim();
    if (!locoNum) continue;
    const devices = Array.isArray(loco?.devices) ? loco.devices : [];
    for (const dev of devices) {
      const dType = String(dev?.type ?? "").trim().toLowerCase();
      const dNum = String(dev?.number ?? "").trim().toLowerCase();
      if (dNum) {
        const cNum = cleanDeviceNumber(dNum).toLowerCase();
        if (dType) {
          index.set(`${dType}::${dNum}`, locoNum);
          index.set(`${dType}::${cNum}`, locoNum);
        }
        if (!index.has(`*::${dNum}`)) index.set(`*::${dNum}`, locoNum);
        if (!index.has(`*::${cNum}`)) index.set(`*::${cNum}`, locoNum);
      }
    }
  }
  return index;
}

/* Пересчет местонахождения всех приборов на складе за один проход O(N+M) */
function recalcWarehouseLocations() {
  const index = buildLocoDeviceIndex();
  for (const row of appState.warehouse) {
    const rType = String(row?.type ?? "").trim().toLowerCase();
    const rNum = String(row?.number ?? "").trim().toLowerCase();
    let location = "Депо";
    if (rNum) {
      const cNum = cleanDeviceNumber(rNum).toLowerCase();
      location = index.get(`${rType}::${rNum}`) || index.get(`${rType}::${cNum}`) || index.get(`*::${rNum}`) || index.get(`*::${cNum}`) || "Депо";
    }
    row.location = location;
  }
}

/* Сбор всех вариантов фильтров и опций приборов за один проход */
function getWarehouseOptionsData() {
  const typesSet = new Set();
  const locsSet = new Set();
  const nextMonthMap = new Map();
  const numbersByType = new Map();
  const allNumbers = new Set();

  for (const row of appState.warehouse) {
    const type = String(row?.type ?? "").trim();
    const loc = String(row?.location ?? "").trim();
    const num = String(row?.number ?? "").trim();
    const nextDate = String(row?.next_verification_date ?? "").trim();

    if (type) typesSet.add(type);
    if (loc) locsSet.add(loc);

    if (num) {
      allNumbers.add(num);
      const lowerType = type.toLowerCase();
      if (!numbersByType.has(lowerType)) numbersByType.set(lowerType, new Set());
      numbersByType.get(lowerType).add(num);
    }

    if (nextDate) {
      const parsed = parseDateDMY(nextDate);
      if (parsed) {
        const key = `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}`;
        if (!nextMonthMap.has(key)) {
          const raw = parsed.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
          nextMonthMap.set(key, raw.charAt(0).toUpperCase() + raw.slice(1));
        }
      }
    }
  }

  const nextMonthOptions = Array.from(nextMonthMap.entries())
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.value.localeCompare(b.value));

  return {
    types: Array.from(typesSet),
    locations: Array.from(locsSet),
    nextMonths: nextMonthOptions,
    numbersByType,
    allNumbers: Array.from(allNumbers)
  };
}

/* Получение номеров приборов по выбранному типу без перебора всего массива */
function getWarehouseNumberOptions(optionsData, type, currentNumber = "") {
  const normType = String(type ?? "").trim().toLowerCase();
  const set = normType ? optionsData.numbersByType.get(normType) : null;
  const list = set ? Array.from(set) : optionsData.allNumbers;
  const current = String(currentNumber ?? "").trim();
  if (current && !list.includes(current)) {
    const cCurr = cleanDeviceNumber(current);
    const hasEquivalent = list.some((item) => cleanDeviceNumber(item) === cCurr);
    if (!hasEquivalent) {
      return [current, ...list];
    }
  }
  return list;
}

function normalizeWarehouseFilters() {
  warehouseFilters = {
    type: String(warehouseFilters?.type ?? ""),
    nextMonth: String(warehouseFilters?.nextMonth ?? ""),
    location: String(warehouseFilters?.location ?? ""),
    number: String(warehouseFilters?.number ?? "")
  };
}

function formatMonthKey(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/* Проверка соответствия строки склада установленным фильтрам */
function warehouseRowMatchesFilters(row) {
  const typeValue = String(row?.type ?? "").trim().toLowerCase();
  const nextValue = String(row?.next_verification_date ?? "").trim();
  const locationValue = String(row?.location ?? "").trim().toLowerCase();
  const numberValue = String(row?.number ?? "").trim().toLowerCase();
  const filterType = String(warehouseFilters.type ?? "").trim().toLowerCase();
  const filterLocation = String(warehouseFilters.location ?? "").trim().toLowerCase();
  const filterNumber = String(warehouseFilters.number ?? "").trim().toLowerCase();

  if (filterNumber) {
    const cleanFilter = cleanDeviceNumber(filterNumber).toLowerCase();
    const cleanNum = cleanDeviceNumber(numberValue).toLowerCase();
    if (!numberValue.includes(filterNumber) && !cleanNum.includes(cleanFilter)) {
      return false;
    }
  }
  if (filterType && typeValue !== filterType) return false;
  if (filterLocation && locationValue !== filterLocation) return false;
  if (warehouseFilters.nextMonth) {
    const parsed = parseDateDMY(nextValue);
    if (!parsed || formatMonthKey(parsed) !== warehouseFilters.nextMonth) return false;
  }
  return true;
}

function syncWarehouseFilterDom() {
  const typeFilter = document.getElementById("warehouseTypeFilter");
  const nextDateFilter = document.getElementById("warehouseNextMonthFilter");
  const locationFilter = document.getElementById("warehouseLocationFilter");
  const numberFilter = document.getElementById("warehouseNumberFilter");
  if (typeFilter) typeFilter.value = warehouseFilters.type;
  if (nextDateFilter) nextDateFilter.value = warehouseFilters.nextMonth;
  if (locationFilter) locationFilter.value = warehouseFilters.location;
  if (numberFilter) numberFilter.value = warehouseFilters.number;
}

/* Применение фильтров склада без полной перерисовки DOM (быстро и без потери фокуса) */
function applyWarehouseFilters() {
  const rows = document.querySelectorAll("#whBody tr[data-warehouse-row]");
  let visibleCount = 0;
  rows.forEach((rowEl) => {
    const row = {
      type: rowEl.dataset.warehouseType || "",
      next_verification_date: rowEl.dataset.warehouseNext || "",
      location: rowEl.dataset.warehouseLocation || "",
      number: rowEl.dataset.warehouseNumber || ""
    };
    const visible = warehouseRowMatchesFilters(row);
    rowEl.style.display = visible ? "" : "none";
    if (visible) visibleCount += 1;
  });
  const emptyRow = document.getElementById("whEmptyStateRow");
  if (emptyRow) emptyRow.style.display = visibleCount > 0 ? "none" : "";
}

/* Установка значения фильтра и мгновенная фильтрация без перерисовки всего DOM */
function setWarehouseFilter(field, value) {
  warehouseFilters[field] = String(value ?? "");
  normalizeWarehouseFilters();
  applyWarehouseFilters();
}

/* Сброс всех фильтров склада */
function clearWarehouseFilters() {
  warehouseFilters = { type: "", nextMonth: "", location: "", number: "" };
  syncWarehouseFilterDom();
  applyWarehouseFilters();
}

function ensureMinLocomotives(rows, minCount = MIN_LOCOMOTIVES) {
  const normalized = Array.isArray(rows) ? rows.slice() : [];
  while (normalized.length < minCount) {
    normalized.push(blankLoc());
  }
  return normalized;
}

function setTab(tab) {
  syncLocomotivesFromDom();
  syncWarehouseFromDom();
  currentTab = tab;
  if (tab !== "warehouse") {
    clearWarehouseSelection();
  }
  document.getElementById("tabLoc").classList.toggle("active", tab === "locomotives");
  document.getElementById("tabWh").classList.toggle("active", tab === "warehouse");
  document.getElementById("tab-locomotives").classList.toggle("active", tab === "locomotives");
  document.getElementById("tab-warehouse").classList.toggle("active", tab === "warehouse");
  syncWarehouseFilterDom();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[m]));
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      message = data.error || message;
    } catch {}
    throw new Error(message);
  }
  return res.json();
}

/* Загрузка состояния с бэкенда */
async function loadState() {
  try {
    const data = await requestJson(`${APP_PREFIX}/api/state`);
    appState = {
      locomotives: ensureMinLocomotives(Array.isArray(data.locomotives) ? data.locomotives.map(normalizeLocRow) : []),
      warehouse: Array.isArray(data.warehouse) ? data.warehouse.map(normalizeWhRow) : []
    };
    if (!appState.warehouse.length) appState.warehouse.push(blankWh());
    appState.warehouse.forEach((row) => recalcWarehouseNextDate(row));
    recalcWarehouseLocations();
    normalizeWarehouseFilters();
    savedState = cloneState(appState);
    canceledState = null;
    render();
    markDirty(false);
    updateHistoryButtons();
  } catch (err) {
    console.error(err);
    alert("Ошибка загрузки модуля АЛСН: " + err.message);
  }
}

function blankLoc() {
  return { series: "", number: "", inventory_num: "", note: "", devices: blankDeviceRows() };
}

function blankWh() {
  return {
    type: "",
    number: "",
    verification_date: "",
    periodicity: "",
    next_verification_date: "",
    location: "",
    updated_at: ""
  };
}

/* Проверка, изменились ли данные прибора в строке склада по сравнению с сохранённым состоянием */
function isWarehouseRowChanged(currentRow, savedRow) {
  if (!savedRow) {
    // Новая строка: считается изменённой при наличии любых заполненных данных прибора
    return !!(
      String(currentRow?.type ?? "").trim() ||
      String(currentRow?.number ?? "").trim() ||
      String(currentRow?.verification_date ?? "").trim() ||
      String(currentRow?.periodicity ?? "").trim() ||
      String(currentRow?.next_verification_date ?? "").trim()
    );
  }
  return (
    String(currentRow?.type ?? "").trim() !== String(savedRow?.type ?? "").trim() ||
    String(currentRow?.number ?? "").trim() !== String(savedRow?.number ?? "").trim() ||
    String(currentRow?.verification_date ?? "").trim() !== String(savedRow?.verification_date ?? "").trim() ||
    String(currentRow?.periodicity ?? "").trim() !== String(savedRow?.periodicity ?? "").trim() ||
    String(currentRow?.next_verification_date ?? "").trim() !== String(savedRow?.next_verification_date ?? "").trim()
  );
}

function parseDateDMY(value) {
  const text = String(value ?? "").trim();
  const match = text.match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!match) return null;
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  const date = new Date(year, month - 1, day);
  if (
    Number.isNaN(date.getTime()) ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }
  return date;
}

function formatDateDMY(date) {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear());
  return `${day}.${month}.${year}`;
}

function addMonthsToDate(date, months) {
  const base = new Date(date.getTime());
  const targetMonth = base.getMonth() + months;
  const targetYear = base.getFullYear() + Math.floor(targetMonth / 12);
  const normalizedMonth = ((targetMonth % 12) + 12) % 12;
  const lastDay = new Date(targetYear, normalizedMonth + 1, 0).getDate();
  return new Date(targetYear, normalizedMonth, Math.min(base.getDate(), lastDay));
}

function recalcWarehouseNextDate(row) {
  if (!row) return "";
  const baseDate = parseDateDMY(row.verification_date);
  const periodicity = Number.parseInt(String(row.periodicity ?? "").trim(), 10);
  if (!baseDate || !Number.isFinite(periodicity) || periodicity <= 0) {
    row.next_verification_date = "";
    return "";
  }
  const nextDate = addMonthsToDate(baseDate, periodicity);
  row.next_verification_date = formatDateDMY(nextDate);
  return row.next_verification_date;
}

function warehouseCellText(rowIdx, colIdx) {
  const row = appState.warehouse[rowIdx];
  if (!row) return "";
  const field = WAREHOUSE_FIELDS[colIdx];
  if (!field) return "";
  if (field === "location") return row.location || "Депо";
  return String(row[field] ?? "");
}

function setWarehouseCellValue(rowIdx, colIdx, value) {
  const row = appState.warehouse[rowIdx];
  const field = WAREHOUSE_FIELDS[colIdx];
  if (!row || !field) return;
  row[field] = String(value ?? "");
}

/* Получение информации о ячейке склада (строка и колонка) по DOM-элементу */
function getWarehouseCellInfo(target) {
  const cell = target?.closest?.("#whBody td");
  if (!cell) return null;
  const row = Number(cell.dataset.row);
  const col = Number(cell.dataset.col);
  if (!Number.isFinite(row) || !Number.isFinite(col)) return null;
  return { cell, row, col };
}

/* Вычисление прямоугольных границ диапазона выделения */
function warehouseSelectionBounds(a, b) {
  return {
    startRow: Math.min(a.row, b.row),
    endRow: Math.max(a.row, b.row),
    startCol: Math.min(a.col, b.col),
    endCol: Math.max(a.col, b.col)
  };
}

/* Установка выделенного диапазона ячеек склада как в Excel */
function setWarehouseSelection(anchor, focus) {
  if (!anchor || !focus) return;
  const totalRows = appState.warehouse.length;
  if (!totalRows) return;
  const totalCols = WAREHOUSE_FIELDS.length;

  const boundedAnchor = {
    row: Math.max(0, Math.min(totalRows - 1, anchor.row)),
    col: Math.max(0, Math.min(totalCols - 1, anchor.col))
  };
  const boundedFocus = {
    row: Math.max(0, Math.min(totalRows - 1, focus.row)),
    col: Math.max(0, Math.min(totalCols - 1, focus.col))
  };

  const bounds = warehouseSelectionBounds(boundedAnchor, boundedFocus);
  warehouseSelection = {
    anchor: boundedAnchor,
    focus: boundedFocus,
    ...bounds
  };
  warehouseSelected = { row: boundedFocus.row, col: boundedFocus.col };
  applyWarehouseSelectionClasses();
}

/* Очистка выделения ячеек склада */
function clearWarehouseSelection() {
  warehouseSelection = null;
  warehouseSelected = null;
  applyWarehouseSelectionClasses();
}

/* Получение активного диапазона выделения склада */
function getWarehouseSelection() {
  if (warehouseSelection) return warehouseSelection;
  if (warehouseSelected) {
    return {
      startRow: warehouseSelected.row,
      endRow: warehouseSelected.row,
      startCol: warehouseSelected.col,
      endCol: warehouseSelected.col,
      anchor: warehouseSelected,
      focus: warehouseSelected
    };
  }
  return null;
}

/* Применение CSS-классов и контурной рамки выделения в стиле Excel */
function applyWarehouseSelectionClasses() {
  document.querySelectorAll("#whBody td.selected-range, #whBody td.selected").forEach((cell) => {
    cell.classList.remove("selected-range", "selected");
    cell.style.removeProperty("box-shadow");
  });

  const sel = getWarehouseSelection();
  if (!sel || currentTab !== "warehouse") return;

  const rowEls = document.querySelectorAll("#whBody tr[data-warehouse-row]");
  for (let r = sel.startRow; r <= sel.endRow; r++) {
    const rowEl = rowEls[r];
    if (!rowEl) continue;
    const cells = rowEl.querySelectorAll("td");
    for (let c = sel.startCol; c <= sel.endCol; c++) {
      const cell = cells[c];
      if (!cell) continue;

      cell.classList.add("selected-range");
      if (r === sel.focus.row && c === sel.focus.col) {
        cell.classList.add("selected");
      }

      // Отрисовка контурной внешней рамки диапазона как в Excel
      const shadows = [];
      if (r === sel.startRow) shadows.push("inset 0 1.5px 0 0 #276ef1");
      if (r === sel.endRow) shadows.push("inset 0 -1.5px 0 0 #276ef1");
      if (c === sel.startCol) shadows.push("inset 1.5px 0 0 0 #276ef1");
      if (c === sel.endCol) shadows.push("inset -1.5px 0 0 0 #276ef1");

      if (shadows.length > 0) {
        cell.style.setProperty("box-shadow", shadows.join(", "), "important");
      } else {
        cell.style.boxShadow = "";
      }
    }
  }
}

/* Копирование выделенных приборов/ячеек склада в буфер обмена в формате TSV (как в Excel) */
function copyWarehouseSelection(event) {
  const sel = getWarehouseSelection();
  if (!sel || currentTab !== "warehouse") return;

  const lines = [];
  for (let r = sel.startRow; r <= sel.endRow; r++) {
    const rowValues = [];
    for (let c = sel.startCol; c <= sel.endCol; c++) {
      rowValues.push(warehouseCellText(r, c));
    }
    lines.push(rowValues.join("\t"));
  }
  const tsvText = lines.join("\n");
  if (!tsvText) return;

  if (event?.clipboardData) {
    event.clipboardData.setData("text/plain", tsvText);
    event.preventDefault();
  } else if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(tsvText);
  }
}

/* Очистка значений в выделенном диапазоне ячеек при нажатии Delete / Backspace */
function clearWarehouseSelectionValues() {
  if (!CAN_EDIT) return false;
  const sel = getWarehouseSelection();
  if (!sel) return false;

  let changed = false;
  for (let r = sel.startRow; r <= sel.endRow; r++) {
    const row = appState.warehouse[r];
    if (!row) continue;
    for (let c = sel.startCol; c <= sel.endCol; c++) {
      if (c >= 5) continue; // Не затираем автоматически вычисляемые поля
      setWarehouseCellValue(r, c, "");
      const cellEl = document.querySelector(`.warehouse-cell[data-row="${r}"][data-col="${c}"]`);
      if (cellEl) cellEl.innerText = "";
      changed = true;
    }
    recalcWarehouseNextDate(row);
    const nextCell = document.querySelector(`.warehouse-cell[data-row="${r}"][data-col="4"]`);
    if (nextCell) nextCell.innerText = row.next_verification_date || "";
  }
  if (changed) {
    recalcWarehouseLocations();
    for (let r = sel.startRow; r <= sel.endRow; r++) {
      const locCell = document.querySelector(`.warehouse-auto[data-row="${r}"][data-col="5"] .warehouse-auto-value`);
      if (locCell) locCell.innerText = appState.warehouse[r]?.location || "Депо";
    }
    applyWarehouseSelectionClasses();
    markDirty(true);
  }
  return changed;
}

/* Обработка нажатия мыши по ячейке склада */
function handleWarehouseMouseDown(e) {
  if (e.button !== 0) return;
  const info = getWarehouseCellInfo(e.target);
  if (!info) return;

  if (e.shiftKey && warehouseSelection?.anchor) {
    didWarehouseDrag = true;
    setWarehouseSelection(warehouseSelection.anchor, { row: info.row, col: info.col });
    e.preventDefault();
    return;
  }

  isWarehouseSelecting = true;
  didWarehouseDrag = false;
  selectionAnchor = { row: info.row, col: info.col };
  setWarehouseSelection(selectionAnchor, { row: info.row, col: info.col });

  if (info.col >= 5) {
    e.preventDefault();
  }
}

/* Обработка перемещения мыши с зажатой кнопкой для протягивания выделения */
function handleWarehouseMouseOver(e) {
  if (!isWarehouseSelecting) return;
  if (e.buttons !== 1) {
    isWarehouseSelecting = false;
    return;
  }
  const info = getWarehouseCellInfo(e.target);
  if (!info || !selectionAnchor) return;

  if (info.row !== selectionAnchor.row || info.col !== selectionAnchor.col) {
    didWarehouseDrag = true;
    window.getSelection()?.removeAllRanges();
    if (document.activeElement && document.activeElement.isContentEditable) {
      document.activeElement.blur();
    }
  }

  setWarehouseSelection(selectionAnchor, { row: info.row, col: info.col });
}

/* Завершение протягивания выделения мыши */
function handleWarehouseMouseUp(e) {
  if (!isWarehouseSelecting) return;
  isWarehouseSelecting = false;

  const sel = getWarehouseSelection();
  if (sel && sel.startRow === sel.endRow && sel.startCol === sel.endCol && !didWarehouseDrag) {
    if (sel.startCol < 5 && CAN_EDIT) {
      const cell = document.querySelector(`.warehouse-cell[data-row="${sel.startRow}"][data-col="${sel.startCol}"]`);
      if (cell && document.activeElement !== cell) {
        cell.focus();
      }
    }
  }
}

function selectWarehouseCell(rowIdx, colIdx) {
  setWarehouseSelection({ row: rowIdx, col: colIdx }, { row: rowIdx, col: colIdx });
}

function focusWarehouseCell(rowIdx, colIdx, selectText = false) {
  const cell = document.querySelector(`.warehouse-cell[data-row="${rowIdx}"][data-col="${colIdx}"]`);
  if (!cell) return;
  cell.focus();
  selectWarehouseCell(rowIdx, colIdx);
  if (selectText && typeof document.createRange === "function") {
    const range = document.createRange();
    range.selectNodeContents(cell);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
}

function parsePasteMatrix(text) {
  return String(text ?? "")
    .replace(/\r/g, "")
    .split("\n")
    .filter((line, idx, arr) => !(idx === arr.length - 1 && line === ""))
    .map((line) => line.split("\t"));
}

/* Синхронизация данных локомотивов из DOM в память appState */
function syncLocomotivesFromDom() {
  document.querySelectorAll(".loc-series[data-loc-idx]").forEach((el) => {
    const idx = Number(el.dataset.locIdx);
    if (appState.locomotives && appState.locomotives[idx]) {
      const val = el.innerText.trim();
      appState.locomotives[idx].series = val === "Локомотив" ? "" : val;
    }
  });
  document.querySelectorAll(".loc-number[data-loc-idx]").forEach((el) => {
    const idx = Number(el.dataset.locIdx);
    if (appState.locomotives && appState.locomotives[idx]) {
      appState.locomotives[idx].number = el.innerText.trim();
    }
  });
}

/* Синхронизация данных склада из DOM в память appState */
function syncWarehouseFromDom() {
  document.querySelectorAll(".warehouse-cell").forEach((cell) => {
    const rowIdx = Number(cell.dataset.row);
    const colIdx = Number(cell.dataset.col);
    if (Number.isFinite(rowIdx) && Number.isFinite(colIdx)) {
      setWarehouseCellValue(rowIdx, colIdx, cell.innerText.trim());
    }
  });
  appState.warehouse.forEach((row) => recalcWarehouseNextDate(row));
}

function getRows() {
  return currentTab === "locomotives" ? appState.locomotives : appState.warehouse;
}

function addRow() {
  if (!CAN_EDIT) return;
  syncLocomotivesFromDom();
  syncWarehouseFromDom();
  const rows = getRows();
  rows.push(currentTab === "locomotives" ? blankLoc() : blankWh());
  recalcWarehouseLocations();
  render();
  markDirty(true);
}

function removeRow() {
  if (!CAN_EDIT) return;
  syncLocomotivesFromDom();
  syncWarehouseFromDom();
  const rows = getRows();
  if (currentTab === "locomotives" && rows.length <= MIN_LOCOMOTIVES) return;
  if (currentTab === "warehouse" && rows.length <= 1) return;
  rows.pop();
  recalcWarehouseLocations();
  render();
  markDirty(true);
}

function editCell(tab, rowIdx, field, el) {
  const rows = tab === "locomotives" ? appState.locomotives : appState.warehouse;
  if (!rows[rowIdx]) return;
  let val = el.innerText.trim();
  if (tab === "locomotives" && field === "series" && val === "Локомотив") {
    val = "";
  }
  rows[rowIdx][field] = val;
  if (tab === "locomotives" && field === "number") {
    recalcWarehouseLocations();
  }
  markDirty(true);
}

function editDeviceSelect(rowIdx, deviceIdx, field, value) {
  syncLocomotivesFromDom();
  const row = appState.locomotives[rowIdx];
  if (!row) return;
  if (!Array.isArray(row.devices)) row.devices = blankDeviceRows();
  if (!row.devices[deviceIdx]) row.devices[deviceIdx] = { type: "", number: "" };
  row.devices[deviceIdx][field] = String(value ?? "");
  if (field === "type") {
    const optionsData = getWarehouseOptionsData();
    const allowedNumbers = getWarehouseNumberOptions(optionsData, row.devices[deviceIdx].type);
    const currentNumber = String(row.devices[deviceIdx].number ?? "").trim();
    const cCurr = cleanDeviceNumber(currentNumber);
    const isAllowed = allowedNumbers.includes(currentNumber) || allowedNumbers.some((item) => cleanDeviceNumber(item) === cCurr);
    if (currentNumber && !isAllowed) {
      row.devices[deviceIdx].number = "";
    }
  }
  recalcWarehouseLocations();
  if (field === "type") {
    render();
  }
  markDirty(true);
}

function editWarehouseCell(rowIdx, colIdx, el) {
  const val = el.innerText.trim();
  setWarehouseCellValue(rowIdx, colIdx, val);

  const rowEl = el.closest("tr");
  if (rowEl) {
    if (colIdx === 0) rowEl.dataset.warehouseType = val;
    if (colIdx === 1) rowEl.dataset.warehouseNumber = val;
    if (colIdx === 4) rowEl.dataset.warehouseNext = val;
  }

  if (colIdx === 2 || colIdx === 3) {
    const nextValue = recalcWarehouseNextDate(appState.warehouse[rowIdx]);
    const nextCell = document.querySelector(`.warehouse-cell[data-row="${rowIdx}"][data-col="4"]`);
    if (nextCell && document.activeElement !== nextCell) {
      nextCell.innerText = nextValue;
    }
    if (rowEl) rowEl.dataset.warehouseNext = nextValue;
  }
  if (colIdx === 0 || colIdx === 1) {
    recalcWarehouseLocations();
    // Обновляем отображение ячейки местонахождения для текущей строки
    const locCell = rowEl ? rowEl.querySelector(".warehouse-auto-value") : null;
    if (locCell) locCell.innerText = appState.warehouse[rowIdx].location || "Депо";
  }
  markDirty(true);
}

function handleWarehouseFocus(rowIdx, colIdx, el) {
  selectWarehouseCell(rowIdx, colIdx);
  if (!el.innerText.trim() && el.innerText !== "") {
    el.innerText = "";
  }
}

function handleWarehouseClick(rowIdx, colIdx) {
  if (didWarehouseDrag) return;
  selectWarehouseCell(rowIdx, colIdx);
}

function handleWarehouseKeydown(event, rowIdx, colIdx) {
  if (!CAN_EDIT) return;

  const key = event.key;
  const sel = getWarehouseSelection();

  // Очистка выделенного диапазона при нажатии Delete или Backspace
  if (key === "Delete" || key === "Backspace") {
    if (sel && (sel.endRow > sel.startRow || sel.endCol > sel.startCol)) {
      event.preventDefault();
      clearWarehouseSelectionValues();
      return;
    }
    // Очистка одиночной ячейки
    event.preventDefault();
    const cell = event.currentTarget;
    cell.innerText = "";
    setWarehouseCellValue(rowIdx, colIdx, "");
    const rowEl = cell.closest("tr");
    if (rowEl) {
      if (colIdx === 0) rowEl.dataset.warehouseType = "";
      if (colIdx === 1) rowEl.dataset.warehouseNumber = "";
      if (colIdx === 4) rowEl.dataset.warehouseNext = "";
    }
    if (colIdx === 2 || colIdx === 3) {
      recalcWarehouseNextDate(appState.warehouse[rowIdx]);
      const nextCell = document.querySelector(`.warehouse-cell[data-row="${rowIdx}"][data-col="4"]`);
      if (nextCell) nextCell.innerText = "";
    }
    if (colIdx === 0 || colIdx === 1) {
      recalcWarehouseLocations();
      const locCell = cell.closest("tr")?.querySelector(".warehouse-auto-value");
      if (locCell) locCell.innerText = appState.warehouse[rowIdx].location || "Депо";
    }
    markDirty(true);
    return;
  }

  // Расширение диапазона выделения с зажатым Shift (стрелки клавиатуры как в Excel)
  if (event.shiftKey && (key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft" || key === "ArrowRight")) {
    event.preventDefault();
    const anchor = sel?.anchor || { row: rowIdx, col: colIdx };
    const focus = { ...(sel?.focus || { row: rowIdx, col: colIdx }) };
    if (key === "ArrowUp") focus.row = Math.max(0, focus.row - 1);
    else if (key === "ArrowDown") focus.row = Math.min(appState.warehouse.length - 1, focus.row + 1);
    else if (key === "ArrowLeft") focus.col = Math.max(0, focus.col - 1);
    else if (key === "ArrowRight") focus.col = Math.min(WAREHOUSE_FIELDS.length - 1, focus.col + 1);
    setWarehouseSelection(anchor, focus);
    return;
  }

  let targetRow = rowIdx;
  let targetCol = colIdx;
  if (key === "ArrowLeft") targetCol -= 1;
  else if (key === "ArrowRight" || key === "Tab") {
    event.preventDefault();
    targetCol += 1;
    if (targetCol >= 5) {
      targetCol = 0;
      targetRow += 1;
    }
  } else if (key === "ArrowUp") targetRow -= 1;
  else if (key === "ArrowDown" || key === "Enter") {
    event.preventDefault();
    targetRow += 1;
  } else {
    return;
  }

  event.preventDefault();
  if (targetRow < 0 || targetCol < 0) return;
  if (targetRow >= appState.warehouse.length) return;
  if (targetCol >= 5) return;
  focusWarehouseCell(targetRow, targetCol, true);
}

function handleWarehouseCopy(event, rowIdx, colIdx) {
  const sel = getWarehouseSelection();
  if (sel && (sel.endRow > sel.startRow || sel.endCol > sel.startCol)) {
    copyWarehouseSelection(event);
    return;
  }
  const text = warehouseCellText(rowIdx, colIdx);
  if (!text) return;
  event.clipboardData?.setData("text/plain", text);
  event.preventDefault();
}

function handleWarehousePaste(event, rowIdx, colIdx) {
  if (!CAN_EDIT) return;
  event.preventDefault();
  syncLocomotivesFromDom();
  syncWarehouseFromDom();

  let matrix = [];
  // Сначала пробуем получить форматированную HTML-таблицу (из Excel / веб-страниц),
  // где номера с ведущими нулями (например '0123') не обрезаются до чисел
  const html = event.clipboardData?.getData("text/html");
  if (html && (html.includes("<table") || html.includes("<tr") || html.includes("<td"))) {
    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const trs = Array.from(doc.querySelectorAll("tr"));
      if (trs.length) {
        matrix = trs.map((tr) =>
          Array.from(tr.querySelectorAll("td, th")).map((td) => td.innerText.replace(/\u00a0/g, " ").trim())
        ).filter((row) => row.length && row.some((c) => c !== ""));
      }
    } catch (e) {
      console.warn("HTML paste fallback:", e);
    }
  }

  // Если HTML не найден, используем стандартный текстовый буфер обмена
  if (!matrix.length) {
    const text = event.clipboardData?.getData("text/plain") || "";
    matrix = parsePasteMatrix(text);
  }
  if (!matrix.length) return;

  const sel = getWarehouseSelection();
  const startRow = sel ? sel.startRow : rowIdx;
  const startCol = sel ? sel.startCol : colIdx;

  // Если в буфере одна ячейка, а в таблице выделен диапазон из нескольких — заполняем все выделенные ячейки (как в Excel)
  const fillSingle = matrix.length === 1 && matrix[0].length === 1 && sel && (sel.endRow > sel.startRow || sel.endCol > sel.startCol);
  const targetRowCount = fillSingle ? (sel.endRow - sel.startRow + 1) : matrix.length;
  const targetColCount = fillSingle ? (sel.endCol - sel.startCol + 1) : Math.max(...matrix.map((row) => row.length));

  for (let r = 0; r < targetRowCount; r += 1) {
    const targetRowIdx = startRow + r;
    while (targetRowIdx >= appState.warehouse.length) {
      appState.warehouse.push(blankWh());
    }
    const targetRow = appState.warehouse[targetRowIdx];
    if (!targetRow) break;

    const sourceRow = fillSingle ? matrix[0] : matrix[Math.min(r, matrix.length - 1)];
    for (let c = 0; c < targetColCount; c += 1) {
      const targetColIdx = startCol + c;
      if (targetColIdx >= 5) break; // Автоматические колонки (местонахождение и дата изменения) не перезаписываются при вставке
      const val = fillSingle ? sourceRow[0] : (sourceRow[c] ?? "");
      setWarehouseCellValue(targetRowIdx, targetColIdx, String(val).trim());
    }
    recalcWarehouseNextDate(targetRow);
  }
  recalcWarehouseLocations();
  render();
  markDirty(true);

  // Устанавливаем выделение на вставленный диапазон ячеек
  const newFocusRow = Math.min(startRow + targetRowCount - 1, appState.warehouse.length - 1);
  const newFocusCol = Math.min(startCol + targetColCount - 1, 4);
  setWarehouseSelection({ row: startRow, col: startCol }, { row: newFocusRow, col: newFocusCol });
}

/* Отрисовка интерфейса локомотивов и склада */
function render() {
  const locBody = document.getElementById("locBody");
  const whBody = document.getElementById("whBody");
  const optionsData = getWarehouseOptionsData();

  normalizeWarehouseFilters();
  syncWarehouseFilterDom();

  locBody.innerHTML = appState.locomotives.map((row, idx) => {
    const deviceRows = (row.devices && row.devices.length ? row.devices : blankDeviceRows()).map((device, deviceIdx) => {
      const numberOptions = getWarehouseNumberOptions(optionsData, device.type, device.number);
      const availableTypes = Array.from(new Set([...(device.type ? [String(device.type).trim()] : []), ...optionsData.types]));
      const devNumStr = String(device.number ?? "").trim();
      const devNumClean = cleanDeviceNumber(devNumStr);
      return `
      <tr>
        <td>
          <select class="device-select" ${CAN_EDIT ? `onchange="editDeviceSelect(${idx}, ${deviceIdx}, 'type', this.value)"` : 'disabled'}>
            <option value=""></option>
            ${availableTypes
              .map((option) => `<option value="${escapeHtml(option)}"${String(device.type ?? "") === option ? " selected" : ""}>${escapeHtml(option)}</option>`)
              .join("")}
          </select>
        </td>
        <td>
          <select class="device-select" ${CAN_EDIT ? `onchange="editDeviceSelect(${idx}, ${deviceIdx}, 'number', this.value)"` : 'disabled'}>
            <option value=""></option>
            ${numberOptions
              .map((option) => {
                const optStr = String(option ?? "").trim();
                const isSelected = devNumStr === optStr || (devNumClean && cleanDeviceNumber(optStr) === devNumClean);
                return `<option value="${escapeHtml(option)}"${isSelected ? " selected" : ""}>${escapeHtml(option)}</option>`;
              })
              .join("")}
          </select>
        </td>
      </tr>
      `;
    }).join("");

    return `
      <article class="loc-card">
        <div class="loc-card-title">
          <span class="editable loc-series" data-loc-idx="${idx}" style="display:inline-block; min-width:120px;" ${CAN_EDIT ? `contenteditable="true" onfocus="if(this.innerText.trim()==='Локомотив')this.innerText='';" oninput="editCell('locomotives', ${idx}, 'series', this)" onblur="if(!this.innerText.trim())this.innerText='Локомотив'; editCell('locomotives', ${idx}, 'series', this)"` : ''}>${escapeHtml(row.series || "Локомотив")}</span>
          <span> № </span>
          <span class="editable loc-number" data-loc-idx="${idx}" style="display:inline-block; min-width:70px;" ${CAN_EDIT ? `contenteditable="true" oninput="editCell('locomotives', ${idx}, 'number', this)" onblur="editCell('locomotives', ${idx}, 'number', this)"` : ''}>${escapeHtml(row.number)}</span>
        </div>
        <table class="device-table">
          <thead>
            <tr>
              <th>Тип прибора</th>
              <th>№ прибора</th>
            </tr>
          </thead>
          <tbody>${deviceRows}</tbody>
        </table>
      </article>
    `;
  }).join("") || `<div class="empty-state">Нет строк</div>`;

  whBody.innerHTML = appState.warehouse.map((row, idx) => `
    <tr data-warehouse-row="1" data-warehouse-type="${escapeHtml(row.type)}" data-warehouse-next="${escapeHtml(row.next_verification_date)}" data-warehouse-location="${escapeHtml(row.location || 'Депо')}" data-warehouse-number="${escapeHtml(row.number)}">
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 0 ? " selected" : ""}"
          data-row="${idx}" data-col="0"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 0, this)" oninput="editWarehouseCell(' + idx + ', 0, this)" onblur="editWarehouseCell(' + idx + ', 0, this)" onclick="handleWarehouseClick(' + idx + ', 0)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 0)" oncopy="handleWarehouseCopy(event, ' + idx + ', 0)" onpaste="handleWarehousePaste(event, ' + idx + ', 0)"' : ''}>${escapeHtml(row.type)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 1 ? " selected" : ""}"
          data-row="${idx}" data-col="1"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 1, this)" oninput="editWarehouseCell(' + idx + ', 1, this)" onblur="editWarehouseCell(' + idx + ', 1, this)" onclick="handleWarehouseClick(' + idx + ', 1)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 1)" oncopy="handleWarehouseCopy(event, ' + idx + ', 1)" onpaste="handleWarehousePaste(event, ' + idx + ', 1)"' : ''}>${escapeHtml(row.number)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 2 ? " selected" : ""}"
          data-row="${idx}" data-col="2"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 2, this)" oninput="editWarehouseCell(' + idx + ', 2, this)" onblur="editWarehouseCell(' + idx + ', 2, this)" onclick="handleWarehouseClick(' + idx + ', 2)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 2)" oncopy="handleWarehouseCopy(event, ' + idx + ', 2)" onpaste="handleWarehousePaste(event, ' + idx + ', 2)"' : ''}>${escapeHtml(row.verification_date)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 3 ? " selected" : ""}"
          data-row="${idx}" data-col="3"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 3, this)" oninput="editWarehouseCell(' + idx + ', 3, this)" onblur="editWarehouseCell(' + idx + ', 3, this)" onclick="handleWarehouseClick(' + idx + ', 3)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 3)" oncopy="handleWarehouseCopy(event, ' + idx + ', 3)" onpaste="handleWarehousePaste(event, ' + idx + ', 3)"' : ''}>${escapeHtml(row.periodicity)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 4 ? " selected" : ""}"
          data-row="${idx}" data-col="4"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 4, this)" oninput="editWarehouseCell(' + idx + ', 4, this)" onblur="editWarehouseCell(' + idx + ', 4, this)" onclick="handleWarehouseClick(' + idx + ', 4)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 4)" oncopy="handleWarehouseCopy(event, ' + idx + ', 4)" onpaste="handleWarehousePaste(event, ' + idx + ', 4)"' : ''}>${escapeHtml(row.next_verification_date)}</td>
      <td class="warehouse-auto" data-row="${idx}" data-col="5">
        <div class="warehouse-auto-value">${escapeHtml(row.location || "Депо")}</div>
      </td>
      <td class="warehouse-auto" data-row="${idx}" data-col="6">
        <div class="warehouse-auto-value warehouse-updated-val" data-row="${idx}">${escapeHtml(row.updated_at || "")}</div>
      </td>
    </tr>
  `).join("") + `<tr id="whEmptyStateRow"><td class="empty-state" colspan="7">Нет строк</td></tr>`;

  // Заполнение фильтров склада
  const typeFilter = document.getElementById("warehouseTypeFilter");
  if (typeFilter) {
    const currentValue = String(warehouseFilters.type ?? "");
    typeFilter.innerHTML = `
      <option value="">Все типы</option>
      ${optionsData.types
        .map((option) => `<option value="${escapeHtml(option)}"${currentValue === option ? " selected" : ""}>${escapeHtml(option)}</option>`)
        .join("")}
    `;
    typeFilter.value = currentValue;
  }

  const locationFilter = document.getElementById("warehouseLocationFilter");
  if (locationFilter) {
    const currentLocation = String(warehouseFilters.location ?? "");
    locationFilter.innerHTML = `
      <option value="">Все места</option>
      ${optionsData.locations
        .map((option) => `<option value="${escapeHtml(option)}"${currentLocation === option ? " selected" : ""}>${escapeHtml(option)}</option>`)
        .join("")}
    `;
    locationFilter.value = currentLocation;
  }

  const nextMonthFilter = document.getElementById("warehouseNextMonthFilter");
  if (nextMonthFilter) {
    const currentMonth = String(warehouseFilters.nextMonth ?? "");
    nextMonthFilter.innerHTML = `
      <option value="">Все месяцы</option>
      ${optionsData.nextMonths
        .map((option) => `<option value="${escapeHtml(option.value)}"${currentMonth === option.value ? " selected" : ""}>${escapeHtml(option.label)}</option>`)
        .join("")}
    `;
    nextMonthFilter.value = currentMonth;
  }

  applyWarehouseFilters();
  applyWarehouseSelectionClasses();
  document.getElementById("saveBtn").style.display = CAN_EDIT ? "inline-block" : "none";
}

/* Глубокое клонирование объекта состояния */
function cloneState(value) {
  return value ? JSON.parse(JSON.stringify(value)) : null;
}

/* Обновление доступности кнопок отмены и повтора действий */
function updateHistoryButtons() {
  const cancelBtn = document.getElementById("cancelBtn");
  const restoreBtn = document.getElementById("restoreBtn");
  const hasDiff = CAN_EDIT && savedState && JSON.stringify(appState) !== JSON.stringify(savedState);
  if (cancelBtn) cancelBtn.disabled = !hasDiff;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledState;
}

/* Отмена несохраненных изменений */
function cancelChanges() {
  if (!CAN_EDIT || !savedState) return;
  syncLocomotivesFromDom();
  syncWarehouseFromDom();
  canceledState = cloneState(appState);
  appState = cloneState(savedState);
  render();
  markDirty(false);
  updateHistoryButtons();
}

/* Возврат отмененных изменений */
function restoreChanges() {
  if (!CAN_EDIT || !canceledState) return;
  appState = cloneState(canceledState);
  canceledState = null;
  render();
  markDirty(true);
  updateHistoryButtons();
}

/* Обновление индикатора несохраненных изменений */
function markDirty(dirty) {
  if (dirty === false) {
    isDirty = false;
  } else if (savedState && appState) {
    isDirty = !!(CAN_EDIT && JSON.stringify(appState) !== JSON.stringify(savedState));
  } else {
    isDirty = !!dirty;
  }
  const btn = document.getElementById("saveBtn");
  if (btn) {
    btn.style.display = CAN_EDIT ? "inline-block" : "none";
    btn.classList.toggle("primary", !!isDirty && !!CAN_EDIT);
    if (!btn.disabled && !btn.textContent.includes("Сохран")) {
      btn.textContent = "Сохранить";
    }
  }
  updateHistoryButtons();
}

/* Сохранение состояния с поддержкой gzip-сжатия и подробной индикацией */
async function saveState() {
  if (!CAN_EDIT) return;
  const btn = document.getElementById("saveBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Сохранение...";
  }

  const t0 = performance.now();

  try {
    if (document.activeElement && typeof document.activeElement.blur === "function") {
      document.activeElement.blur();
    }
    syncLocomotivesFromDom();
    syncWarehouseFromDom();
    recalcWarehouseLocations();
    appState.warehouse.forEach((row) => recalcWarehouseNextDate(row));

    // Обновление даты последнего изменения только для строк приборов с фактическими правками
    const todayStr = formatDateDMY(new Date());
    appState.warehouse.forEach((row, idx) => {
      const savedRow = savedState?.warehouse ? savedState.warehouse[idx] : null;
      const hasAnyData = !!(
        String(row?.type ?? "").trim() ||
        String(row?.number ?? "").trim() ||
        String(row?.verification_date ?? "").trim() ||
        String(row?.periodicity ?? "").trim() ||
        String(row?.next_verification_date ?? "").trim()
      );
      if (!hasAnyData) {
        row.updated_at = "";
      } else if (isWarehouseRowChanged(row, savedRow)) {
        row.updated_at = todayStr;
      }
      const updatedValEl = document.querySelector(`.warehouse-updated-val[data-row="${idx}"]`);
      if (updatedValEl) {
        updatedValEl.innerText = row.updated_at || "";
      }
    });

    const jsonPayload = JSON.stringify(appState);
    let bodyToSend = jsonPayload;
    const headers = { "Content-Type": "application/json; charset=utf-8" };

    // Сжатие gzip на клиенте при наличии поддержки CompressionStream
    if (typeof CompressionStream !== "undefined") {
      try {
        const stream = new Blob([jsonPayload]).stream().pipeThrough(new CompressionStream("gzip"));
        bodyToSend = await new Response(stream).blob();
        headers["Content-Encoding"] = "gzip";
      } catch (e) {
        console.warn("Gzip fallback:", e);
        bodyToSend = jsonPayload;
        delete headers["Content-Encoding"];
      }
    }

    const tPayload = performance.now();
    const res = await fetch(`${APP_PREFIX}/api/state`, {
      method: "POST",
      headers,
      body: bodyToSend
    });

    const tFetch = performance.now();
    const netElapsed = ((tFetch - tPayload) / 1000).toFixed(1);

    if (!res.ok) {
      let errMsg = `Ошибка сохранения (HTTP ${res.status})`;
      try {
        const text = await res.text();
        try {
          const errData = JSON.parse(text);
          if (errData.error) errMsg = `Ошибка сервера: ${errData.error}`;
          else if (errData.detail) errMsg = `Ошибка: ${errData.detail}`;
          else errMsg = `HTTP ${res.status}: ${text.substring(0, 100)}`;
        } catch {
          errMsg = `HTTP ${res.status}: ${text.substring(0, 100)}`;
        }
      } catch {}

      if (btn) {
        btn.disabled = false;
        btn.textContent = `✗ Ошибка (${netElapsed}с)`;
        setTimeout(() => {
          if (btn) {
            btn.textContent = "Сохранить";
            markDirty();
          }
        }, 3000);
      }
      throw new Error(errMsg);
    }

    savedState = cloneState(appState);
    canceledState = null;
    markDirty(false);
    updateHistoryButtons();

    const totalElapsed = ((performance.now() - t0) / 1000).toFixed(1);
    if (btn) {
      btn.disabled = false;
      btn.textContent = `✓ Сохранено (${totalElapsed}с)`;
      setTimeout(() => {
        if (btn) {
          btn.textContent = "Сохранить";
          markDirty();
        }
      }, 2500);
    }
    return true;
  } catch (err) {
    console.error("Save error:", err);
    alert("Ошибка сохранения: " + err.message);
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Сохранить";
      markDirty();
    }
    throw err;
  }
}

let pendingLeaveAction = null;

function checkUnsavedBeforeLeave(action, message) {
  syncLocomotivesFromDom();
  syncWarehouseFromDom();
  markDirty();
  if (!isDirty || !CAN_EDIT) {
    action();
    return;
  }
  pendingLeaveAction = action;
  const modal = document.getElementById("unsavedChangesModal");
  const msgEl = document.getElementById("unsavedChangesMessage");
  if (msgEl && message) msgEl.textContent = message;
  if (modal) modal.style.display = "flex";
}

function initUnsavedChangesModal() {
  const modal = document.getElementById("unsavedChangesModal");
  const saveBtn = document.getElementById("unsavedSaveBtn");
  const discardBtn = document.getElementById("unsavedDiscardBtn");
  const cancelBtn = document.getElementById("unsavedCancelBtn");

  if (saveBtn) {
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = "⏳ Сохранение...";
      try {
        await saveState();
      } catch (e) {
        console.error(e);
        saveBtn.disabled = false;
        saveBtn.textContent = "Сохранить";
        return;
      }
      saveBtn.disabled = false;
      saveBtn.textContent = "Сохранить";
      if (modal) modal.style.display = "none";
      const act = pendingLeaveAction;
      pendingLeaveAction = null;
      if (act) act();
    };
  }

  if (discardBtn) {
    discardBtn.onclick = () => {
      markDirty(false);
      if (modal) modal.style.display = "none";
      const act = pendingLeaveAction;
      pendingLeaveAction = null;
      if (act) act();
    };
  }

  if (cancelBtn) {
    cancelBtn.onclick = () => {
      pendingLeaveAction = null;
      if (modal) modal.style.display = "none";
    };
  }
}

/* Переход на главную страницу портала с проверкой несохраненных изменений */
function requestHomeClick(event) {
  if (event) event.preventDefault();
  const mainUrl = (window.APP_CONFIG && window.APP_CONFIG.MAIN_SITE_URL) ? window.APP_CONFIG.MAIN_SITE_URL : "http://yrtps.ru";
  checkUnsavedBeforeLeave(() => {
    markDirty(false);
    window.location.href = mainUrl + "/";
  }, "Есть несохранённые изменения. Сохранить их перед переходом на главную страницу?");
  return false;
}

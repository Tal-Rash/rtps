const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = {
  columns: [],
  employees: [],
  trainings: {}
};

let currentMode = "dates";
let showDismissed = localStorage.getItem("edu_show_dismissed") === "true";
let tempColumns = [];
let tempCategories = {};
let draggedRowTabNum = null;
let resizeResetTimer = null;
let undoStack = [];
let redoStack = [];
let savedSnapshot = "";
let isDirty = false;
let isEduSelecting = false;
let eduSelectionStart = null;
let eduSelectionEnd = null;

/* Снимок сохраняемого состояния (обучение и порядок сотрудников) */
function getEduSnapshot() {
  return JSON.stringify({
    trainings: appState.trainings || {},
    order: (appState.employees || []).map((e) => e.tab_num)
  });
}

/* Проверка наличия несохранённых изменений и подсветка кнопки Сохранить */
function updateDirtyState(forceHasTypingDiff = false) {
  isDirty = !!(CAN_EDIT && (forceHasTypingDiff || (savedSnapshot && getEduSnapshot() !== savedSnapshot)));
  const btn = document.getElementById("saveBtn");
  if (btn) {
    btn.classList.toggle("primary", isDirty);
    if (isDirty) btn.textContent = "Сохранить";
  }
}

/* Обновление доступности кнопок отмены и возврата */
function updateHistoryButtons() {
  const cancelBtn = document.getElementById("cancelBtn");
  const restoreBtn = document.getElementById("restoreBtn");
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || undoStack.length === 0;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || redoStack.length === 0;
}

/* Применение порядка сотрудников локально в состоянии */
function applyEmployeeOrder(order) {
  const map = new Map((appState.employees || []).map((e) => [e.tab_num, e]));
  const reordered = [];
  order.forEach((tab) => {
    if (map.has(tab)) {
      reordered.push(map.get(tab));
      map.delete(tab);
    }
  });
  map.forEach((e) => reordered.push(e));
  appState.employees = reordered;
}

/* Отмена последнего действия */
function cancelChanges() {
  if (!CAN_EDIT || undoStack.length === 0) return;
  const action = undoStack.pop();
  try {
    if (action.type === "cell") {
      applyCellValueToState(action.tab_num, action.col, action.oldText);
      redoStack.push(action);
      renderMatrix();
    } else if (action.type === "batch") {
      action.changes.forEach((ch) => {
        applyCellValueToState(ch.tab_num, ch.col, ch.oldText);
      });
      redoStack.push(action);
      renderMatrix();
    } else if (action.type === "reorder") {
      applyEmployeeOrder(action.oldOrder);
      redoStack.push(action);
      renderMatrix();
    }
  } catch (err) {
    console.error(err);
    undoStack.push(action);
  }
  updateHistoryButtons();
  updateDirtyState();
}

/* Возврат отмененного действия */
function restoreChanges() {
  if (!CAN_EDIT || redoStack.length === 0) return;
  const action = redoStack.pop();
  try {
    if (action.type === "cell") {
      applyCellValueToState(action.tab_num, action.col, action.newText);
      undoStack.push(action);
      renderMatrix();
    } else if (action.type === "batch") {
      action.changes.forEach((ch) => {
        applyCellValueToState(ch.tab_num, ch.col, ch.newText);
      });
      undoStack.push(action);
      renderMatrix();
    } else if (action.type === "reorder") {
      applyEmployeeOrder(action.newOrder);
      undoStack.push(action);
      renderMatrix();
    }
  } catch (err) {
    console.error(err);
    redoStack.push(action);
  }
  updateHistoryButtons();
  updateDirtyState();
}

window.addEventListener("DOMContentLoaded", () => {
  const chk = document.getElementById("chkShowDismissed");
  if (chk) chk.checked = showDismissed;
  loadState();

  // Горячие клавиши отмены (Ctrl+Z) и возврата (Ctrl+Y / Ctrl+Shift+Z)
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
      if (document.activeElement && document.activeElement.classList.contains("cell")) return;
      e.preventDefault();
      cancelChanges();
    } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
      if (document.activeElement && document.activeElement.classList.contains("cell")) return;
      e.preventDefault();
      restoreChanges();
    }
  });

  window.addEventListener("resize", () => {
    if (resizeResetTimer) clearTimeout(resizeResetTimer);
    resizeResetTimer = setTimeout(() => {
      resetTableScroll();
      requestAnimationFrame(updateStickyOffsets);
    }, 80);
  });
  if (!CAN_EDIT) {
    document.getElementById("btnCategorySettings")?.remove();
    document.getElementById("btnSettings")?.remove();
  } else {
    const saveBtn = document.getElementById("saveBtn");
    if (saveBtn) saveBtn.style.display = "";
  }

  const eduTable = document.getElementById("eduTable");
  if (eduTable) {
    eduTable.addEventListener("click", (e) => {
      const td = e.target.closest("td.col-training");
      if (td) {
        const cell = td.querySelector(".cell[contenteditable='true']");
        if (cell && !window.getSelection().toString()) {
          cell.focus();
        }
      }
    });
  }

  initUnsavedChangesModal();
});

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function requestJson(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      message = data.error || message;
    } catch {
      // Keep the generic HTTP message.
    }
    throw new Error(message);
  }
  return res.json();
}

async function loadState() {
  try {
    appState = await requestJson(`${APP_PREFIX}/api/state`);
    savedSnapshot = getEduSnapshot();
    undoStack = [];
    redoStack = [];
    updateHistoryButtons();
    updateDirtyState();
    renderMatrix();
  } catch (err) {
    console.error(err);
    alert(`Ошибка загрузки модуля обучения: ${err.message}`);
  }
}

/* Обновление данных с сервера с проверкой несохранённых изменений */
function reloadEduState() {
  checkUnsavedBeforeLeave(() => {
    loadState();
  }, "Есть несохранённые изменения. Сохранить их перед обновлением данных?");
}

function setMode(mode) {
  currentMode = mode;
  document.getElementById("btnModeDates").classList.toggle("active", mode === "dates");
  document.getElementById("btnModeProtocols").classList.toggle("active", mode === "protocols");
  document.getElementById("btnModeCerts").classList.toggle("active", mode === "certs");
  renderMatrix();
}

/* Переключение отображения уволенных сотрудников */
function toggleDismissed(checked) {
  showDismissed = Boolean(checked);
  localStorage.setItem("edu_show_dismissed", showDismissed ? "true" : "false");
  renderMatrix();
}

/* Обновление надписи и счетчика уволенных на переключателе */
function updateDismissedToggleLabel() {
  const lbl = document.getElementById("toggleDismissedText");
  const chk = document.getElementById("chkShowDismissed");
  if (chk) chk.checked = showDismissed;
  if (!lbl) return;
  const dismissedCount = (appState.employees || []).filter(e => e.is_dismissed).length;
  if (dismissedCount > 0) {
    lbl.textContent = `Показывать уволенных (${dismissedCount})`;
  } else {
    lbl.textContent = "Показывать уволенных";
  }
}

/* Преобразование даты YYYY-MM-DD в DD.MM.YYYY для отображения */
function formatDateStrRu(str) {
  if (!str) return "";
  const parts = String(str).split("-");
  if (parts.length === 3) {
    return `${parts[2]}.${parts[1]}.${parts[0]}`;
  }
  return str;
}

function parseDateStr(str) {
  if (!str) return null;
  const parts = str.split("-");
  if (parts.length !== 3) return null;
  const date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
  if (date.getFullYear() !== Number(parts[0]) || date.getMonth() !== Number(parts[1]) - 1 || date.getDate() !== Number(parts[2])) {
    return null;
  }
  return date;
}

function parseRuDate(value) {
  let dateStr = String(value || "").split("\n")[0].trim();
  if (!dateStr) return null;

  const cleanText = dateStr.replace(/\D/g, "");
  if (cleanText.length === 6) {
    dateStr = `${cleanText.substring(0, 2)}.${cleanText.substring(2, 4)}.20${cleanText.substring(4, 6)}`;
  } else if (cleanText.length === 8) {
    dateStr = `${cleanText.substring(0, 2)}.${cleanText.substring(2, 4)}.${cleanText.substring(4, 8)}`;
  }

  const parts = dateStr.split(".");
  if (parts.length !== 3) return undefined;

  const day = Number(parts[0]);
  const month = Number(parts[1]);
  const year = Number(parts[2]);
  const date = new Date(year, month - 1, day);
  if (!year || !month || !day || date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return undefined;
  }
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function addMonths(date, months) {
  const d = new Date(date);
  d.setMonth(d.getMonth() + Number(months || 12));
  return d;
}

function formatDate(date) {
  if (!date) return "";
  const d = String(date.getDate()).padStart(2, "0");
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const y = date.getFullYear();
  return `${d}.${m}.${y}`;
}

function renderMatrix() {
  const thead = document.getElementById("eduHead");
  const tbody = document.getElementById("eduBody");

  let hHTML = `<tr>
    <th class="col-drag"></th>
    <th class="col-fio">ФИО работника</th>
    <th class="col-tab">Таб. №</th>
    <th class="col-pos">Должность</th>`;
  for (const c of appState.columns) {
    const trainingClass = c.name === appState.columns[0]?.name ? "col-training col-training-first" : "col-training";
    hHTML += `<th class="${trainingClass}">${escapeHtml(c.name)}</th>`;
  }
  hHTML += "</tr>";
  thead.innerHTML = hHTML;

  updateDismissedToggleLabel();

  let bHTML = "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const visibleEmployees = (appState.employees || []).filter((emp) => {
    if (emp.is_dismissed && !showDismissed) {
      return false;
    }
    return true;
  });

  visibleEmployees.forEach((emp, rIdx) => {
    const isDismissed = Boolean(emp.is_dismissed);
    const categoryClass = emp.category === "itr" ? "category-itr" : "category-workers";
    const dismissedClass = isDismissed ? "row-dismissed" : "";
    const handleHtml = CAN_EDIT ? `<button type="button" class="row-handle" draggable="true" aria-label="Перетащить строку" data-tab="${escapeHtml(emp.tab_num)}">☰</button>` : "";

    // Всплывающая подсказка при наведении (без визуальных бейджей)
    let fioTitle = "";
    if (isDismissed) {
      const dStr = emp.exclude_date ? formatDateStrRu(emp.exclude_date) : "";
      fioTitle = emp.hire_date 
        ? `Принят: ${formatDateStrRu(emp.hire_date)} | Уволен: ${dStr || 'да'}` 
        : `Уволен${dStr ? ' ' + dStr : ''}`;
    } else if (emp.is_pending_dismissal) {
      const dStr = emp.exclude_date ? formatDateStrRu(emp.exclude_date) : "";
      fioTitle = `Назначено увольнение: ${dStr}`;
    } else if (emp.is_future_hire) {
      const dStr = emp.hire_date ? formatDateStrRu(emp.hire_date) : "";
      fioTitle = `Дата приема на работу: ${dStr}`;
    } else if (emp.hire_date) {
      fioTitle = `Принят: ${formatDateStrRu(emp.hire_date)}`;
    }

    const titleAttr = fioTitle ? ` title="${escapeHtml(fioTitle)}"` : "";

    bHTML += `<tr class="edu-row ${categoryClass} ${dismissedClass}" data-tab="${escapeHtml(emp.tab_num)}">
      <td class="col-drag">${handleHtml}</td>
      <td class="col-fio"${titleAttr}><span class="fio-text">${escapeHtml(emp.fio)}</span></td>
      <td class="col-tab">${escapeHtml(emp.tab_num)}</td>
      <td class="col-pos">${escapeHtml(emp.position)}</td>`;

    const empTrainings = appState.trainings[emp.tab_num] || {};
    appState.columns.forEach((col, cIdx) => {
      const tInfo = empTrainings[col.name] || { last: null, period_months: col.period_months, protocol: "", cert: "" };
      let cellText = "";
      let autoText = "";
      let cellClass = "";

      if (currentMode === "protocols") {
        cellText = tInfo.protocol || "";
      } else if (currentMode === "certs") {
        cellText = tInfo.cert || "";
      } else if (tInfo.last) {
        const lastDate = parseDateStr(tInfo.last);
        if (lastDate) {
          const nextDate = addMonths(lastDate, tInfo.period_months || col.period_months);
          const diffDays = Math.ceil((nextDate - today) / (1000 * 60 * 60 * 24));

          cellText = formatDate(lastDate);
          autoText = `<div class="auto-text"><span class="auto-label">сл. аттестация:</span><span class="auto-date">${formatDate(nextDate)}</span>`;
          if (nextDate < today) {
            cellClass = "bg-expired";
            autoText += `<div class="auto-status">Просрочено</div>`;
          } else if (diffDays <= 30) {
            cellClass = "bg-warning";
            autoText += `<div class="auto-status">Действ.</div>`;
          } else {
            autoText += `<div class="auto-status">Действ.</div>`;
          }
          autoText += "</div>";
        }
      }

      const contentEditable = CAN_EDIT ? 'contenteditable="true"' : "";
      const trainingClass = cIdx === 0 ? "col-training col-training-first" : "col-training";
      bHTML += `<td class="${cellClass} ${trainingClass}" data-row="${rIdx}" data-col="${cIdx}" data-tab="${escapeHtml(emp.tab_num)}">
        <div class="cell" ${contentEditable} data-row="${rIdx}" data-tab="${escapeHtml(emp.tab_num)}" data-col="${cIdx}" data-original="${escapeHtml(cellText)}">${escapeHtml(cellText)}</div>
        ${autoText}
      </td>`;
    });
    bHTML += "</tr>";
  });

  tbody.innerHTML = bHTML || `<tr><td class="empty-state" colspan="${appState.columns.length + 4}">Нет сотрудников для отображения</td></tr>`;

  if (CAN_EDIT) {
    attachCellListeners();
    attachRowDragListeners();
  }
  attachEduSelectionListeners();
  applyEduSelectionClasses();

  resetTableScroll();
  requestAnimationFrame(updateStickyOffsets);
}

function resetTableScroll() {
  const wrap = document.querySelector(".table-wrap");
  if (wrap) {
    wrap.scrollLeft = 0;
    wrap.scrollTop = wrap.scrollTop;
  }
  const scroller = document.scrollingElement || document.documentElement;
  if (scroller) scroller.scrollLeft = 0;
  if (window.scrollX !== 0) {
    window.scrollTo(0, window.scrollY);
  }
}

function updateStickyOffsets() {
  const table = document.getElementById("eduTable");
  if (!table) return;

  const sampleRow = table.querySelector("tbody tr.edu-row") || table.querySelector("thead tr");
  if (!sampleRow) return;

  const dragCell = sampleRow.querySelector(".col-drag");
  const fioCell = sampleRow.querySelector(".col-fio");
  const tabCell = sampleRow.querySelector(".col-tab");
  const posCell = sampleRow.querySelector(".col-pos");
  if (!dragCell || !fioCell || !tabCell || !posCell) return;

  const dragRect = dragCell.getBoundingClientRect();
  const fioRect = fioCell.getBoundingClientRect();
  const tabRect = tabCell.getBoundingClientRect();
  const posRect = posCell.getBoundingClientRect();

  const dragLeft = 0;
  const fioLeft = dragRect.width;
  const tabLeft = fioLeft + fioRect.width;
  const posLeft = tabLeft + tabRect.width;

  table.querySelectorAll(".col-drag").forEach((el) => {
    el.style.left = `${dragLeft}px`;
  });
  table.querySelectorAll(".col-fio").forEach((el) => {
    el.style.left = `${fioLeft}px`;
  });
  table.querySelectorAll(".col-tab").forEach((el) => {
    el.style.left = `${tabLeft}px`;
  });
  table.querySelectorAll(".col-pos").forEach((el) => {
    el.style.left = `${posLeft}px`;
  });
}

function attachCellListeners() {
  document.querySelectorAll(".cell[contenteditable='true']").forEach((cell) => {
    cell.addEventListener("blur", onCellBlur);
    cell.addEventListener("keydown", onCellKeydown);
    cell.addEventListener("input", onCellInput);
  });
}

function onCellInput(e) {
  const cell = e.target;
  const currentText = String(cell ? cell.innerText : "").trim();
  const originalText = String(cell && cell.dataset ? cell.dataset.original : "").trim();
  updateDirtyState(currentText !== originalText);
}

function attachRowDragListeners() {
  document.querySelectorAll(".row-handle").forEach((handle) => {
    handle.addEventListener("dragstart", onRowDragStart);
    handle.addEventListener("dragend", onRowDragEnd);
  });
  document.querySelectorAll("tr.edu-row").forEach((row) => {
    row.addEventListener("dragover", onRowDragOver);
    row.addEventListener("dragleave", onRowDragLeave);
    row.addEventListener("drop", onRowDrop);
  });
}

function clearRowDropHints() {
  document.querySelectorAll("tr.edu-row").forEach((row) => {
    row.classList.remove("drop-before", "drop-after");
  });
}

function onRowDragStart(e) {
  const handle = e.currentTarget;
  const row = handle.closest("tr.edu-row");
  draggedRowTabNum = handle.dataset.tab;
  row?.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", draggedRowTabNum || "");
}

function onRowDragEnd() {
  draggedRowTabNum = null;
  document.querySelectorAll("tr.edu-row").forEach((row) => row.classList.remove("dragging", "drop-before", "drop-after"));
}

function onRowDragOver(e) {
  if (!draggedRowTabNum) return;
  e.preventDefault();
  const row = e.currentTarget;
  if (row.dataset.tab === draggedRowTabNum) return;

  const rect = row.getBoundingClientRect();
  const after = e.clientY > rect.top + rect.height / 2;
  clearRowDropHints();
  row.classList.add(after ? "drop-after" : "drop-before");
}

function onRowDragLeave() {
  clearRowDropHints();
}

async function saveEmployeeOrder() {
  const order = appState.employees.map((emp) => emp.tab_num);
  await requestJson(`${APP_PREFIX}/api/settings/employee_order`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(order)
  });
}

function moveEmployeeRow(sourceTabNum, targetTabNum, after) {
  if (!sourceTabNum || !targetTabNum || sourceTabNum === targetTabNum) return;

  const oldOrder = (appState.employees || []).map((e) => e.tab_num);
  const fromIdx = appState.employees.findIndex((emp) => emp.tab_num === sourceTabNum);
  const targetIdx = appState.employees.findIndex((emp) => emp.tab_num === targetTabNum);
  if (fromIdx < 0 || targetIdx < 0) return;

  const [moved] = appState.employees.splice(fromIdx, 1);
  if (targetIdx < 0) {
    appState.employees.splice(fromIdx, 0, moved);
    return;
  }
  let insertAt = targetIdx + (after ? 1 : 0);
  if (fromIdx < targetIdx) insertAt -= 1;
  appState.employees.splice(insertAt, 0, moved);

  const newOrder = (appState.employees || []).map((e) => e.tab_num);
  undoStack.push({ type: "reorder", oldOrder, newOrder });
  redoStack = [];
  updateHistoryButtons();
  renderMatrix();
  updateDirtyState();
}

async function onRowDrop(e) {
  if (!draggedRowTabNum) return;
  e.preventDefault();
  const row = e.currentTarget;
  const targetTabNum = row.dataset.tab;
  const rect = row.getBoundingClientRect();
  const after = e.clientY > rect.top + rect.height / 2;
  clearRowDropHints();
  await moveEmployeeRow(draggedRowTabNum, targetTabNum, after);
}

function onCellKeydown(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    const row = Number(this.dataset.row);
    const col = Number(this.dataset.col);
    this.blur();
    // Переход на строку ниже в том же столбце, как в Excel
    const nextCell = document.querySelector(`#eduBody td.col-training[data-row="${row + 1}"][data-col="${col}"] .cell[contenteditable="true"]`);
    if (nextCell) {
      eduSelectionStart = { row: row + 1, col };
      eduSelectionEnd = { row: row + 1, col };
      applyEduSelectionClasses();
      nextCell.focus();
    }
  }
}

/* Границы выделенного диапазона ячеек таблицы обучения */
function getEduSelectionBounds() {
  if (!eduSelectionStart || !eduSelectionEnd) return null;
  return {
    minRow: Math.min(eduSelectionStart.row, eduSelectionEnd.row),
    maxRow: Math.max(eduSelectionStart.row, eduSelectionEnd.row),
    minCol: Math.min(eduSelectionStart.col, eduSelectionEnd.col),
    maxCol: Math.max(eduSelectionStart.col, eduSelectionEnd.col)
  };
}

function clearEduSelection() {
  eduSelectionStart = null;
  eduSelectionEnd = null;
  applyEduSelectionClasses();
}

/* Подсветка и контурная рамка выделенного диапазона ячеек (как в Excel) */
function applyEduSelectionClasses() {
  document.querySelectorAll("#eduBody td.col-training").forEach((td) => {
    td.classList.remove("edu-selected-range", "edu-selected-anchor");
    td.style.removeProperty("box-shadow");
  });

  const bounds = getEduSelectionBounds();
  if (!bounds) return;

  const isMulti = bounds.maxRow > bounds.minRow || bounds.maxCol > bounds.minCol;
  document.querySelectorAll("#eduBody td.col-training").forEach((td) => {
    const r = Number(td.dataset.row);
    const c = Number(td.dataset.col);
    if (r >= bounds.minRow && r <= bounds.maxRow && c >= bounds.minCol && c <= bounds.maxCol) {
      if (isMulti) {
        td.classList.add("edu-selected-range");
        const shadows = [];
        if (r === bounds.minRow) shadows.push("inset 0 2px 0 0 #276ef1");
        if (r === bounds.maxRow) shadows.push("inset 0 -2px 0 0 #276ef1");
        if (c === bounds.minCol) shadows.push("inset 2px 0 0 0 #276ef1");
        if (c === bounds.maxCol) shadows.push("inset -2px 0 0 0 #276ef1");
        if (shadows.length) td.style.boxShadow = shadows.join(", ");
      }
      if (eduSelectionStart && r === eduSelectionStart.row && c === eduSelectionStart.col) {
        td.classList.add("edu-selected-anchor");
      }
    }
  });
}

let eduSelectionListenersBound = false;
function attachEduSelectionListeners() {
  const eduBody = document.getElementById("eduBody");
  if (!eduBody || eduSelectionListenersBound) return;
  eduSelectionListenersBound = true;

  eduBody.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    const td = e.target.closest("td.col-training");
    if (!td) return;
    const row = Number(td.dataset.row);
    const col = Number(td.dataset.col);
    if (!Number.isFinite(row) || !Number.isFinite(col)) return;

    if (e.shiftKey && eduSelectionStart) {
      e.preventDefault();
      window.getSelection()?.removeAllRanges();
      if (document.activeElement && document.activeElement.classList.contains("cell")) {
        document.activeElement.blur();
      }
      eduSelectionEnd = { row, col };
      applyEduSelectionClasses();
      return;
    }

    eduSelectionStart = { row, col };
    eduSelectionEnd = { row, col };
    isEduSelecting = true;
    applyEduSelectionClasses();
  });

  eduBody.addEventListener("mouseover", (e) => {
    if (!isEduSelecting) return;
    const td = e.target.closest("td.col-training");
    if (!td) return;
    const row = Number(td.dataset.row);
    const col = Number(td.dataset.col);
    if (!Number.isFinite(row) || !Number.isFinite(col)) return;

    if (!eduSelectionStart || (row === eduSelectionStart.row && col === eduSelectionStart.col && (!eduSelectionEnd || (eduSelectionEnd.row === row && eduSelectionEnd.col === col)))) {
      return;
    }
    window.getSelection()?.removeAllRanges();
    if (document.activeElement && document.activeElement.classList.contains("cell")) {
      document.activeElement.blur();
    }
    eduSelectionEnd = { row, col };
    applyEduSelectionClasses();
  });

  window.addEventListener("mouseup", () => {
    isEduSelecting = false;
  });

  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest("#eduTable") && !e.target.closest(".toolbar")) {
      clearEduSelection();
    }
  });

  // Очистка выделенного диапазона по клавише Delete / Backspace
  document.addEventListener("keydown", (e) => {
    if (!CAN_EDIT) return;
    if (e.key !== "Delete" && e.key !== "Backspace") return;
    const activeEl = document.activeElement;
    const bounds = getEduSelectionBounds();
    if (!bounds) return;

    const isMulti = bounds.maxRow > bounds.minRow || bounds.maxCol > bounds.minCol;
    if (activeEl && activeEl.classList.contains("cell") && !isMulti) {
      return;
    }
    if (activeEl && ["INPUT", "SELECT", "TEXTAREA"].includes(activeEl.tagName)) {
      return;
    }

    e.preventDefault();
    const changes = [];
    for (let r = bounds.minRow; r <= bounds.maxRow; r++) {
      for (let c = bounds.minCol; c <= bounds.maxCol; c++) {
        const td = document.querySelector(`#eduBody td.col-training[data-row="${r}"][data-col="${c}"]`);
        if (!td) continue;
        const tab = td.dataset.tab;
        const cellDiv = td.querySelector(".cell");
        const oldText = cellDiv ? String(cellDiv.dataset.original ?? cellDiv.innerText ?? "").trim() : "";
        if (oldText !== "") {
          applyCellValueToState(tab, c, "");
          changes.push({ tab_num: tab, col: c, oldText, newText: "" });
        }
      }
    }
    if (changes.length > 0) {
      undoStack.push({ type: "batch", changes });
      redoStack = [];
      updateHistoryButtons();
      renderMatrix();
      updateDirtyState();
    }
  });
}

/* Применение значения ячейки локально в appState (без отправки на сервер) */
function applyCellValueToState(tabNum, cIdx, rawText) {
  const emp = (appState.employees || []).find((e) => e.tab_num === tabNum);
  const col = appState.columns[cIdx];
  if (!emp || !col) return;

  if (!appState.trainings[emp.tab_num]) appState.trainings[emp.tab_num] = {};
  if (!appState.trainings[emp.tab_num][col.name]) {
    appState.trainings[emp.tab_num][col.name] = { last: null, period_months: col.period_months, protocol: "", cert: "" };
  }

  if (currentMode === "protocols") {
    appState.trainings[emp.tab_num][col.name].protocol = String(rawText || "").trim();
    return;
  }

  if (currentMode === "certs") {
    appState.trainings[emp.tab_num][col.name].cert = String(rawText || "").trim();
    return;
  }

  const isoDate = parseRuDate(rawText);
  if (isoDate === undefined) {
    throw new Error("Введите дату в формате ДД.ММ.ГГГГ");
  }
  appState.trainings[emp.tab_num][col.name].last = isoDate;
  appState.trainings[emp.tab_num][col.name].period_months = col.period_months;
}

function onCellBlur(e) {
  const cell = e.target;
  const newText = String(cell.innerText || "").trim();
  const oldText = String(cell.dataset.original || "").trim();
  if (newText === oldText) {
    updateDirtyState();
    return;
  }

  try {
    applyCellValueToState(cell.dataset.tab, Number(cell.dataset.col), newText);
    undoStack.push({
      type: "cell",
      tab_num: cell.dataset.tab,
      col: Number(cell.dataset.col),
      oldText: oldText,
      newText: newText
    });
    redoStack = [];
    updateHistoryButtons();
    cell.dataset.original = newText;
    renderMatrix();
    updateDirtyState();
  } catch (err) {
    console.error(err);
    alert(`Ошибка ввода: ${err.message}`);
    renderMatrix();
    updateDirtyState();
  }
}

function resetSaveBtn(text = "Сохранить") {
  const btn = document.getElementById("saveBtn");
  if (btn) {
    btn.textContent = text;
    btn.classList.remove("primary");
    if (text === "Сохранено!") {
      setTimeout(() => {
        if (btn.textContent === "Сохранено!") btn.textContent = "Сохранить";
      }, 2000);
    }
  }
}

function openSettingsModal() {
  if (!CAN_EDIT) return;
  tempColumns = JSON.parse(JSON.stringify(appState.columns));
  renderSettingsTable();
  document.getElementById("settingsModal").style.display = "flex";
}

function closeSettingsModal() {
  document.getElementById("settingsModal").style.display = "none";
}

function renderSettingsTable() {
  const tbody = document.getElementById("settingsTableBody");
  let html = "";
  tempColumns.forEach((col, idx) => {
    html += `<tr>
      <td><input type="text" class="input" value="${escapeHtml(col.name)}" onchange="updateSettingsCol(${idx}, 'name', this.value)"></td>
      <td><input type="number" class="input input-number" min="1" max="1200" value="${escapeHtml(col.period_months)}" onchange="updateSettingsCol(${idx}, 'period_months', this.value)"></td>
      <td><button class="btn btn-danger" onclick="deleteSettingsRow(${idx})" title="Удалить">×</button></td>
    </tr>`;
  });
  tbody.innerHTML = html;
}

function updateSettingsCol(idx, field, value) {
  if (field === "period_months") value = Math.max(1, Math.min(Number(value) || 12, 1200));
  tempColumns[idx][field] = value;
}

function addSettingsRow() {
  tempColumns.push({ name: "Новый курс", period_months: 12 });
  renderSettingsTable();
}

function deleteSettingsRow(idx) {
  if (confirm("Удалить этот вид обучения?")) {
    tempColumns.splice(idx, 1);
    renderSettingsTable();
  }
}

async function saveSettings() {
  try {
    await requestJson(`${APP_PREFIX}/api/settings/columns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tempColumns)
    });
    closeSettingsModal();
    await loadState();
  } catch (err) {
    console.error(err);
    alert(`Ошибка сохранения настроек: ${err.message}`);
  }
}

function openCategoryModal() {
  if (!CAN_EDIT) return;
  tempCategories = {};
  for (const emp of appState.employees) {
    if (emp.position) tempCategories[emp.position] = emp.category || "workers";
  }
  renderCategoryTable();
  document.getElementById("categoryModal").style.display = "flex";
}

function closeCategoryModal() {
  document.getElementById("categoryModal").style.display = "none";
}

function renderCategoryTable() {
  const tbody = document.getElementById("categoryTableBody");
  const positions = Object.keys(tempCategories).sort((a, b) => a.localeCompare(b, "ru"));
  tbody.innerHTML = positions.map((pos) => {
    const value = tempCategories[pos] || "workers";
    return `<tr>
      <td>${escapeHtml(pos)}</td>
      <td>
        <select class="input category-select" data-pos="${escapeHtml(pos)}">
          <option value="workers" ${value === "workers" ? "selected" : ""}>Рабочие</option>
          <option value="itr" ${value === "itr" ? "selected" : ""}>ИТР</option>
        </select>
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="2" class="empty-state">Должности не найдены</td></tr>`;
  tbody.querySelectorAll(".category-select").forEach((select) => {
    select.addEventListener("change", () => {
      tempCategories[select.dataset.pos] = select.value;
    });
  });
}

async function saveCategories() {
  try {
    await requestJson(`${APP_PREFIX}/api/settings/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tempCategories)
    });
    closeCategoryModal();
    await loadState();
  } catch (err) {
    console.error(err);
    alert(`Ошибка сохранения категорий: ${err.message}`);
  }
}

document.addEventListener("paste", (e) => {
  if (!CAN_EDIT) return;
  const activeEl = document.activeElement;
  if (activeEl && ["INPUT", "SELECT", "TEXTAREA"].includes(activeEl.tagName)) return;

  let bounds = getEduSelectionBounds();
  if (!bounds && activeEl && activeEl.classList.contains("cell")) {
    const r = Number(activeEl.dataset.row);
    const c = Number(activeEl.dataset.col);
    if (Number.isFinite(r) && Number.isFinite(c)) {
      bounds = { minRow: r, maxRow: r, minCol: c, maxCol: c };
    }
  }
  if (!bounds) return;

  const pasteData = (e.clipboardData || window.clipboardData).getData("text");
  if (!pasteData) return;

  const rawLines = pasteData.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  if (rawLines.length > 1 && rawLines[rawLines.length - 1] === "") {
    rawLines.pop();
  }
  if (!rawLines.length) return;

  const matrix = rawLines.map((line) => line.split("\t"));
  const isSingleValue = matrix.length === 1 && matrix[0].length === 1;
  const isMultiSelected = bounds.maxRow > bounds.minRow || bounds.maxCol > bounds.minCol;

  // Если вставляем 1 значение внутри редактируемой ячейки без выделения диапазона — даём стандартную вставку текста
  if (isSingleValue && !isMultiSelected && activeEl && activeEl.classList.contains("cell")) {
    const selText = window.getSelection()?.toString();
    if (selText) return;
  }

  e.preventDefault();
  const changes = [];
  try {
    if (isSingleValue && isMultiSelected) {
      const val = String(matrix[0][0] ?? "").trim();
      for (let r = bounds.minRow; r <= bounds.maxRow; r++) {
        for (let c = bounds.minCol; c <= bounds.maxCol; c++) {
          const td = document.querySelector(`#eduBody td.col-training[data-row="${r}"][data-col="${c}"]`);
          if (!td) continue;
          const tab = td.dataset.tab;
          const cellDiv = td.querySelector(".cell");
          const oldText = cellDiv ? String(cellDiv.dataset.original ?? cellDiv.innerText ?? "").trim() : "";
          applyCellValueToState(tab, c, val);
          if (oldText !== val) {
            changes.push({ tab_num: tab, col: c, oldText, newText: val });
          }
        }
      }
    } else {
      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < matrix[i].length; j++) {
          const r = bounds.minRow + i;
          const c = bounds.minCol + j;
          const td = document.querySelector(`#eduBody td.col-training[data-row="${r}"][data-col="${c}"]`);
          if (!td) continue;
          const tab = td.dataset.tab;
          const val = String(matrix[i][j] ?? "").trim();
          const cellDiv = td.querySelector(".cell");
          const oldText = cellDiv ? String(cellDiv.dataset.original ?? cellDiv.innerText ?? "").trim() : "";
          applyCellValueToState(tab, c, val);
          if (oldText !== val) {
            changes.push({ tab_num: tab, col: c, oldText, newText: val });
          }
        }
      }
      eduSelectionStart = { row: bounds.minRow, col: bounds.minCol };
      eduSelectionEnd = {
        row: bounds.minRow + matrix.length - 1,
        col: bounds.minCol + Math.max(...matrix.map((row) => row.length)) - 1
      };
    }

    if (changes.length > 0) {
      undoStack.push({ type: "batch", changes });
      redoStack = [];
      updateHistoryButtons();
    }
    renderMatrix();
    updateDirtyState();
  } catch (err) {
    console.error(err);
    alert(`Ошибка вставки: ${err.message}`);
    renderMatrix();
    updateDirtyState();
  }
});

document.addEventListener("copy", (e) => {
  const activeEl = document.activeElement;
  if (activeEl && ["INPUT", "SELECT", "TEXTAREA"].includes(activeEl.tagName)) return;

  const textSelection = window.getSelection()?.toString();
  if (textSelection && activeEl && activeEl.classList.contains("cell")) {
    return;
  }

  let bounds = getEduSelectionBounds();
  if (!bounds && activeEl && activeEl.classList.contains("cell")) {
    const r = Number(activeEl.dataset.row);
    const c = Number(activeEl.dataset.col);
    if (Number.isFinite(r) && Number.isFinite(c)) {
      bounds = { minRow: r, maxRow: r, minCol: c, maxCol: c };
    }
  }
  if (!bounds) return;

  const lines = [];
  for (let r = bounds.minRow; r <= bounds.maxRow; r++) {
    const rowVals = [];
    for (let c = bounds.minCol; c <= bounds.maxCol; c++) {
      const td = document.querySelector(`#eduBody td.col-training[data-row="${r}"][data-col="${c}"]`);
      const cellDiv = td ? td.querySelector(".cell") : null;
      rowVals.push(cellDiv ? String(cellDiv.innerText || "").trim() : "");
    }
    lines.push(rowVals.join("\t"));
  }

  const tsv = lines.join("\n");
  if (tsv || bounds.maxRow > bounds.minRow || bounds.maxCol > bounds.minCol) {
    e.preventDefault();
    (e.clipboardData || window.clipboardData).setData("text/plain", tsv);
  }
});

async function forceSave() {
  if (!CAN_EDIT) return false;

  // Если фокус находится в ячейке, применяем текущее введенное значение
  const active = document.activeElement;
  if (active && active.classList.contains("cell")) {
    const newText = String(active.innerText || "").trim();
    const oldText = String(active.dataset.original || "").trim();
    if (newText !== oldText) {
      try {
        applyCellValueToState(active.dataset.tab, Number(active.dataset.col), newText);
        active.dataset.original = newText;
        undoStack.push({
          type: "cell",
          tab_num: active.dataset.tab,
          col: Number(active.dataset.col),
          oldText,
          newText
        });
        redoStack = [];
        updateHistoryButtons();
      } catch (err) {
        alert(`Ошибка ввода: ${err.message}`);
        return false;
      }
    }
  }

  const btn = document.getElementById("saveBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Сохранение...";
  }

  try {
    const order = (appState.employees || []).map((e) => e.tab_num);
    await requestJson(`${APP_PREFIX}/api/save_state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trainings: appState.trainings || {},
        order
      })
    });

    savedSnapshot = getEduSnapshot();
    updateDirtyState(false);
    renderMatrix();
    resetSaveBtn("Сохранено!");
    return true;
  } catch (err) {
    console.error(err);
    alert(`Ошибка сохранения: ${err.message}`);
    updateDirtyState();
    return false;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function isEduDirty() {
  return !!(CAN_EDIT && (isDirty || (savedSnapshot && getEduSnapshot() !== savedSnapshot)));
}

let pendingLeaveAction = null;

function checkUnsavedBeforeLeave(action, message) {
  if (!isEduDirty() || !CAN_EDIT) {
    action();
    return;
  }
  pendingLeaveAction = action;
  const modal = document.getElementById('unsavedChangesModal');
  const msgEl = document.getElementById('unsavedChangesMessage');
  if (msgEl && message) msgEl.textContent = message;
  if (modal) modal.style.display = 'flex';
}

function handleHomeClick(event) {
  if (event) event.preventDefault();
  const mainUrl = (window.APP_CONFIG && window.APP_CONFIG.MAIN_SITE_URL) ? window.APP_CONFIG.MAIN_SITE_URL : "http://yrtps.ru";
  checkUnsavedBeforeLeave(() => {
    resetSaveBtn();
    window.location.href = mainUrl + "/";
  }, 'Есть несохранённые изменения. Сохранить их перед переходом на главную страницу?');
  return false;
}

function initUnsavedChangesModal() {
  const modal = document.getElementById('unsavedChangesModal');
  const saveBtn = document.getElementById('unsavedSaveBtn');
  const discardBtn = document.getElementById('unsavedDiscardBtn');
  const cancelBtn = document.getElementById('unsavedCancelBtn');

  if (saveBtn) {
    saveBtn.onclick = async () => {
      const ok = await forceSave();
      if (!ok) return;
      if (modal) modal.style.display = 'none';
      const act = pendingLeaveAction;
      pendingLeaveAction = null;
      if (act) act();
    };
  }

  if (discardBtn) {
    discardBtn.onclick = () => {
      savedSnapshot = getEduSnapshot();
      isDirty = false;
      resetSaveBtn();
      if (modal) modal.style.display = 'none';
      const act = pendingLeaveAction;
      pendingLeaveAction = null;
      if (act) act();
    };
  }

  if (cancelBtn) {
    cancelBtn.onclick = () => {
      pendingLeaveAction = null;
      if (modal) modal.style.display = 'none';
    };
  }
}

window.addEventListener('beforeunload', (e) => {
  if (isEduDirty() && CAN_EDIT) {
    e.preventDefault();
    e.returnValue = '';
  }
});

/* Автоматическая инициализация пользовательских меток таблиц для модуля Обучение */
function getEmpReplacementPairs() {
  const raw = localStorage.getItem('rtps_emp_dict') || localStorage.getItem('rtps_employees_full_dict');
  if (!raw) return [];
  
  let map = null;
  try { map = JSON.parse(raw); } catch (e) { return []; }
  if (!map) return [];

  const flatMap = {};

  function extractNum(idStr) {
    if (!idStr) return null;
    const clean = String(idStr)
      .replace(/ID_/g, '')
      .replace(/Работник\s*№?\s*/g, '')
      .replace(/СотрудникПолн\s*№?\s*/g, '')
      .replace(/Сотрудник\s*№?\s*/g, '')
      .replace(/Должность\s*№?\s*/g, '')
      .trim();
    const num = parseInt(clean, 10);
    return isNaN(num) ? null : num;
  }

  function addFieldVariants(prefix, num, val) {
    const sNum = String(num);
    const pNum = (num < 10 ? '00' : (num < 100 ? '0' : '')) + num;
    const valStr = String(val);

    flatMap[prefix + " №" + num] = valStr;
    flatMap[prefix + " №" + sNum] = valStr;
    flatMap[prefix + " №" + pNum] = valStr;
    flatMap[prefix + " № " + sNum] = valStr;
    flatMap[prefix + " № " + pNum] = valStr;
  }

  function addIdVariants(num, val) {
    const sNum = String(num);
    const pNum = (num < 10 ? '00' : (num < 100 ? '0' : '')) + num;
    const valStr = String(val);

    flatMap["ID_" + pNum] = valStr;
    flatMap["ID_" + sNum] = valStr;
    flatMap["ID_" + num] = valStr;
  }

  if (Array.isArray(map)) {
    for (let i = 0; i < map.length; i++) {
      let rec = map[i];
      if (!rec) continue;

      let num = extractNum(rec.id || rec.tab || rec.tab_num);
      if (num === null) num = i + 1;

      let shortF = rec.shortFio || rec.fio || rec.name || rec.short_name || '';
      let fullF = rec.fullFio || rec.full_name || rec.fio || rec.name || '';
      let pos = rec.pos || rec.position || '';
      let tab = rec.tab || rec.tab_num || rec.id || '';

      if (shortF) addFieldVariants("Работник", num, shortF);
      if (fullF) {
        addFieldVariants("СотрудникПолн", num, fullF);
        addFieldVariants("Сотрудник", num, fullF);
      }
      if (pos) addFieldVariants("Должность", num, pos);
      if (tab) {
        addIdVariants(num, tab);
        if (rec.id) flatMap[String(rec.id)] = String(tab);
      }
    }
  } else if (typeof map === 'object') {
    for (let k in map) {
      if (map.hasOwnProperty(k) && k && map[k]) {
        const valStr = String(map[k]);
        flatMap[k] = valStr;
        let num = extractNum(k);
        if (num !== null) {
          if (k.startsWith("Работник")) {
            addFieldVariants("Работник", num, valStr);
          } else if (k.startsWith("СотрудникПолн")) {
            addFieldVariants("СотрудникПолн", num, valStr);
            addFieldVariants("Сотрудник", num, valStr);
          } else if (k.startsWith("Сотрудник")) {
            addFieldVariants("Сотрудник", num, valStr);
            addFieldVariants("СотрудникПолн", num, valStr);
          } else if (k.startsWith("Должность")) {
            addFieldVariants("Должность", num, valStr);
          } else if (k.startsWith("ID_") || /^\d+$/.test(k)) {
            addIdVariants(num, valStr);
          }
        }
      }
    }
  }

  const pairs = [];
  for (let k in flatMap) {
    if (flatMap.hasOwnProperty(k) && k && flatMap[k]) {
      pairs.push({ from: k, to: String(flatMap[k]) });
    }
  }

  pairs.sort((a, b) => b.from.length - a.from.length);
  return pairs;
}

(function initTableCustomLabels() {
  function applyCustomLabels() {
    try {
      const pairs = typeof getEmpReplacementPairs === 'function' ? getEmpReplacementPairs() : [];
      if (!pairs || !pairs.length) return;

      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
      let node;
      while ((node = walker.nextNode())) {
        let val = node.nodeValue;
        if (!val || !val.trim()) continue;
        let newVal = val;
        for (let p = 0; p < pairs.length; p++) {
          if (newVal.indexOf(pairs[p].from) !== -1) {
            newVal = newVal.split(pairs[p].from).join(pairs[p].to);
          }
        }
        if (newVal !== val) node.nodeValue = newVal;
      }

      const inputs = document.querySelectorAll('input, select, option, textarea');
      for (let i = 0; i < inputs.length; i++) {
        let el = inputs[i];
        if (el.tagName === 'OPTION' || el.tagName === 'option') {
          if (el.textContent) {
            let val = el.textContent, newVal = val;
            for (let p = 0; p < pairs.length; p++) {
              if (newVal.indexOf(pairs[p].from) !== -1) {
                newVal = newVal.split(pairs[p].from).join(pairs[p].to);
              }
            }
            if (newVal !== val) el.textContent = newVal;
          }
        }
        if (el.value) {
          let val = el.value, newVal = val;
          for (let p = 0; p < pairs.length; p++) {
            if (newVal.indexOf(pairs[p].from) !== -1) {
              newVal = newVal.split(pairs[p].from).join(pairs[p].to);
            }
          }
          if (newVal !== val) el.value = newVal;
        }
        if (el.title) {
          let val = el.title, newVal = val;
          for (let p = 0; p < pairs.length; p++) {
            if (newVal.indexOf(pairs[p].from) !== -1) {
              newVal = newVal.split(pairs[p].from).join(pairs[p].to);
            }
          }
          if (newVal !== val) el.title = newVal;
        }
        if (el.placeholder) {
          let val = el.placeholder, newVal = val;
          for (let p = 0; p < pairs.length; p++) {
            if (newVal.indexOf(pairs[p].from) !== -1) {
              newVal = newVal.split(pairs[p].from).join(pairs[p].to);
            }
          }
          if (newVal !== val) el.placeholder = newVal;
        }
      }
    } catch (e) {}
  }

  window.applyCustomLabels = applyCustomLabels;

  document.addEventListener("DOMContentLoaded", function () {
    applyCustomLabels();
    let timer = null;
    const observer = new MutationObserver(function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(applyCustomLabels, 10);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();

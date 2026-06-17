const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = {
  columns: [],
  employees: [],
  trainings: {}
};

let currentMode = "dates";
let tempColumns = [];
let tempCategories = {};
let draggedRowTabNum = null;
let resizeResetTimer = null;

window.addEventListener("DOMContentLoaded", () => {
  loadState();
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
  }
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
    renderMatrix();
  } catch (err) {
    console.error(err);
    alert(`Ошибка загрузки модуля обучения: ${err.message}`);
  }
}

function setMode(mode) {
  currentMode = mode;
  document.getElementById("btnModeDates").classList.toggle("active", mode === "dates");
  document.getElementById("btnModeProtocols").classList.toggle("active", mode === "protocols");
  renderMatrix();
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

  let bHTML = "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  appState.employees.forEach((emp, rIdx) => {
    const categoryClass = emp.category === "itr" ? "category-itr" : "category-workers";
    const handleHtml = CAN_EDIT ? `<button type="button" class="row-handle" draggable="true" aria-label="Перетащить строку" data-tab="${escapeHtml(emp.tab_num)}">☰</button>` : "";
    bHTML += `<tr class="edu-row ${categoryClass}" data-tab="${escapeHtml(emp.tab_num)}">
      <td class="col-drag">${handleHtml}</td>
      <td class="col-fio">${escapeHtml(emp.fio)}</td>
      <td class="col-tab">${escapeHtml(emp.tab_num)}</td>
      <td class="col-pos">${escapeHtml(emp.position)}</td>`;

    const empTrainings = appState.trainings[emp.tab_num] || {};
    appState.columns.forEach((col, cIdx) => {
      const tInfo = empTrainings[col.name] || { last: null, period_months: col.period_months, protocol: "" };
      let cellText = "";
      let autoText = "";
      let cellClass = "";

      if (currentMode === "protocols") {
        cellText = tInfo.protocol || "";
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
      bHTML += `<td class="${cellClass} ${trainingClass}">
        <div class="cell" ${contentEditable} data-row="${rIdx}" data-col="${cIdx}">${escapeHtml(cellText)}</div>
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
  });
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

async function moveEmployeeRow(sourceTabNum, targetTabNum, after) {
  if (!sourceTabNum || !targetTabNum || sourceTabNum === targetTabNum) return;

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

  renderMatrix();
  try {
    await saveEmployeeOrder();
  } catch (err) {
    console.error(err);
    alert(`Ошибка сохранения порядка строк: ${err.message}`);
    await loadState();
  }
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
    this.blur();
  }
}

async function saveCellValue(rIdx, cIdx, rawText) {
  const emp = appState.employees[rIdx];
  const col = appState.columns[cIdx];
  if (!emp || !col) return;

  if (currentMode === "protocols") {
    const protocol = String(rawText || "").trim();
    await requestJson(`${APP_PREFIX}/api/save_protocol`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tab_num: emp.tab_num,
        training_type: col.name,
        protocol
      })
    });

    if (!appState.trainings[emp.tab_num]) appState.trainings[emp.tab_num] = {};
    if (!appState.trainings[emp.tab_num][col.name]) appState.trainings[emp.tab_num][col.name] = { period_months: col.period_months };
    appState.trainings[emp.tab_num][col.name].protocol = protocol;
    return;
  }

  const isoDate = parseRuDate(rawText);
  if (isoDate === undefined) {
    throw new Error("Введите дату в формате ДД.ММ.ГГГГ");
  }

  await requestJson(`${APP_PREFIX}/api/save_training`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      tab_num: emp.tab_num,
      training_type: col.name,
      last_date: isoDate,
      period_months: col.period_months
    })
  });

  if (!appState.trainings[emp.tab_num]) appState.trainings[emp.tab_num] = {};
  if (!appState.trainings[emp.tab_num][col.name]) appState.trainings[emp.tab_num][col.name] = { period_months: col.period_months };
  appState.trainings[emp.tab_num][col.name].last = isoDate;
}

async function onCellBlur(e) {
  const cell = e.target;
  try {
    await saveCellValue(Number(cell.dataset.row), Number(cell.dataset.col), cell.innerText);
    renderMatrix();
  } catch (err) {
    console.error(err);
    alert(`Ошибка сохранения: ${err.message}`);
    renderMatrix();
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

document.addEventListener("paste", async (e) => {
  if (!CAN_EDIT) return;
  const activeEl = document.activeElement;
  if (!activeEl || !activeEl.classList.contains("cell")) return;

  e.preventDefault();
  const pasteData = (e.clipboardData || window.clipboardData).getData("text");
  if (!pasteData) return;

  const lines = pasteData.replace(/\r/g, "").split("\n").filter((line) => line.length);
  const startRow = Number(activeEl.dataset.row);
  const startCol = Number(activeEl.dataset.col);

  try {
    for (let i = 0; i < lines.length; i++) {
      const cells = lines[i].split("\t");
      for (let j = 0; j < cells.length; j++) {
        await saveCellValue(startRow + i, startCol + j, cells[j]);
      }
    }
    renderMatrix();
  } catch (err) {
    console.error(err);
    alert(`Ошибка вставки: ${err.message}`);
    renderMatrix();
  }
});

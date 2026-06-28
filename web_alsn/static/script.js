const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = { locomotives: [], warehouse: [] };
let currentTab = "locomotives";
let isDirty = false;
const MIN_LOCOMOTIVES = 5;
const WAREHOUSE_FIELDS = [
  "type",
  "number",
  "verification_date",
  "periodicity",
  "next_verification_date",
  "location"
];
let warehouseSelected = null;

document.addEventListener("DOMContentLoaded", () => {
  loadState();
});

function blankDeviceRows(count = 5) {
  return Array.from({ length: Math.max(1, count) }, () => ({ type: "", number: "" }));
}

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

function normalizeWhRow(row) {
  return {
    type: String(row?.type ?? ""),
    number: String(row?.number ?? ""),
    verification_date: String(row?.verification_date ?? ""),
    periodicity: String(row?.periodicity ?? ""),
    next_verification_date: String(row?.next_verification_date ?? ""),
    location: String(row?.location ?? "")
  };
}

function ensureMinLocomotives(rows, minCount = MIN_LOCOMOTIVES) {
  const normalized = Array.isArray(rows) ? rows.slice() : [];
  while (normalized.length < minCount) {
    normalized.push(blankLoc());
  }
  return normalized;
}

function setTab(tab) {
  currentTab = tab;
  document.getElementById("tabLoc").classList.toggle("active", tab === "locomotives");
  document.getElementById("tabWh").classList.toggle("active", tab === "warehouse");
  document.getElementById("tab-locomotives").classList.toggle("active", tab === "locomotives");
  document.getElementById("tab-warehouse").classList.toggle("active", tab === "warehouse");
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

async function loadState() {
  try {
    const data = await requestJson(`${APP_PREFIX}/api/state`);
    appState = {
      locomotives: ensureMinLocomotives(Array.isArray(data.locomotives) ? data.locomotives.map(normalizeLocRow) : []),
      warehouse: Array.isArray(data.warehouse) ? data.warehouse.map(normalizeWhRow) : []
    };
    if (!appState.warehouse.length) appState.warehouse.push(blankWh());
    render();
    markDirty(false);
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
    location: ""
  };
}

function warehouseCellText(rowIdx, colIdx) {
  const row = appState.warehouse[rowIdx];
  if (!row) return "";
  const field = WAREHOUSE_FIELDS[colIdx];
  return field ? String(row[field] ?? "") : "";
}

function setWarehouseCellValue(rowIdx, colIdx, value) {
  const row = appState.warehouse[rowIdx];
  const field = WAREHOUSE_FIELDS[colIdx];
  if (!row || !field) return;
  row[field] = String(value ?? "");
}

function selectWarehouseCell(rowIdx, colIdx) {
  warehouseSelected = { row: rowIdx, col: colIdx };
  document.querySelectorAll(".warehouse-cell.selected").forEach((cell) => cell.classList.remove("selected"));
  const cell = document.querySelector(`.warehouse-cell[data-row="${rowIdx}"][data-col="${colIdx}"]`);
  if (cell) cell.classList.add("selected");
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

function syncWarehouseFromDom() {
  document.querySelectorAll(".warehouse-cell").forEach((cell) => {
    const rowIdx = Number(cell.dataset.row);
    const colIdx = Number(cell.dataset.col);
    if (Number.isFinite(rowIdx) && Number.isFinite(colIdx)) {
      setWarehouseCellValue(rowIdx, colIdx, cell.innerText.trim());
    }
  });
}

function getRows() {
  return currentTab === "locomotives" ? appState.locomotives : appState.warehouse;
}

function addRow() {
  if (!CAN_EDIT) return;
  if (currentTab === "warehouse") syncWarehouseFromDom();
  const rows = getRows();
  rows.push(currentTab === "locomotives" ? blankLoc() : blankWh());
  render();
  markDirty(true);
}

function removeRow() {
  if (!CAN_EDIT) return;
  if (currentTab === "warehouse") syncWarehouseFromDom();
  const rows = getRows();
  if (currentTab === "locomotives" && rows.length <= MIN_LOCOMOTIVES) return;
  if (currentTab === "warehouse" && rows.length <= 1) return;
  rows.pop();
  render();
  markDirty(true);
}

function editCell(tab, rowIdx, field, el) {
  const rows = tab === "locomotives" ? appState.locomotives : appState.warehouse;
  if (!rows[rowIdx]) return;
  rows[rowIdx][field] = el.innerText.trim();
  markDirty(true);
}

function editDeviceCell(rowIdx, deviceIdx, field, el) {
  const row = appState.locomotives[rowIdx];
  if (!row) return;
  if (!Array.isArray(row.devices)) row.devices = blankDeviceRows();
  if (!row.devices[deviceIdx]) row.devices[deviceIdx] = { type: "", number: "" };
  row.devices[deviceIdx][field] = el.innerText.trim();
  markDirty(true);
}

function editWarehouseCell(rowIdx, colIdx, el) {
  setWarehouseCellValue(rowIdx, colIdx, el.innerText.trim());
  markDirty(true);
}

function handleWarehouseFocus(rowIdx, colIdx, el) {
  selectWarehouseCell(rowIdx, colIdx);
  if (!el.innerText.trim() && el.innerText !== "") {
    el.innerText = "";
  }
}

function handleWarehouseClick(rowIdx, colIdx) {
  selectWarehouseCell(rowIdx, colIdx);
}

function handleWarehouseKeydown(event, rowIdx, colIdx) {
  if (!CAN_EDIT) return;

  const key = event.key;
  if (key === "Delete" || key === "Backspace") {
    event.preventDefault();
    const cell = event.currentTarget;
    cell.innerText = "";
    setWarehouseCellValue(rowIdx, colIdx, "");
    markDirty(true);
    return;
  }

  let targetRow = rowIdx;
  let targetCol = colIdx;
  if (key === "ArrowLeft") targetCol -= 1;
  else if (key === "ArrowRight" || key === "Tab") {
    event.preventDefault();
    targetCol += 1;
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
  if (targetCol >= WAREHOUSE_FIELDS.length) return;
  focusWarehouseCell(targetRow, targetCol, true);
}

function handleWarehouseCopy(event, rowIdx, colIdx) {
  const text = warehouseCellText(rowIdx, colIdx);
  if (!text) return;
  event.clipboardData?.setData("text/plain", text);
  event.preventDefault();
}

function handleWarehousePaste(event, rowIdx, colIdx) {
  if (!CAN_EDIT) return;
  event.preventDefault();
  syncWarehouseFromDom();
  const text = event.clipboardData?.getData("text/plain") || "";
  const matrix = parsePasteMatrix(text);
  if (!matrix.length) return;

  for (let r = 0; r < matrix.length; r += 1) {
    const sourceRow = matrix[r];
    const targetRowIdx = rowIdx + r;
    const targetRow = appState.warehouse[targetRowIdx];
    if (!targetRow) break;
    for (let c = 0; c < sourceRow.length; c += 1) {
      const targetColIdx = colIdx + c;
      if (targetColIdx >= WAREHOUSE_FIELDS.length) break;
      setWarehouseCellValue(targetRowIdx, targetColIdx, sourceRow[c].trim());
    }
  }
  render();
  markDirty(true);
  focusWarehouseCell(
    Math.min(rowIdx + matrix.length - 1, appState.warehouse.length - 1),
    Math.min(colIdx + matrix[0].length - 1, WAREHOUSE_FIELDS.length - 1)
  );
}

function render() {
  const locBody = document.getElementById("locBody");
  const whBody = document.getElementById("whBody");

  locBody.innerHTML = appState.locomotives.map((row, idx) => {
    const deviceRows = (row.devices && row.devices.length ? row.devices : blankDeviceRows()).map((device, deviceIdx) => `
      <tr>
        <td>
          <div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editDeviceCell(${idx}, ${deviceIdx}, 'type', this)"` : ''}>${escapeHtml(device.type)}</div>
        </td>
        <td>
          <div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editDeviceCell(${idx}, ${deviceIdx}, 'number', this)"` : ''}>${escapeHtml(device.number)}</div>
        </td>
      </tr>
    `).join("");

    return `
      <article class="loc-card">
        <div class="loc-card-title">
          <span class="editable" style="display:inline-block; min-width:120px;" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('locomotives', ${idx}, 'series', this)"` : ''}>${escapeHtml(row.series || "Локомотив")}</span>
          <span> № </span>
          <span class="editable" style="display:inline-block; min-width:70px;" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('locomotives', ${idx}, 'number', this)"` : ''}>${escapeHtml(row.number)}</span>
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
    <tr>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 0 ? " selected" : ""}"
          data-row="${idx}" data-col="0"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 0, this)" onblur="editWarehouseCell(' + idx + ', 0, this)" onclick="handleWarehouseClick(' + idx + ', 0)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 0)" oncopy="handleWarehouseCopy(event, ' + idx + ', 0)" onpaste="handleWarehousePaste(event, ' + idx + ', 0)"' : ''}>${escapeHtml(row.type)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 1 ? " selected" : ""}"
          data-row="${idx}" data-col="1"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 1, this)" onblur="editWarehouseCell(' + idx + ', 1, this)" onclick="handleWarehouseClick(' + idx + ', 1)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 1)" oncopy="handleWarehouseCopy(event, ' + idx + ', 1)" onpaste="handleWarehousePaste(event, ' + idx + ', 1)"' : ''}>${escapeHtml(row.number)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 2 ? " selected" : ""}"
          data-row="${idx}" data-col="2"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 2, this)" onblur="editWarehouseCell(' + idx + ', 2, this)" onclick="handleWarehouseClick(' + idx + ', 2)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 2)" oncopy="handleWarehouseCopy(event, ' + idx + ', 2)" onpaste="handleWarehousePaste(event, ' + idx + ', 2)"' : ''}>${escapeHtml(row.verification_date)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 3 ? " selected" : ""}"
          data-row="${idx}" data-col="3"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 3, this)" onblur="editWarehouseCell(' + idx + ', 3, this)" onclick="handleWarehouseClick(' + idx + ', 3)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 3)" oncopy="handleWarehouseCopy(event, ' + idx + ', 3)" onpaste="handleWarehousePaste(event, ' + idx + ', 3)"' : ''}>${escapeHtml(row.periodicity)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 4 ? " selected" : ""}"
          data-row="${idx}" data-col="4"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 4, this)" onblur="editWarehouseCell(' + idx + ', 4, this)" onclick="handleWarehouseClick(' + idx + ', 4)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 4)" oncopy="handleWarehouseCopy(event, ' + idx + ', 4)" onpaste="handleWarehousePaste(event, ' + idx + ', 4)"' : ''}>${escapeHtml(row.next_verification_date)}</td>
      <td class="warehouse-cell${warehouseSelected?.row === idx && warehouseSelected?.col === 5 ? " selected" : ""}"
          data-row="${idx}" data-col="5"
          ${CAN_EDIT ? 'contenteditable="true" spellcheck="false" onfocus="handleWarehouseFocus(' + idx + ', 5, this)" onblur="editWarehouseCell(' + idx + ', 5, this)" onclick="handleWarehouseClick(' + idx + ', 5)" onkeydown="handleWarehouseKeydown(event, ' + idx + ', 5)" oncopy="handleWarehouseCopy(event, ' + idx + ', 5)" onpaste="handleWarehousePaste(event, ' + idx + ', 5)"' : ''}>${escapeHtml(row.location)}</td>
    </tr>
  `).join("") || `<tr><td class="empty-state" colspan="6">Нет строк</td></tr>`;

  document.getElementById("saveBtn").style.display = CAN_EDIT ? "inline-block" : "none";
}

function markDirty(dirty) {
  isDirty = dirty;
  const btn = document.getElementById("saveBtn");
  if (!btn) return;
  btn.textContent = dirty ? "Сохранить*" : "Сохранить";
}

async function saveState() {
  if (!CAN_EDIT) return;
  try {
    if (currentTab === "warehouse") syncWarehouseFromDom();
    if (document.activeElement && typeof document.activeElement.blur === "function") {
      document.activeElement.blur();
    }
    await requestJson(`${APP_PREFIX}/api/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(appState)
    });
    markDirty(false);
  } catch (err) {
    console.error(err);
    alert("Ошибка сохранения: " + err.message);
  }
}

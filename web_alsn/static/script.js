const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = { locomotives: [], warehouse: [] };
let currentTab = "locomotives";
let isDirty = false;

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
    item: String(row?.item ?? ""),
    unit: String(row?.unit ?? ""),
    quantity: String(row?.quantity ?? ""),
    note: String(row?.note ?? "")
  };
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
      locomotives: Array.isArray(data.locomotives) ? data.locomotives.map(normalizeLocRow) : [],
      warehouse: Array.isArray(data.warehouse) ? data.warehouse.map(normalizeWhRow) : []
    };
    if (!appState.locomotives.length) appState.locomotives.push(blankLoc());
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
  return { item: "", unit: "", quantity: "", note: "" };
}

function getRows() {
  return currentTab === "locomotives" ? appState.locomotives : appState.warehouse;
}

function addRow() {
  if (!CAN_EDIT) return;
  const rows = getRows();
  rows.push(currentTab === "locomotives" ? blankLoc() : blankWh());
  render();
  markDirty(true);
}

function removeRow() {
  if (!CAN_EDIT) return;
  const rows = getRows();
  if (rows.length <= 1) return;
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
      <td class="row-num">${idx + 1}</td>
      <td><div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('warehouse', ${idx}, 'item', this)"` : ''}>${escapeHtml(row.item)}</div></td>
      <td><div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('warehouse', ${idx}, 'unit', this)"` : ''}>${escapeHtml(row.unit)}</div></td>
      <td><div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('warehouse', ${idx}, 'quantity', this)"` : ''}>${escapeHtml(row.quantity)}</div></td>
      <td><div class="editable" ${CAN_EDIT ? `contenteditable="true" onblur="editCell('warehouse', ${idx}, 'note', this)"` : ''}>${escapeHtml(row.note)}</div></td>
    </tr>
  `).join("") || `<tr><td class="empty-state" colspan="5">Нет строк</td></tr>`;

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

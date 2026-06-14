const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = null;
let isDirty = false;

document.addEventListener("DOMContentLoaded", () => {
  const d = new Date();
  document.getElementById("yearInput").value = d.getFullYear();
  document.getElementById("monthInput").value = d.getMonth() + 1;
  loadState();
});

function setMonth(val) {
  document.getElementById("monthInput").value = val;
  loadState();
}

function renderMonthButtons() {
  const months = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
  ];
  const currentMonth = parseInt(document.getElementById("monthInput").value, 10);
  const html = months.map((m, i) => {
    const val = i + 1;
    const active = val === currentMonth ? 'class="active"' : '';
    return `<button ${active} onclick="setMonth(${val})">${m}</button>`;
  }).join('');
  const strip = document.getElementById("monthStrip");
  if (strip) strip.innerHTML = html;
}

function switchTab(tabId) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  
  event.currentTarget.classList.add('active');
  document.getElementById('tab-' + tabId).classList.add('active');
  
  if (tabId === 'months') {
    applyVacations();
    setTimeout(autoResizeMonthHint, 10);
  }
}

function autoResizeMonthHint() {
  const mh = document.getElementById("monthHint");
  if (!mh || mh.offsetParent === null) return;
  mh.style.height = 'auto';
  mh.style.height = mh.scrollHeight + 'px';
}

function markDirty(dirty) {
  isDirty = dirty;
  const btn = document.getElementById("saveBtn");
  btn.style.display = CAN_EDIT ? "inline-block" : "none";
  if (dirty) {
    btn.classList.add("dirty");
    btn.textContent = "Сохранить*";
  } else {
    btn.classList.remove("dirty");
    btn.textContent = "Сохранить";
  }
}

async function loadState() {
  const year = document.getElementById("yearInput").value;
  const month = document.getElementById("monthInput").value;
  
  try {
    const res = await fetch(`${APP_PREFIX}/api/state?year=${year}&month=${month}`);
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        alert("Нет доступа. Пожалуйста, авторизуйтесь.");
        window.location.href = "/";
        return;
      }
      throw new Error("Failed to load");
    }
    appState = await res.json();
    applyVacations(); // Re-apply vacations to fix old DB state
    renderMonthButtons();
    renderTable();
    markDirty(false);
  } catch (err) {
    console.error(err);
    alert("Ошибка загрузки данных");
  }
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function renderTable() {
  const mh = document.getElementById("monthHint");
  if (mh) {
    mh.value = appState.month_hint || "";
    if (!CAN_EDIT) mh.readOnly = true;
    setTimeout(autoResizeMonthHint, 50);
  }
  updateExportMenu();
  const year = parseInt(appState.year);
  const month = parseInt(appState.month);
  const days = daysInMonth(year, month);
  
  // Render Headers
  const thead = document.getElementById("tabelHeader");
  let hHTML = `<th class="col-idx">№</th><th class="col-pos">Должность</th><th class="col-fio">ФИО</th><th class="col-tab">Таб. №</th>`;
  for (let d = 1; d <= days; d++) {
    hHTML += `<th class="col-day">${String(d).padStart(2, '0')}</th>`;
  }
  thead.innerHTML = hHTML;
  
  renderTabelBody();
  // Render Data (Norms)
  const dbody = document.getElementById("dataBody");
  let dHTML = "";
  const monthsNames = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  for (let r = 0; r < 12; r++) {
    dHTML += `<tr><td style="text-align: left;">${monthsNames[r]}</td>`;
    for (let c = 1; c < 8; c++) {
      const val = (appState.ts_norms_data && appState.ts_norms_data[r] && appState.ts_norms_data[r][c]) || "";
      dHTML += `<td><div class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="dataEdited(${r}, ${c}, this)">${escapeHtml(val)}</div></td>`;
    }
    dHTML += `</tr>`;
  }
  dbody.innerHTML = dHTML;

  // Render Employees
  const ebody = document.getElementById("employeesBody");
  let eHTML = "";
  appState.employees.forEach((emp, r) => {
    const trClass = "";
    eHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;
    eHTML += `<td class="col-idx" style="cursor: grab;"><div class="rownum"><span>${r + 1}</span></div></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'pos', this)">${escapeHtml(emp.pos)}</div></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'name', this)">${escapeHtml(emp.name)}</div></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'full_name', this)">${escapeHtml(emp.full_name)}</div></td>`;
    eHTML += `<td><div class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'tab_num', this)">${escapeHtml(emp.tab_num)}</div></td>`;
    eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk', this)" ${emp.milk ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk_issue', this)" ${emp.milk_issue ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><input type="date" onchange="empEdited(${r}, 'exclude_date', this)" value="${emp.exclude_date || ''}" ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'milk_note', this)">${escapeHtml(emp.milk_note)}</div></td>`;
    eHTML += `</tr>`;
  });
  ebody.innerHTML = eHTML;

  // Render Vacations
  const vbody = document.getElementById("vacationsBody");
  let vHTML = "";
  for (let r = 0; r < 11; r++) {
    const emp = appState.employees[r] || {};
    const tabNum = emp.tab_num || `empty_${r}`;
    const trClass = emp.exclude_date ? "excluded" : "";
    vHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;
    vHTML += `<td class="col-idx" style="cursor: grab;"><div class="rownum"><span>${r + 1}</span></div></td>`;
    vHTML += `<td style="text-align: left;">${escapeHtml(emp.tab_num || '')}</td>`;
    vHTML += `<td style="text-align: left;">${escapeHtml(emp.name || '')}</td>`;
    
    const cols = [1, 2, 3, 'sep', 5, 6, 7, 'sep', 9, 10, 11];
    cols.forEach(c => {
      if (c === 'sep') {
        vHTML += `<td style="background:#f0f0f0;"></td>`; // separator
      } else {
        const val = (appState.vacations && appState.vacations[tabNum] && appState.vacations[tabNum][c]) || "";
        vHTML += `<td><div class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="vacEdited('${tabNum}', ${c}, this)">${escapeHtml(val)}</div></td>`;
      }
    });
    vHTML += `</tr>`;
  }
  vbody.innerHTML = vHTML;
}

function renderTabelBody() {
  const year = parseInt(appState.year);
  const month = parseInt(appState.month);
  const days = daysInMonth(year, month);
  const tbody = document.getElementById("tabelBody");
  let bHTML = "";
  
  appState.employees.forEach((emp, rIndex) => {
    const tabNum = emp.tab_num || `empty_${rIndex}`;
    
    let isFullyExcluded = false;
    let excludeDayStart = null;
    if (emp.exclude_date) {
      const parts = emp.exclude_date.split('-');
      if (parts.length === 3) {
        const exY = parseInt(parts[0]);
        const exM = parseInt(parts[1]);
        const exD = parseInt(parts[2]);
        if (year > exY || (year === exY && month > exM)) {
          isFullyExcluded = true;
        } else if (year === exY && month === exM) {
          excludeDayStart = exD;
        }
      }
    }
    
    const trClass = isFullyExcluded ? "excluded" : "";
    bHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${rIndex})" ondragover="rowDragOver(event, ${rIndex})" ondrop="rowDrop(event, ${rIndex})">`;
    bHTML += `<td class="col-idx"><div class="rownum"><span>${rIndex + 1}</span></div></td>`;
    bHTML += `<td class="col-pos"><div class="cell" style="text-align: left;">${escapeHtml(emp.pos)}</div></td>`;
    bHTML += `<td class="col-fio"><div class="cell" style="text-align: left;">${escapeHtml(emp.name || emp.full_name)}</div></td>`;
    bHTML += `<td class="col-tab"><div class="cell center">${escapeHtml(emp.tab_num)}</div></td>`;
    
    const rowData = appState.timesheet[tabNum] || {};
    
    for (let d = 1; d <= days; d++) {
      const val = rowData[d] || "";
      let isCellExcluded = isFullyExcluded || (excludeDayStart && d >= excludeDayStart);
      const isWeekend = [0, 6].includes(new Date(year, month - 1, d).getDay());
      let tdClass = "col-day";
      if (isCellExcluded) tdClass += " excluded";
      
      let isH = false, isT = false;
      if (appState.system_dates) {
        isT = appState.system_dates.transfer.some(date => date[0] === month && date[1] === d);
        isH = appState.system_dates.holiday.some(date => date[0] === month && date[1] === d);
      }
      
      const cleanVal = String(val).trim().toUpperCase();
      
      if (cleanVal === "О" || cleanVal === "ДО") {
        tdClass += " bg-vacation";
      } else if (cleanVal === "К" || cleanVal === "У") {
        tdClass += " bg-trip";
      } else if (cleanVal === "Б" || cleanVal === "БН") {
        tdClass += " bg-ill";
      } else if ((isWeekend || isH || isT) && cleanVal !== "" && cleanVal !== "В" && cleanVal !== "B") {
        tdClass += " bg-work-weekend";
      } else if (isH) {
        tdClass += " bg-holiday";
      } else if (isWeekend || isT || cleanVal === "В" || cleanVal === "B") {
        tdClass += " bg-weekend";
      }
      
      const contentEditable = (CAN_EDIT && !isCellExcluded) ? 'contenteditable="true"' : '';
      let extraStyle = (cleanVal === "В" || cleanVal === "B") ? ' style="color: rgba(16, 32, 51, 0.2) !important;"' : "";
      bHTML += `<td class="${tdClass}"><div class="cell day-cell" ${contentEditable} oninput="cellEdited('${tabNum}', ${d}, this)"${extraStyle}>${escapeHtml(val)}</div></td>`;
    }
    
    bHTML += `</tr>`;
  });
  
  tbody.innerHTML = bHTML;
}

function cellEdited(tabNum, c, el) {
  if (!appState.timesheet[tabNum]) appState.timesheet[tabNum] = {};
  appState.timesheet[tabNum][c] = el.innerText.trim();
  markDirty(true);
  

}

function dataEdited(r, c, el) {
  if (!appState.ts_norms_data) appState.ts_norms_data = {};
  if (!appState.ts_norms_data[r]) appState.ts_norms_data[r] = {};
  appState.ts_norms_data[r][c] = el.innerText.trim();
  markDirty(true);
}

function empEdited(r, field, el) {
  if (!appState.employees[r]) appState.employees[r] = {pos:"", name:"", full_name:"", tab_num:"", milk:0, milk_issue:0, milk_note:"", exclude_date:""};
  if (field === 'milk' || field === 'milk_issue' || field === 'is_excluded') {
    appState.employees[r][field] = el.checked ? 1 : 0;
  } else if (field === 'exclude_date') {
    appState.employees[r][field] = el.value;
    renderTabelBody();
  } else {
    appState.employees[r][field] = el.innerText.trim();
  }
  markDirty(true);
}

function vacEdited(tabNum, c, el) {
  if (!appState.vacations) appState.vacations = {};
  if (!appState.vacations[tabNum]) appState.vacations[tabNum] = {};
  appState.vacations[tabNum][c] = el.innerText.trim();
  markDirty(true);
}

async function saveState() {
  if (!CAN_EDIT) return;
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  btn.textContent = "Сохранение...";
  
  try {
    const objTimesheet = {};
    appState.employees.forEach((emp, r) => {
      const tabNum = emp.tab_num || `empty_${r}`;
      objTimesheet[tabNum] = appState.timesheet[tabNum] || {};
    });
    
    const objVac = {};
    for (let r=0; r<11; r++) { 
        const emp = appState.employees[r] || {};
        const tabNum = emp.tab_num || `empty_${r}`;
        objVac[tabNum] = (appState.vacations && appState.vacations[tabNum]) || {}; 
    }
    const arrNorms = [];
    for (let r=0; r<12; r++) { arrNorms[r] = (appState.ts_norms_data && appState.ts_norms_data[r]) || {}; }

    // Clean empty employees from array end to avoid inflating DB
    let cleanEmployees = [...appState.employees];
    while(cleanEmployees.length > 0) {
      let last = cleanEmployees[cleanEmployees.length - 1];
      if (!last || (!last.name && !last.full_name && !last.tab_num && !last.pos)) {
        cleanEmployees.pop();
      } else {
        break;
      }
    }

    const payload = {
      year: appState.year,
      month: appState.month,
      employees: cleanEmployees,
      timesheet: objTimesheet,
      vacations: objVac,
      ts_norms_data: arrNorms,
      month_hint: appState.month_hint || ""
    };
    
    const res = await fetch(`${APP_PREFIX}/api/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    
    if (!res.ok) {
      let errMsg = `Save failed (HTTP ${res.status})`;
      try {
        const text = await res.text();
        try {
          const errData = JSON.parse(text);
          if (errData.error) errMsg = `Backend Error: ${errData.error}`;
          else if (errData.detail) errMsg = `FastAPI Error: ${errData.detail}`;
          else errMsg = `HTTP ${res.status}: ${text.substring(0, 100)}`;
        } catch (e) {
          errMsg = `HTTP ${res.status} HTML: ${text.substring(0, 100)}`;
        }
      } catch (e) {}
      throw new Error(errMsg);
    }
    markDirty(false);
  } catch (err) {
    console.error(err);
    alert("Ошибка сохранения: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = isDirty ? "Сохранить*" : "Сохранить";
  }
}

function exportMilk(type) {
  const year = document.getElementById("yearInput").value;
  const month = document.getElementById("monthInput").value;
  window.open(`${APP_PREFIX}/api/export-milk?year=${year}&month=${month}&type=${type}`, "_blank");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str).replace(/[&<>"']/g, function(m) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
  });
}

window.addEventListener('beforeunload', (e) => {
  if (isDirty && CAN_EDIT) {
    e.preventDefault();
    e.returnValue = '';
  }
});

let draggedRowIndex = -1;

function rowDragStart(event, rIndex) {
  if (!CAN_EDIT) return;
  draggedRowIndex = rIndex;
  event.dataTransfer.effectAllowed = 'move';
}

function rowDragOver(event, rIndex) {
  if (!CAN_EDIT) return;
  if (draggedRowIndex < 0 || draggedRowIndex === rIndex) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
}

function rowDrop(event, rIndex) {
  if (!CAN_EDIT) return;
  event.preventDefault();
  if (draggedRowIndex < 0 || draggedRowIndex === rIndex) return;
  
  const moved = appState.employees.splice(draggedRowIndex, 1)[0];
  appState.employees.splice(rIndex, 0, moved);
  
  draggedRowIndex = -1;
  markDirty(true);
  renderTable();
}

function closeReportModal() {
  document.getElementById("reportModal").style.display = "none";
  document.getElementById("reportIframe").src = "";
}

function exportSummary(type) {
  const year = document.getElementById("yearInput").value;
  const month = document.getElementById("monthInput").value;
  const url = `${APP_PREFIX}/api/export-summary?year=${year}&month=${month}&type=${encodeURIComponent(type)}`;
  document.getElementById("reportIframe").src = url;
  document.getElementById("reportModal").style.display = "block";
}

function updateExportMenu() {
  const panel = document.getElementById("exportMenuPanel");
  if (!panel) return;
  const hintText = appState.month_hint || "";
  const lines = hintText.split("\n");
  let optionsHTML = "";
  
  lines.forEach(line => {
    line = line.trim();
    if (!line) return;
    const match = line.match(/^([a-zA-Zа-яА-ЯёЁ]+)\s*[-—]\s*(.+)$/);
    if (match) {
      const code = match[1].trim().toUpperCase();
      let desc = match[2].trim();
      if (code !== "М" && code !== "M") { 
        const title = desc.charAt(0).toUpperCase() + desc.slice(1);
        optionsHTML += `<button onclick="exportSummary('${code}:${title.replace(/'/g, "\\'")}')">${escapeHtml(title)}</button>`;
      }
    }
  });

  if (!optionsHTML) {
    optionsHTML = `
      <button onclick="exportSummary('О:Отпуска')">Отпуска</button>
      <button onclick="exportSummary('ОВ:Отпуска внеплановые')">Отпуска внеплановые</button>
      <button onclick="exportSummary('ДО:Отпуск б/с')">Отпуск б/с</button>
      <button onclick="exportSummary('У:Учебный отпуск')">Учебный отпуск</button>
      <button onclick="exportSummary('Б:Больничный')">Больничный</button>
    `;
  }
  
  panel.innerHTML = optionsHTML;
}

function openSickModal() {
  const sel = document.getElementById("sickEmp");
  sel.innerHTML = "";
  appState.employees.forEach(emp => {
    if (emp && emp.name) {
      const opt = document.createElement("option");
      opt.value = emp.name;
      opt.textContent = emp.name;
      sel.appendChild(opt);
    }
  });
  const d = new Date();
  document.getElementById("sickStart").valueAsDate = d;
  document.getElementById("sickEnd").valueAsDate = d;
  document.getElementById("sickModal").style.display = "block";
}

function closeSickModal() {
  document.getElementById("sickModal").style.display = "none";
}

function generateSickEmail() {
  const emp = encodeURIComponent(document.getElementById("sickEmp").value);
  const type = encodeURIComponent(document.getElementById("sickType").value);
  const start = document.getElementById("sickStart").value;
  const end = document.getElementById("sickEnd").value;
  const email = encodeURIComponent(document.getElementById("sickEmail").value);
  
  window.open(`${APP_PREFIX}/api/export-sick-email?emp=${emp}&type=${type}&start=${start}&end=${end}&email=${email}`, "_blank");
  closeSickModal();
}


function parseVacationDate(str, defaultYear) {
  if (!str) return null;
  const parts = str.trim().split('.');
  if (parts.length < 2) return null;
  const d = parseInt(parts[0], 10);
  const m = parseInt(parts[1], 10);
  let y = defaultYear;
  if (parts.length >= 3) {
    if (parts[2].length === 2) y = 2000 + parseInt(parts[2], 10);
    else y = parseInt(parts[2], 10);
  }
  if (isNaN(d) || isNaN(m) || isNaN(y)) return null;
  return new Date(y, m - 1, d);
}

function applyVacations() {
  if (!appState || !appState.vacations || !appState.employees) return;
  const year = parseInt(appState.year);
  const month = parseInt(appState.month);
  const days = daysInMonth(year, month);
  
  let changed = false;

  appState.employees.forEach((emp, r) => {
    const tabNum = emp.tab_num || `empty_${r}`;
    const vacData = appState.vacations[tabNum];
    
    const vacDays = new Set();
    if (vacData) {
      const cols = [[1,2,3], [5,6,7], [9,10,11]];
      cols.forEach(pair => {
        const sDateStr = vacData[pair[0]];
        const eDateStr = vacData[pair[1]];
        
        const sDate = parseVacationDate(sDateStr, year);
        const eDate = parseVacationDate(eDateStr, year);
        
        if (sDate && eDate && eDate >= sDate) {
          let curr = new Date(sDate);
          while (curr <= eDate) {
            if (curr.getFullYear() === year) {
              const m = curr.getMonth() + 1;
              const d = curr.getDate();
              const isH = appState.system_dates && appState.system_dates.holiday && appState.system_dates.holiday.some(h => h[0] === m && h[1] === d);
              if (!isH) {
                vacDays.add(`${m}-${d}`);
              }
            }
            curr.setDate(curr.getDate() + 1);
          }
        }
      });
    }
    
    if (!appState.timesheet[tabNum]) appState.timesheet[tabNum] = {};
    for (let d = 1; d <= days; d++) {
      const isVac = vacDays.has(`${month}-${d}`);
      const currVal = appState.timesheet[tabNum][d] || "";
      
      const date = new Date(year, month - 1, d);
      const isWeekend = date.getDay() === 0 || date.getDay() === 6;
      let isH = false, isT = false;
      if (appState.system_dates) {
        isT = appState.system_dates.transfer.some(dt => dt[0] === month && dt[1] === d);
        isH = appState.system_dates.holiday.some(dt => dt[0] === month && dt[1] === d);
      }
      const isRestDay = isWeekend || isH || isT;
      
      if (isVac) {
        if (currVal !== "О" && currVal !== "ДО") {
          appState.timesheet[tabNum][d] = "О";
          changed = true;
        }
      } else {
        if (currVal === "О") {
          appState.timesheet[tabNum][d] = "";
          changed = true;
        }
        
        // Auto-fill "В" for empty rest days
        if (isRestDay && (!appState.timesheet[tabNum][d] || appState.timesheet[tabNum][d] === "")) {
          appState.timesheet[tabNum][d] = "В";
          changed = true;
        }
        // Auto-clear "В" if it's no longer a rest day (e.g. system_dates changed)
        else if (!isRestDay && appState.timesheet[tabNum][d] === "В") {
          appState.timesheet[tabNum][d] = "";
          changed = true;
        }
      }
    }
  });
  
  if (changed) {
    markDirty(true);
    renderTable();
  }
}

// --- Выделение нескольких ячеек ---
let isSelecting = false;
let startCell = null;
let currentSelectedCells = new Set();
let lastHoveredCell = null;

document.addEventListener('mousedown', function(e) {
  // Управление HTML5 drag-and-drop: строка перетаскивается только за номер
  const tr = e.target.closest('tr');
  if (tr && tr.hasAttribute('ondragstart')) {
    if (e.target.closest('.col-idx')) {
      tr.setAttribute('draggable', 'true');
    } else {
      tr.removeAttribute('draggable');
    }
  }

  const cell = e.target.closest('.day-cell');
  if (!cell || !CAN_EDIT) {
    if (!e.target.closest('.json-menu')) {
       clearSelection();
    }
    return;
  }
  if (e.button !== 0) return; 
  
  isSelecting = true;
  startCell = cell;
  lastHoveredCell = cell;
  selectRange(startCell, startCell);
});

document.addEventListener('mousemove', function(e) {
  if (!isSelecting || !startCell) return;
  
  // Используем elementFromPoint для обхода захвата мыши
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (!el) return;
  
  const cell = el.closest('.day-cell');
  if (!cell || !CAN_EDIT) return;
  
  if (cell !== lastHoveredCell) {
    selectRange(startCell, cell);
    lastHoveredCell = cell;
    
    // Снимаем стандартное выделение текста, чтобы не мешало
    window.getSelection().removeAllRanges();
  }
});

document.addEventListener('mouseup', function(e) {
  if (isSelecting && currentSelectedCells.size > 1) {
    if (startCell) {
      startCell.focus();
      const range = document.createRange();
      range.selectNodeContents(startCell);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  }
  isSelecting = false;
  lastHoveredCell = null;
});

function clearSelection() {
  currentSelectedCells.forEach(c => {
    c.classList.remove('multi-selected');
    c.style.boxShadow = '';
  });
  currentSelectedCells.clear();
}

function selectRange(start, end) {
  clearSelection();
  if (!start || !end) return;
  
  const tbody = start.closest('tbody');
  if (!tbody) return;
  const allRows = Array.from(tbody.querySelectorAll('tr'));
  
  const startTr = start.closest('tr');
  const startTd = start.closest('td');
  const endTr = end.closest('tr');
  const endTd = end.closest('td');
  
  const startRowIdx = allRows.indexOf(startTr);
  const endRowIdx = allRows.indexOf(endTr);
  
  const startTds = Array.from(startTr.querySelectorAll('td'));
  const endTds = Array.from(endTr.querySelectorAll('td'));
  
  const startColIdx = startTds.indexOf(startTd);
  const endColIdx = endTds.indexOf(endTd);
  
  const minRow = Math.min(startRowIdx, endRowIdx);
  const maxRow = Math.max(startRowIdx, endRowIdx);
  const minCol = Math.min(startColIdx, endColIdx);
  const maxCol = Math.max(startColIdx, endColIdx);
  
  for (let r = minRow; r <= maxRow; r++) {
    const rowTds = Array.from(allRows[r].querySelectorAll('td'));
    for (let c = minCol; c <= maxCol; c++) {
      const tdElement = rowTds[c];
      const cell = tdElement?.querySelector('.day-cell');
      if (cell && tdElement) {
        tdElement.classList.add('multi-selected');
        currentSelectedCells.add(tdElement);
        
        const shadows = [];
        if (r === minRow) shadows.push('inset 0 1.5px 0 0 #276ef1');
        if (r === maxRow) shadows.push('inset 0 -1.5px 0 0 #276ef1');
        if (c === minCol) shadows.push('inset 1.5px 0 0 0 #276ef1');
        if (c === maxCol) shadows.push('inset -1.5px 0 0 0 #276ef1');
        
        if (shadows.length > 0) {
          tdElement.style.setProperty('box-shadow', shadows.join(', '), 'important');
        } else {
          tdElement.style.boxShadow = '';
        }
      }
    }
  }
}

// Навигация по ячейкам как в Excel и копипаст
document.addEventListener('keydown', function(e) {
  const cell = e.target.closest('.cell');
  if (!cell || !CAN_EDIT) return;

  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (currentSelectedCells.size > 1) {
      e.preventDefault();
      currentSelectedCells.forEach(td => {
        const c = td.querySelector('.cell');
        if (c) {
          c.innerText = "";
          c.dispatchEvent(new Event('input', { bubbles: true }));
        }
      });
      return;
    }
  }

  const td = cell.closest('td');
  const tr = cell.closest('tr');
  if (!td || !tr) return;

  const tbody = tr.closest('tbody');
  const allRows = Array.from(tbody.querySelectorAll('tr'));
  const rowIndex = allRows.indexOf(tr);
  const allCellsInRow = Array.from(tr.querySelectorAll('td'));
  const colIndex = allCellsInRow.indexOf(td);

  let targetCell = null;

  if (e.key === 'ArrowUp') {
    e.preventDefault();
    const targetRow = allRows[rowIndex - 1];
    if (targetRow) targetCell = targetRow.querySelectorAll('td')[colIndex]?.querySelector('.cell');
  } else if (e.key === 'ArrowDown' || e.key === 'Enter') {
    e.preventDefault();
    const targetRow = allRows[rowIndex + 1];
    if (targetRow) targetCell = targetRow.querySelectorAll('td')[colIndex]?.querySelector('.cell');
  } else if (e.key === 'ArrowRight') {
    const sel = window.getSelection();
    if (sel.focusOffset === cell.innerText.length || cell.innerText.length === 0) {
      e.preventDefault();
      targetCell = allCellsInRow[colIndex + 1]?.querySelector('.cell');
    }
  } else if (e.key === 'ArrowLeft') {
    const sel = window.getSelection();
    if (sel.focusOffset === 0 || cell.innerText.length === 0) {
      e.preventDefault();
      targetCell = allCellsInRow[colIndex - 1]?.querySelector('.cell');
    }
  }

  if (targetCell) {
    clearSelection();
    targetCell.focus();
    const range = document.createRange();
    range.selectNodeContents(targetCell);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  } else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
    if (currentSelectedCells.size > 1) clearSelection();
  }
});

document.addEventListener('paste', function(e) {
  const cell = e.target.closest('.cell');
  if (!cell || !CAN_EDIT) return;

  e.preventDefault();
  const pasteData = (e.clipboardData || window.clipboardData).getData('text');
  
  const rows = pasteData.split(/\r?\n/);
  // Удаляем последнюю пустую строку, которую часто добавляет Excel
  if (rows.length > 0 && rows[rows.length - 1] === "") {
    rows.pop();
  }
  
  if (rows.length === 0) return;

  if (rows.length === 1 && rows[0].split('\t').length === 1) {
    const text = rows[0];
    if (currentSelectedCells.size > 1) {
      currentSelectedCells.forEach(td => {
        const c = td.querySelector('.cell');
        if (c) {
          c.innerText = text;
          c.dispatchEvent(new Event('input', { bubbles: true }));
        }
      });
    } else {
      document.execCommand('insertText', false, text);
    }
    return;
  }

  // Если это несколько ячеек (сетка)
  const td = cell.closest('td');
  const tr = cell.closest('tr');
  if (!td || !tr) return;
  
  const tbody = tr.closest('tbody');
  const allRows = Array.from(tbody.querySelectorAll('tr'));
  const startRowIndex = allRows.indexOf(tr);
  const allCellsInRow = Array.from(tr.querySelectorAll('td'));
  const startColIndex = allCellsInRow.indexOf(td);

  for (let i = 0; i < rows.length; i++) {
    const rowData = rows[i].split('\t');
    const targetRow = allRows[startRowIndex + i];
    if (!targetRow) break;
    
    const rowTds = Array.from(targetRow.querySelectorAll('td'));
    
    for (let j = 0; j < rowData.length; j++) {
      const targetTd = rowTds[startColIndex + j];
      if (!targetTd) break;
      
      const targetCell = targetTd.querySelector('.cell[contenteditable="true"]');
      if (targetCell) {
        targetCell.innerText = rowData[j].trim();
        targetCell.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
  }
});


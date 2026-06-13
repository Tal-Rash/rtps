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
  const year = parseInt(appState.year);
  const month = parseInt(appState.month);
  const days = daysInMonth(year, month);
  
  // Render Headers
  const thead = document.getElementById("tabelHeader");
  let hHTML = `<th class="col-idx">№</th><th class="col-pos">Должность</th><th class="col-fio">ФИО</th><th class="col-tab">Таб. №</th>`;
  for (let d = 1; d <= days; d++) {
    hHTML += `<th class="col-day">${String(d).padStart(2, '0')}</th>`;
  }
  hHTML += `<th class="col-total">Итого</th>`;
  thead.innerHTML = hHTML;
  
  // Render Body for Tabel
  const tbody = document.getElementById("tabelBody");
  let bHTML = "";
  
  appState.employees.forEach((emp, rIndex) => {
    bHTML += `<tr>`;
    bHTML += `<td class="col-idx"><div class="rownum"><span>${rIndex + 1}</span></div></td>`;
    bHTML += `<td class="col-pos"><div class="cell" style="text-align: left;">${escapeHtml(emp.pos)}</div></td>`;
    bHTML += `<td class="col-fio"><div class="cell" style="text-align: left;">${escapeHtml(emp.name || emp.full_name)}</div></td>`;
    bHTML += `<td class="col-tab"><div class="cell center">${escapeHtml(emp.tab_num)}</div></td>`;
    
    let total = 0;
    const rowData = appState.timesheet[rIndex] || {};
    
    for (let d = 1; d <= days; d++) {
      const val = rowData[d] || "";
      const isWeekend = [0, 6].includes(new Date(year, month - 1, d).getDay());
      let tdClass = "col-day";
      if (isWeekend) tdClass += " holiday-col";
      if (val === "В") tdClass += " holiday-col";
      if (val === "ОТ" || val === "О" || val === "ОВ" || val === "А" || val === "У") tdClass += " transfer-col";
      if (val === "Б") tdClass += " holiday-col";
      if (val.match(/^[0-9]+$/)) total += parseInt(val);
      
      const contentEditable = CAN_EDIT ? 'contenteditable="true"' : '';
      bHTML += `<td class="${tdClass}"><div class="cell day-cell" ${contentEditable} oninput="cellEdited(${rIndex}, ${d}, this)">${escapeHtml(val)}</div></td>`;
    }
    
    bHTML += `<td class="col-total" id="total_${rIndex}"><div class="cell center"><strong>${total}</strong></div></td>`;
    bHTML += `</tr>`;
  });
  
  tbody.innerHTML = bHTML;

  // Render Data (Norms)
  const dbody = document.getElementById("dataBody");
  let dHTML = "";
  const monthsNames = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  for (let r = 0; r < 12; r++) {
    dHTML += `<tr><td style="text-align: left;">${monthsNames[r]}</td>`;
    for (let c = 1; c < 8; c++) {
      const val = (appState.ts_norms_data && appState.ts_norms_data[r] && appState.ts_norms_data[r][c]) || "";
      dHTML += `<td class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="dataEdited(${r}, ${c}, this)">${escapeHtml(val)}</td>`;
    }
    dHTML += `</tr>`;
  }
  dbody.innerHTML = dHTML;

  // Render Employees
  const ebody = document.getElementById("employeesBody");
  let eHTML = "";
  // 11 rows
  for (let r = 0; r < 11; r++) {
    const emp = appState.employees[r] || {pos:"", name:"", full_name:"", tab_num:"", milk:0, milk_issue:0, milk_note:""};
    eHTML += `<tr>`;
    eHTML += `<td class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'pos', this)">${escapeHtml(emp.pos)}</td>`;
    eHTML += `<td class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'name', this)">${escapeHtml(emp.name)}</td>`;
    eHTML += `<td class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'full_name', this)">${escapeHtml(emp.full_name)}</td>`;
    eHTML += `<td class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'tab_num', this)">${escapeHtml(emp.tab_num)}</td>`;
    eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk', this)" ${emp.milk ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk_issue', this)" ${emp.milk_issue ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'milk_note', this)">${escapeHtml(emp.milk_note)}</td>`;
    eHTML += `</tr>`;
  }
  ebody.innerHTML = eHTML;

  // Render Vacations
  const vbody = document.getElementById("vacationsBody");
  let vHTML = "";
  // 11 rows
  for (let r = 0; r < 11; r++) {
    vHTML += `<tr>`;
    for (let c = 0; c < 13; c++) {
      if (c === 5 || c === 9) {
        vHTML += `<td style="background:#f0f0f0;"></td>`; // separator
      } else {
        const val = (appState.vacations && appState.vacations[r] && appState.vacations[r][c]) || "";
        vHTML += `<td class="cell" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="vacEdited(${r}, ${c}, this)">${escapeHtml(val)}</td>`;
      }
    }
    vHTML += `</tr>`;
  }
  vbody.innerHTML = vHTML;
}

function cellEdited(r, c, el) {
  if (!appState.timesheet[r]) appState.timesheet[r] = {};
  appState.timesheet[r][c] = el.innerText.trim();
  markDirty(true);
  
  let total = 0;
  const days = daysInMonth(appState.year, appState.month);
  for (let d = 1; d <= days; d++) {
    const v = appState.timesheet[r][d] || "";
    if (v.match(/^[0-9]+$/)) total += parseInt(v);
  }
  document.getElementById(`total_${r}`).innerHTML = `<strong>${total}</strong>`;
}

function dataEdited(r, c, el) {
  if (!appState.ts_norms_data) appState.ts_norms_data = {};
  if (!appState.ts_norms_data[r]) appState.ts_norms_data[r] = {};
  appState.ts_norms_data[r][c] = el.innerText.trim();
  markDirty(true);
}

function empEdited(r, field, el) {
  if (!appState.employees[r]) appState.employees[r] = {pos:"", name:"", full_name:"", tab_num:"", milk:0, milk_issue:0, milk_note:""};
  if (field === 'milk' || field === 'milk_issue') {
    appState.employees[r][field] = el.checked ? 1 : 0;
  } else {
    appState.employees[r][field] = el.innerText.trim();
  }
  markDirty(true);
}

function vacEdited(r, c, el) {
  if (!appState.vacations) appState.vacations = {};
  if (!appState.vacations[r]) appState.vacations[r] = {};
  appState.vacations[r][c] = el.innerText.trim();
  markDirty(true);
}

async function saveState() {
  if (!CAN_EDIT) return;
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  btn.textContent = "Сохранение...";
  
  try {
    const arrTimesheet = [];
    appState.employees.forEach((_, r) => {
      arrTimesheet[r] = appState.timesheet[r] || {};
    });
    
    // Convert objects to arrays for vacations and norms
    const arrVac = [];
    for (let r=0; r<11; r++) { arrVac[r] = (appState.vacations && appState.vacations[r]) || {}; }
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
      timesheet: arrTimesheet,
      employees: cleanEmployees,
      vacations: arrVac,
      ts_norms_data: arrNorms
    };
    
    const res = await fetch(`${APP_PREFIX}/api/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    
    if (!res.ok) throw new Error("Save failed");
    markDirty(false);
  } catch (err) {
    console.error(err);
    alert("Ошибка сохранения");
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

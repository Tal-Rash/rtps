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
  let hHTML = `<th>№</th><th>Должность</th><th>ФИО</th><th>Таб. №</th>`;
  for (let d = 1; d <= days; d++) {
    hHTML += `<th>${String(d).padStart(2, '0')}</th>`;
  }
  hHTML += `<th>Итого</th>`;
  thead.innerHTML = hHTML;
  
  // Render Body
  const tbody = document.getElementById("tabelBody");
  let bHTML = "";
  
  appState.employees.forEach((emp, rIndex) => {
    bHTML += `<tr>`;
    bHTML += `<td>${rIndex + 1}</td>`;
    bHTML += `<td>${escapeHtml(emp.pos)}</td>`;
    bHTML += `<td>${escapeHtml(emp.full_name)}</td>`;
    bHTML += `<td>${escapeHtml(emp.tab_num)}</td>`;
    
    let total = 0;
    const rowData = appState.timesheet[rIndex] || {};
    
    for (let d = 1; d <= days; d++) {
      const val = rowData[d] || "";
      const isWeekend = [0, 6].includes(new Date(year, month - 1, d).getDay());
      let classes = [];
      if (isWeekend) classes.push("cell-weekend");
      if (val === "В") classes.push("cell-weekend");
      if (val === "ОТ") classes.push("cell-vacation");
      if (val === "Б") classes.push("cell-sick");
      if (val.match(/^[0-9]+$/)) total += parseInt(val);
      
      const contentEditable = CAN_EDIT ? 'contenteditable="true"' : '';
      bHTML += `<td class="cell ${classes.join(' ')}" ${contentEditable} oninput="cellEdited(${rIndex}, ${d}, this)">${escapeHtml(val)}</td>`;
    }
    
    bHTML += `<td id="total_${rIndex}"><strong>${total}</strong></td>`;
    bHTML += `</tr>`;
  });
  
  tbody.innerHTML = bHTML;
}

function cellEdited(r, c, el) {
  if (!appState.timesheet[r]) appState.timesheet[r] = {};
  appState.timesheet[r][c] = el.innerText.trim();
  markDirty(true);
  
  // Recalculate total for row
  let total = 0;
  const days = daysInMonth(appState.year, appState.month);
  for (let d = 1; d <= days; d++) {
    const v = appState.timesheet[r][d] || "";
    if (v.match(/^[0-9]+$/)) total += parseInt(v);
  }
  document.getElementById(`total_${r}`).innerHTML = `<strong>${total}</strong>`;
}

async function saveState() {
  if (!CAN_EDIT) return;
  const btn = document.getElementById("saveBtn");
  btn.disabled = true;
  btn.textContent = "Сохранение...";
  
  try {
    // Transform timesheet back to array for sending
    const arrTimesheet = [];
    appState.employees.forEach((_, r) => {
      arrTimesheet[r] = appState.timesheet[r] || {};
    });
    
    const payload = {
      year: appState.year,
      month: appState.month,
      timesheet: arrTimesheet
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

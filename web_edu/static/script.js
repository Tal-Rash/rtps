const APP_PREFIX = window.APP_CONFIG.APP_PREFIX;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;

let appState = {
  columns: [],
  employees: [],
  trainings: {}
};

let currentMode = "dates"; // "dates" or "protocols"
let currentFilter = "all"; // "all", "workers", "itr"

window.addEventListener("DOMContentLoaded", () => {
  loadState();
});

async function loadState() {
  try {
    const res = await fetch(`${APP_PREFIX}/api/state`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appState = data;
    renderMatrix();
  } catch (err) {
    console.error(err);
  }
}

function setMode(mode) {
  currentMode = mode;
  document.getElementById("btnModeDates").classList.toggle("active", mode === "dates");
  document.getElementById("btnModeProtocols").classList.toggle("active", mode === "protocols");
  renderMatrix();
}

function setFilter(filter) {
  currentFilter = filter;
  document.getElementById("btnFilterAll").classList.toggle("active", filter === "all");
  document.getElementById("btnFilterWorkers").classList.toggle("active", filter === "workers");
  document.getElementById("btnFilterITR").classList.toggle("active", filter === "itr");
  renderMatrix();
}

function parseDateStr(str) {
  if (!str) return null;
  const parts = str.split("-");
  if (parts.length === 3) {
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }
  return null;
}

function addMonths(date, months) {
  let d = new Date(date);
  d.setMonth(d.getMonth() + months);
  return d;
}

function formatDate(date) {
  if (!date) return "";
  const d = String(date.getDate()).padStart(2, '0');
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const y = date.getFullYear();
  return `${d}.${m}.${y}`;
}

function renderMatrix() {
  const thead = document.getElementById("eduHead");
  const tbody = document.getElementById("eduBody");
  
  // Render Headers
  let hHTML = `<tr><th style="width:200px">ФИО работника</th><th style="width:70px">Таб. №</th><th style="width:150px">Должность</th>`;
  for (let c of appState.columns) {
    hHTML += `<th>${c.name}</th>`;
  }
  hHTML += `</tr>`;
  thead.innerHTML = hHTML;
  
  // Filter Employees
  let filteredEmployees = appState.employees;
  if (currentFilter === "workers") {
    filteredEmployees = appState.employees.filter(e => e.category !== "itr");
  } else if (currentFilter === "itr") {
    filteredEmployees = appState.employees.filter(e => e.category === "itr");
  }

  let bHTML = "";
  const today = new Date();
  today.setHours(0,0,0,0);
  
  for (let rIdx = 0; rIdx < filteredEmployees.length; rIdx++) {
    const emp = filteredEmployees[rIdx];
    bHTML += `<tr>`;
    bHTML += `<td>${emp.fio}</td>`;
    bHTML += `<td>${emp.tab_num}</td>`;
    bHTML += `<td>${emp.position}</td>`;
    
    const empTrainings = appState.trainings[emp.tab_num] || {};
    
    for (let cIdx = 0; cIdx < appState.columns.length; cIdx++) {
      const col = appState.columns[cIdx];
      const tInfo = empTrainings[col.name] || { last: null, period_months: col.period_months, protocol: "" };
      
      let cellText = "";
      let autoText = "";
      let cellClass = "";
      
      if (currentMode === "protocols") {
        cellText = tInfo.protocol || "";
      } else {
        if (tInfo.last) {
          const lastDate = parseDateStr(tInfo.last);
          if (lastDate) {
            const nextDate = addMonths(lastDate, tInfo.period_months);
            const isExpired = nextDate < today;
            const diffTime = nextDate - today;
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            const isSoon = !isExpired && diffDays <= 30;
            
            cellText = formatDate(lastDate);
            autoText = `<div class="auto-text">след аттестация:<br>${formatDate(nextDate)}`;
            if (isExpired) {
              cellClass = "bg-expired";
              autoText += "<br>(Просрочено)";
            } else if (isSoon) {
              cellClass = "bg-warning";
            }
            autoText += `</div>`;
          }
        }
      }
      
      const contentEditable = CAN_EDIT ? 'contenteditable="true"' : '';
      bHTML += `<td class="${cellClass}"><div class="cell" ${contentEditable} data-row="${rIdx}" data-col="${cIdx}">${cellText}</div>${autoText}</td>`;
    }
    bHTML += `</tr>`;
  }
  
  tbody.innerHTML = bHTML;
  
  if (CAN_EDIT) {
    attachCellListeners();
  }
}

function attachCellListeners() {
  const cells = document.querySelectorAll(".cell[contenteditable='true']");
  cells.forEach(c => {
    c.addEventListener("blur", onCellBlur);
    c.addEventListener("keydown", onCellKeydown);
  });
}

function onCellKeydown(e) {
  if (e.key === "Enter") {
    e.preventDefault();
    this.blur();
  }
}

async function onCellBlur(e) {
  const cell = e.target;
  const rIdx = parseInt(cell.dataset.row, 10);
  const cIdx = parseInt(cell.dataset.col, 10);
  let text = cell.innerText.trim();
  
  // Get the employee from filtered list since rIdx is the visual row index
  let filteredEmployees = appState.employees;
  if (currentFilter === "workers") {
    filteredEmployees = appState.employees.filter(emp => emp.category !== "itr");
  } else if (currentFilter === "itr") {
    filteredEmployees = appState.employees.filter(emp => emp.category === "itr");
  }
  const emp = filteredEmployees[rIdx];
  const col = appState.columns[cIdx];
  
  if (currentMode === "protocols") {
    // Save protocol
    try {
      const res = await fetch(`${APP_PREFIX}/api/save_protocol`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          tab_num: emp.tab_num,
          training_type: col.name,
          protocol: text
        })
      });
      if (!res.ok) throw new Error("Failed to save protocol");
      // update local state
      if (!appState.trainings[emp.tab_num]) appState.trainings[emp.tab_num] = {};
      if (!appState.trainings[emp.tab_num][col.name]) appState.trainings[emp.tab_num][col.name] = {period_months: col.period_months};
      appState.trainings[emp.tab_num][col.name].protocol = text;
    } catch (err) {
      console.error(err);
      alert("Ошибка сохранения: " + err.message);
    }
  } else {
    // Save dates
    // Just take the first line if it's already formatted
    let dateStr = text.split('\n')[0].trim();
    if (!dateStr) {
      try {
        const res = await fetch(`${APP_PREFIX}/api/save_training`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            tab_num: emp.tab_num,
            training_type: col.name,
            last_date: null,
            period_months: col.period_months
          })
        });
        if (!res.ok) throw new Error("Failed to clear date");
        if (appState.trainings[emp.tab_num] && appState.trainings[emp.tab_num][col.name]) {
          appState.trainings[emp.tab_num][col.name].last = null;
        }
        renderMatrix();
      } catch (err) {
        console.error(err);
        alert("Ошибка очистки: " + err.message);
      }
      return;
    }
    
    // Auto format dates
    let cleanText = dateStr.replace(/\D/g, "");
    if (cleanText.length === 6) {
      dateStr = `${cleanText.substring(0,2)}.${cleanText.substring(2,4)}.20${cleanText.substring(4,6)}`;
    } else if (cleanText.length === 8) {
      dateStr = `${cleanText.substring(0,2)}.${cleanText.substring(2,4)}.${cleanText.substring(4,8)}`;
    }
    
    // parse DD.MM.YYYY
    const parts = dateStr.split(".");
    if (parts.length !== 3) {
      // Ignore invalid date if not formatted
      return;
    }
    const y = parseInt(parts[2], 10);
    const m = parseInt(parts[1], 10);
    const d = parseInt(parts[0], 10);
    
    if (isNaN(y) || isNaN(m) || isNaN(d)) return;
    
    const isoDate = `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    
    try {
      const res = await fetch(`${APP_PREFIX}/api/save_training`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          tab_num: emp.tab_num,
          training_type: col.name,
          last_date: isoDate,
          period_months: col.period_months
        })
      });
      if (!res.ok) throw new Error("Failed to save date");
      
      if (!appState.trainings[emp.tab_num]) appState.trainings[emp.tab_num] = {};
      if (!appState.trainings[emp.tab_num][col.name]) appState.trainings[emp.tab_num][col.name] = {period_months: col.period_months};
      appState.trainings[emp.tab_num][col.name].last = isoDate;
      renderMatrix();
    } catch (err) {
      console.error(err);
      alert("Ошибка сохранения: " + err.message);
    }
  }
}

// Settings Modal Logic
let tempColumns = [];

function openSettingsModal() {
  if (!CAN_EDIT) {
    alert("Только редакторы могут настраивать колонки.");
    return;
  }
  // copy from state
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
      <td><input type="text" class="input" style="width:100%;" value="${col.name.replace(/"/g, '&quot;')}" onchange="updateSettingsCol(${idx}, 'name', this.value)"></td>
      <td><input type="number" class="input" style="width:100%; text-align:center;" value="${col.period_months}" onchange="updateSettingsCol(${idx}, 'period_months', this.value)"></td>
      <td><button class="btn btn-outline" style="padding: 4px 8px; font-size:12px; color:red; border-color:#ffcccc;" onclick="deleteSettingsRow(${idx})">🗑</button></td>
    </tr>`;
  });
  tbody.innerHTML = html;
}

function updateSettingsCol(idx, field, value) {
  if (field === 'period_months') value = parseInt(value, 10) || 12;
  tempColumns[idx][field] = value;
}

function addSettingsRow() {
  tempColumns.push({name: "Новый курс", period_months: 12});
  renderSettingsTable();
}

function deleteSettingsRow(idx) {
  if (confirm("Вы уверены, что хотите удалить эту колонку?")) {
    tempColumns.splice(idx, 1);
    renderSettingsTable();
  }
}

async function saveSettings() {
  try {
    const res = await fetch(`${APP_PREFIX}/api/settings/columns`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(tempColumns)
    });
    if (!res.ok) throw new Error("Failed to save settings");
    closeSettingsModal();
    loadState();
  } catch (err) {
    console.error(err);
    alert("Ошибка сохранения настроек: " + err.message);
  }
}

// Copy/Paste logic (basic)
document.addEventListener("paste", async (e) => {
  if (!CAN_EDIT) return;
  const activeEl = document.activeElement;
  if (!activeEl || !activeEl.classList.contains("cell")) return;
  
  e.preventDefault();
  const pasteData = (e.clipboardData || window.clipboardData).getData("text");
  if (!pasteData) return;
  
  const lines = pasteData.trim().split("\n");
  const startRow = parseInt(activeEl.dataset.row, 10);
  const startCol = parseInt(activeEl.dataset.col, 10);
  
  let hasUpdates = false;
  for (let i = 0; i < lines.length; i++) {
    const cells = lines[i].split("\t");
    for (let j = 0; j < cells.length; j++) {
      const rIdx = startRow + i;
      const cIdx = startCol + j;
      const targetCell = document.querySelector(`.cell[data-row="${rIdx}"][data-col="${cIdx}"]`);
      if (targetCell) {
        targetCell.innerText = cells[j].trim();
        await onCellBlur({target: targetCell});
      }
    }
  }
});

  // Category Modal Logic
  let tempCategories = {};

  function openCategoryModal() {
    if (!CAN_EDIT) {
      alert("Только редакторы могут менять категории.");
      return;
    }
    // Extract unique positions from employees
    const posSet = new Set();
    tempCategories = {};
    appState.employees.forEach(e => {
      if (e.position) {
        posSet.add(e.position);
        if (!tempCategories[e.position]) {
          tempCategories[e.position] = e.category || "workers";
        }
      }
    });

    const tbody = document.getElementById("categoryTableBody");
    let html = "";
    Array.from(posSet).sort().forEach(pos => {
      const cat = tempCategories[pos] || "workers";
      html += `<tr>
        <td>${pos}</td>
        <td>
          <select class="num" onchange="tempCategories['${pos}'] = this.value">
            <option value="workers" ${cat === "workers" ? "selected" : ""}>Рабочий</option>
            <option value="itr" ${cat === "itr" ? "selected" : ""}>ИТР</option>
          </select>
        </td>
      </tr>`;
    });
    tbody.innerHTML = html;
    document.getElementById("categoryModal").style.display = "flex";
  }

  function closeCategoryModal() {
    document.getElementById("categoryModal").style.display = "none";
  }

  async function saveCategories() {
    try {
      const res = await fetch(`${APP_PREFIX}/api/settings/categories`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(tempCategories)
      });
      if (!res.ok) throw new Error("Failed to save categories");
      closeCategoryModal();
      loadState();
    } catch (err) {
      console.error(err);
      alert("Ошибка сохранения: " + err.message);
    }
  }

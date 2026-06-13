import re

script_path = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(script_path, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Remove total column from headers
old_header = """  let hHTML = `<th class="col-idx">№</th><th class="col-pos">Должность</th><th class="col-fio">ФИО</th><th class="col-tab">Таб. №</th>`;
  for (let d = 1; d <= days; d++) {
    hHTML += `<th class="col-day">${String(d).padStart(2, '0')}</th>`;
  }
  hHTML += `<th class="col-total">Итого</th>`;
  thead.innerHTML = hHTML;"""
new_header = """  let hHTML = `<th class="col-idx">№</th><th class="col-pos">Должность</th><th class="col-fio">ФИО</th><th class="col-tab">Таб. №</th>`;
  for (let d = 1; d <= days; d++) {
    hHTML += `<th class="col-day">${String(d).padStart(2, '0')}</th>`;
  }
  thead.innerHTML = hHTML;"""
text = text.replace(old_header, new_header)

# 2. Remove total from body
old_body_total = """    bHTML += `<td class="col-total" id="total_${tabNum}"><div class="cell center"><strong>${total}</strong></div></td>`;
    bHTML += `</tr>`;"""
new_body_total = """    bHTML += `</tr>`;"""
text = text.replace(old_body_total, new_body_total)

# 3. Remove total update in cellEdited
old_cell_edited = """  let total = 0;
  const days = daysInMonth(appState.year, appState.month);
  for (let d = 1; d <= days; d++) {
    const v = appState.timesheet[tabNum][d] || "";
    if (v.match(/^[0-9]+$/)) total += parseInt(v);
  }
  document.getElementById(`total_${tabNum}`).innerHTML = `<div class="cell center"><strong>${total}</strong></div>`;"""
text = text.replace(old_cell_edited, "")

# 4. Add applyVacations logic and hook it into switchTab
vacation_logic = """
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
    if (!vacData) return;
    
    const vacDays = new Set();
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
    
    if (!appState.timesheet[tabNum]) appState.timesheet[tabNum] = {};
    for (let d = 1; d <= days; d++) {
      const isVac = vacDays.has(`${month}-${d}`);
      const currVal = appState.timesheet[tabNum][d] || "";
      if (isVac) {
        if (currVal !== "О" && currVal !== "ДО") {
          appState.timesheet[tabNum][d] = "О";
          changed = true;
        }
      } else if (currVal === "О") {
        appState.timesheet[tabNum][d] = "";
        changed = true;
      }
    }
  });
  
  if (changed) {
    markDirty(true);
    renderTable();
  }
}
"""

old_switch_tab = """function switchTab(tabId) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  
  event.currentTarget.classList.add('active');
  document.getElementById('tab-' + tabId).classList.add('active');
}"""

new_switch_tab = """function switchTab(tabId) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  
  event.currentTarget.classList.add('active');
  document.getElementById('tab-' + tabId).classList.add('active');
  
  if (tabId === 'months') {
    applyVacations();
  }
}"""

if vacation_logic not in text:
    text += "\n" + vacation_logic
text = text.replace(old_switch_tab, new_switch_tab)

with open(script_path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed script.js")

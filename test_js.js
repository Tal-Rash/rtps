const appState = {
  year: "2026",
  month: "6",
  employees: [{ tab_num: "123" }],
  vacations: { "123": { 1: "10.06", 2: "14.06", 3: "" } },
  timesheet: { "123": { 10: "О", 11: "О", 12: "О", 13: "О", 14: "О" } },
  system_dates: { holiday: [[6, 12]] }
};

function daysInMonth(y, m) { return new Date(y, m, 0).getDate(); }

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
}

applyVacations();
console.log(appState.timesheet["123"]);

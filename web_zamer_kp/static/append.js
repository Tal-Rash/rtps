// Schedule fetch
async function loadSchedule() {
  const statusEl = document.getElementById('scheduleStatus');
  const tbody = document.getElementById('scheduleBody');
  if (statusEl) statusEl.textContent = 'Загрузка...';
  if (tbody) tbody.innerHTML = '';
  try {
    const res = await fetch('/grafik-ppr/api/state');
    if (!res.ok) throw new Error('Ошибка загрузки графика ППР');
    const grafikState = await res.json();
    renderSchedule(grafikState);
    if (statusEl) statusEl.textContent = '';
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
    console.error(err);
  }
}

function renderSchedule(grafikState) {
  const KP_RECHECK_DAYS = 30;
  const tbody = document.getElementById('scheduleBody');
  if (!tbody) return;

  function unitKeyFromCells(s, n) {
    let series = (s || '').trim();
    if (!series) series = 'ТЭМ-2УМ';
    const num = (n || '').trim();
    if (!num) return '';
    return series + ' №' + num;
  }

  function repairDateTime(date) {
    return date.getTime();
  }

  function addRepairDays(date, days) {
    const d = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    d.setDate(d.getDate() + days);
    return d;
  }
  
  function latestKpMeasurementByUnit(appState) {
    const map = new Map();
    if (!appState.repair_summary || !appState.repair_summary.kp_measurements) return map;
    for (const m of appState.repair_summary.kp_measurements) {
      if (!m.measurement_date) continue;
      const unitKey = unitKeyFromCells(m.locomotive?.split('№')[0], m.locomotive?.split('№')[1]);
      if (!unitKey) continue;
      const t = new Date(m.measurement_date + 'T00:00:00').getTime();
      if (isNaN(t)) continue;
      if (!map.has(unitKey) || t > map.get(unitKey).time) {
        map.set(unitKey, { dateStr: m.measurement_date, time: t });
      }
    }
    return map;
  }

  const latestByUnit = latestKpMeasurementByUnit(grafikState);
  const units = new Map();
  (grafikState.months || []).forEach((month) => {
    const monthNumber = month.month;
    (month.rows || []).forEach((row) => {
      const unitKey = unitKeyFromCells(row.series, row.number);
      if (!unitKey) return;
      if (!units.has(unitKey)) {
        units.set(unitKey, { series: row.series || 'ТЭМ-2УМ', number: row.number, repairs: [] });
      }
      for (let col = 4; col <= 34; col++) {
        const cell = row['col' + col];
        if (cell && typeof cell === 'object' && cell.v) {
          const v = typeof cell.v === 'string' ? cell.v.trim().toUpperCase() : '';
          const p = typeof cell.p === 'string' ? cell.p.trim().toUpperCase() : '';
          const repairType = v || p;
          if (['ТО3', 'ТР1', 'ТР', 'ТР2', 'ТР3', 'СР', 'КР'].includes(repairType)) {
            const day = col - 3;
            const candidateDate = new Date(Number(grafikState.year), monthNumber - 1, day);
            const candidateTime = repairDateTime(candidateDate);
            units.get(unitKey).repairs.push({ date: candidateDate, time: candidateTime, type: repairType });
          }
        }
      }
    });
  });

  const bestByUnit = new Map();
  units.forEach((unitData, unitKey) => {
    const lastMeas = latestByUnit.get(unitKey);
    if (!lastMeas) return;
    const limitDate = new Date(lastMeas.time);
    limitDate.setDate(limitDate.getDate() + KP_RECHECK_DAYS);
    const limitTime = limitDate.getTime();
    let bestRepair = null;
    let bestRepairTime = 0;
    for (const r of unitData.repairs) {
      if (r.time > lastMeas.time && r.time <= limitTime) {
        if (!bestRepair || r.time > bestRepairTime) {
          bestRepair = r;
          bestRepairTime = r.time;
        }
      }
    }
    bestByUnit.set(unitKey, {
      series: unitData.series,
      number: unitData.number,
      lastDateStr: lastMeas.dateStr,
      limitDate: limitDate,
      bestRepair: bestRepair
    });
  });

  const rows = [];
  bestByUnit.forEach((data, key) => rows.push(data));
  rows.sort((a, b) => {
    return a.limitDate.getTime() - b.limitDate.getTime();
  });

  const todayTime = new Date().setHours(0,0,0,0);
  
  tbody.innerHTML = rows.map(r => {
    const limitStr = r.limitDate.toLocaleDateString('ru-RU');
    const isOverdue = r.limitDate.getTime() < todayTime;
    const bestStr = r.bestRepair ? r.bestRepair.date.toLocaleDateString('ru-RU') + ' (' + r.bestRepair.type + ')' : '<span style="color:red">Не найден подходящий ремонт</span>';
    return '<tr ' + (isOverdue ? 'style="background-color:#ffebee"' : '') + '>' +
      '<td>' + esc(r.series) + '</td>' +
      '<td>' + esc(r.number) + '</td>' +
      '<td>' + esc(r.lastDateStr) + '</td>' +
      '<td ' + (isOverdue ? 'style="color:red; font-weight:bold"' : '') + '>' + limitStr + '</td>' +
      '<td>' + bestStr + '</td>' +
    '</tr>';
  }).join('');
}

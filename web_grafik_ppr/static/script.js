const BOOT_VERSION = window.APP_CONFIG.APP_VERSION;
let appState = window.APP_CONFIG.STATE_JSON;
const EMPLOYEE_NAMES = window.APP_CONFIG.EMPLOYEE_NAMES;
const EMPLOYEE_VACATIONS = window.APP_CONFIG.EMPLOYEE_VACATIONS || {};
let ui = {
  section: 'months',
  modal: null,
  monthIndex: new Date().getMonth(),
  mode: 'plan',
  selected: { months: null, norms: null },
  monthSelection: null,
  draggingSelection: false,
  repairScheduleSelection: null,
  repairScheduleDragging: false,
  repairPeriodicitySelection: null,
  repairPeriodicityDragging: false,
  repairSummary: {
    source: 'months',
    locomotive: '',
    dateFrom: '',
    dateTo: '',
    types: [],
  },
  lastCell: null,
  tu28MonthIndex: new Date().getMonth(),
  tu28RowIndex: null,
  tu28Staff: {},
  tu28ExtraRepairs: {}
};
let dirty = false;
let savedAppState = null;
let savedMonthsState = null;
let canceledMonthsState = null;
const CAN_EDIT = window.APP_CONFIG.CAN_EDIT;
const TEM_NORM_ROWS = window.APP_CONFIG.TEM_NORM_ROWS;
const AGR_NORM_ROWS = window.APP_CONFIG.AGR_NORM_ROWS;
const REPAIR_AUTO_FILL_DAYS = {"ТО3": 1, "ТР1": 4, "ТР": 4, "ТР2": 9, "ТР3": 14};
const REPAIR_SCHEDULE_COLUMN_CODES = ['ТР1', 'ТР2', 'ТР1', 'ТР3', 'ТР1', 'ТР2', 'ТР1', 'СР', 'ТР1', 'ТР2', 'ТР1', 'ТР3', 'ТР1', 'ТР2', 'ТР1', 'КР'];
const REPAIR_PERIODICITY_COLUMNS = ['TP1', 'TP2', 'TP3', 'CP', 'KP'];
const REPAIR_PERIODICITY_DEFAULT_SERIES = ['ТЭМ-2УМ', 'ТЭМ-2', ''];
const REPAIR_SUMMARY_FIXED_HOLIDAYS = new Set([
  '01-01', '01-02', '01-03', '01-04', '01-05', '01-06', '01-07', '01-08',
  '02-23', '03-08', '05-01', '05-09', '06-12', '11-04',
]);
const KP_RECHECK_DAYS = 30;
const sections = [{id:'repairSchedule',label:'График ремонтов'},{id:'repairSummary',label:'Сводка'},{id:'norms',label:'Нормы / парк'},{id:'acts',label:'Акты'},{id:'tu28',label:'ТУ-28'}];
let leaveGuardInstalled = false;
let pendingLeaveAction = null;

function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
function normalizeRepairCode(v){
  const map = {A:'А', B:'В', C:'С', E:'Е', H:'Н', K:'К', M:'М', O:'О', P:'Р', T:'Т', X:'Х', Y:'У'};
  return String(v ?? '')
    .trim()
    .toUpperCase()
    .replace(/\\s+/g, '')
    .replace(/-/g, '')
    .replace(/[ABCEHKMOPTXY]/g, (ch) => map[ch] || ch);
}
function setStatus(t){ void t; }
function closeJsonMenu(){
  const wrap = document.getElementById('jsonMenuWrap');
  const panel = document.getElementById('jsonMenuPanel');
  if (wrap) wrap.classList.remove('open');
  if (panel) panel.setAttribute('aria-hidden', 'true');
}
function toggleJsonMenu(event){
  if (event) event.stopPropagation();
  const wrap = document.getElementById('jsonMenuWrap');
  const panel = document.getElementById('jsonMenuPanel');
  if (!wrap || !panel) return;
  const open = !wrap.classList.contains('open');
  wrap.classList.toggle('open', open);
  panel.setAttribute('aria-hidden', open ? 'false' : 'true');
}
function triggerImportJson(){
  const input = document.getElementById('importFile');
  if (input) input.click();
  closeJsonMenu();
}
function showErrorModal(message){
  const modal = document.getElementById('errorModal');
  const body = document.getElementById('errorModalBody');
  if (!modal || !body) return;
  body.innerHTML = `<div class="error-modal-text" tabindex="0">${esc(message || 'Неизвестная ошибка')}</div>`;
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
}
function closeErrorModal(){
  const modal = document.getElementById('errorModal');
  if (!modal) return;
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
}
function markDirty(v=true){ dirty=v; updateSaveButtonState(); }
function updateSaveButtonState(){
  const btn = document.getElementById('saveButton');
  if (!btn) return;
  btn.classList.toggle('save-ready', !!dirty && !!CAN_EDIT);
}
function cloneState(value){
  return value ? JSON.parse(JSON.stringify(value)) : null;
}
function updateHistoryButtons(){
  const cancelBtn = document.getElementById('cancelButton');
  const restoreBtn = document.getElementById('restoreButton');
  if (cancelBtn) cancelBtn.style.display = '';
  if (restoreBtn) restoreBtn.style.display = '';
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || !savedMonthsState;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledMonthsState;
}
function ensureLeaveGuard(){
  if (!CAN_EDIT || leaveGuardInstalled) return;
  history.pushState({leaveGuard:true}, '', location.href);
  leaveGuardInstalled = true;
}
function openLeaveModal(message, action){
  pendingLeaveAction = action;
  const modal = document.getElementById('leaveModal');
  const body = document.getElementById('leaveMessage');
  if (body) body.textContent = message || 'Есть несохранённые изменения.';
  if (!modal) return;
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
}
function closeLeaveModal(){
  const modal = document.getElementById('leaveModal');
  if (!modal) return;
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
}
async function resolveLeaveChoice(shouldSave){
  const action = pendingLeaveAction;
  if (!action) return;
  if (shouldSave && dirty && CAN_EDIT) {
    await saveState({refreshReport:false});
    if (dirty) return;
  }
  pendingLeaveAction = null;
  closeLeaveModal();
  await action();
}
function promptLeave(message, action){
  if (!dirty || !CAN_EDIT) {
    action();
    return false;
  }
  openLeaveModal(message, action);
  return false;
}
function setLastCell(el){
  if (!el || !el.dataset) return;
  ui.lastCell = {
    table: el.dataset.table,
    row: Number(el.dataset.row),
    col: Number(el.dataset.col),
    path: el.dataset.path,
  };
}
function getMonthCellInfo(el){
  if (!el || !el.dataset || el.dataset.month === undefined) return null;
  const monthIndex = Number(el.dataset.month);
  const row = Number(el.dataset.row);
  const col = Number(el.dataset.col);
  if (!Number.isFinite(monthIndex) || !Number.isFinite(row) || !Number.isFinite(col)) return null;
  return { monthIndex, table: el.dataset.table, row, col, path: el.dataset.path };
}
function getGridCellInfo(el){
  if (!el || !el.dataset || !el.dataset.grid) return null;
  const row = Number(el.dataset.row);
  const col = Number(el.dataset.col);
  if (!Number.isFinite(row) || !Number.isFinite(col)) return null;
  return { grid: String(el.dataset.grid), row, col, path: el.dataset.path };
}
function selectionBounds(a, b){
  return {
    startRow: Math.min(a.row, b.row),
    endRow: Math.max(a.row, b.row),
    startCol: Math.min(a.col, b.col),
    endCol: Math.max(a.col, b.col),
  };
}
function clearMonthSelection(){
  ui.monthSelection = null;
  applyMonthSelectionClasses();
}
function setMonthSelection(anchor, focus){
  if (!anchor || !focus || anchor.monthIndex !== focus.monthIndex || anchor.table !== focus.table) return;
  ui.monthSelection = {
    monthIndex: anchor.monthIndex,
    table: anchor.table,
    anchor,
    focus,
    ...selectionBounds(anchor, focus),
  };
  applyMonthSelectionClasses();
}
function applyMonthSelectionClasses(){
  document.querySelectorAll('input.selected-cell').forEach((el) => {
    el.classList.remove('selected-cell');
    el.style.removeProperty('box-shadow');
  });
  if (ui.section !== 'months' || !ui.monthSelection) return;
  const sel = ui.monthSelection;
  document.querySelectorAll(`input[data-month="${sel.monthIndex}"][data-table="${sel.table}"]`).forEach((el) => {
    const row = Number(el.dataset.row);
    const col = Number(el.dataset.col);
    if (row >= sel.startRow && row <= sel.endRow && col >= sel.startCol && col <= sel.endCol) {
      el.classList.add('selected-cell');
      const shadows = [];
      if (row === sel.startRow) shadows.push('inset 0 1.5px 0 0 #276ef1');
      if (row === sel.endRow) shadows.push('inset 0 -1.5px 0 0 #276ef1');
      if (col === sel.startCol) shadows.push('inset 1.5px 0 0 0 #276ef1');
      if (col === sel.endCol) shadows.push('inset -1.5px 0 0 0 #276ef1');
      if (shadows.length > 0) {
        el.style.setProperty('box-shadow', shadows.join(', '), 'important');
      } else {
        el.style.boxShadow = '';
      }
    }
  });
}
function isMonthSelectionTarget(el){
  const info = getMonthCellInfo(el);
  return !!info && ui.section === 'months';
}
function beginMonthSelection(e){
  if (!CAN_EDIT || e.button !== 0) return;
  const target = e.currentTarget || e.target;
  const info = getMonthCellInfo(target);
  if (!info || ui.section !== 'months') return;
  e.preventDefault();
  setLastCell(target);
  const keepAnchor = e.shiftKey && ui.monthSelection && ui.monthSelection.monthIndex === info.monthIndex && ui.monthSelection.table === info.table;
  const anchor = keepAnchor ? ui.monthSelection.anchor : info;
  setMonthSelection(anchor, info);
  ui.draggingSelection = true;
  focusCell(target);
}
function extendMonthSelection(e){
  if (!ui.draggingSelection || ui.section !== 'months') return;
  const target = e.currentTarget || e.target;
  const info = getMonthCellInfo(target);
  if (!info || !ui.monthSelection) return;
  const anchor = ui.monthSelection.anchor;
  if (anchor.monthIndex !== info.monthIndex || anchor.table !== info.table) return;
  setMonthSelection(anchor, info);
}
function endMonthSelection(){
  ui.draggingSelection = false;
}
function selectedMonthCellText(info){
  const month = appState.months[info.monthIndex];
  if (!month) return '';
  const row = month[info.table] && month[info.table][info.row];
  if (!row || !row.cells) return '';
  return String(row.cells[info.col] ?? '');
}
function repairGridBounds(a, b){
  return {
    startRow: Math.min(a.row, b.row),
    endRow: Math.max(a.row, b.row),
    startCol: Math.min(a.col, b.col),
    endCol: Math.max(a.col, b.col),
  };
}
function getRepairScheduleSelection(){
  return ui.section === 'repairSchedule' ? ui.repairScheduleSelection : null;
}
function getRepairPeriodicitySelection(){
  return ui.repairPeriodicitySelection;
}
function setRepairScheduleSelection(anchor, focus){
  if (!anchor || !focus) return;
  ui.repairScheduleSelection = { anchor, focus, ...repairGridBounds(anchor, focus) };
  applyRepairScheduleSelectionClasses();
}
function setRepairPeriodicitySelection(anchor, focus){
  if (!anchor || !focus) return;
  ui.repairPeriodicitySelection = { anchor, focus, ...repairGridBounds(anchor, focus) };
  applyRepairPeriodicitySelectionClasses();
}
function clearRepairScheduleSelection(){
  ui.repairScheduleSelection = null;
  applyRepairScheduleSelectionClasses();
}
function clearRepairPeriodicitySelection(){
  ui.repairPeriodicitySelection = null;
  applyRepairPeriodicitySelectionClasses();
}
function applyGridSelectionClasses(grid, selection){
  document.querySelectorAll(`input.selected-cell[data-grid="${grid}"]`).forEach((el) => {
    el.classList.remove('selected-cell');
    el.style.removeProperty('box-shadow');
  });
  if (!selection) return;
  document.querySelectorAll(`input[data-grid="${grid}"]`).forEach((el) => {
    const row = Number(el.dataset.row);
    const col = Number(el.dataset.col);
    if (row >= selection.startRow && row <= selection.endRow && col >= selection.startCol && col <= selection.endCol) {
      el.classList.add('selected-cell');
      const shadows = [];
      if (row === selection.startRow) shadows.push('inset 0 1.5px 0 0 #276ef1');
      if (row === selection.endRow) shadows.push('inset 0 -1.5px 0 0 #276ef1');
      if (col === selection.startCol) shadows.push('inset 1.5px 0 0 0 #276ef1');
      if (col === selection.endCol) shadows.push('inset -1.5px 0 0 0 #276ef1');
      if (shadows.length > 0) {
        el.style.setProperty('box-shadow', shadows.join(', '), 'important');
      } else {
        el.style.boxShadow = '';
      }
    }
  });
}
function applyRepairScheduleSelectionClasses(){
  applyGridSelectionClasses('repair-schedule', ui.section === 'repairSchedule' ? ui.repairScheduleSelection : null);
}
function applyRepairPeriodicitySelectionClasses(){
  applyGridSelectionClasses('repair-periodicity', ui.repairPeriodicitySelection);
}
function repairScheduleGridText(info){
  const schedule = normalizeRepairSchedule();
  const objIndex = Math.floor(info.row / 2);
  const isFact = info.row % 2 === 1;
  const row = schedule.objects && schedule.objects[objIndex];
  if (!row) return '';
  if (info.col === 0) return String((row.kr && (isFact ? row.kr.fact : row.kr.plan)) ?? '');
  const idx = info.col - 1;
  const source = isFact ? row.fact : row.plan;
  return String(source && source[idx] !== undefined ? source[idx] : '');
}
function repairPeriodicityGridText(info){
  const periodicity = normalizeRepairPeriodicity();
  if (info.row < 0 || info.row >= periodicity.series.length) return '';
  if (info.col === 0) return String(periodicity.series[info.row] ?? '');
  return String((periodicity.values[info.row] && periodicity.values[info.row][info.col - 1]) ?? '');
}
function getGridSelectionText(grid, selection){
  if (!selection) return '';
  const lines = [];
  for (let row = selection.startRow; row <= selection.endRow; row++) {
    const values = [];
    for (let col = selection.startCol; col <= selection.endCol; col++) {
      values.push(grid === 'repair-schedule'
        ? repairScheduleGridText({ row, col })
        : repairPeriodicityGridText({ row, col }));
    }
    lines.push(values.join('\t'));
  }
  return lines.join('\n');
}
function writeGridCellValue(grid, row, col, value){
  const selector = `input[data-grid="${grid}"][data-row="${row}"][data-col="${col}"]`;
  const cell = document.querySelector(selector);
  if (!cell) return false;
  const normalized = value ?? '';
  cell.value = normalized;
  setPath(cell.dataset.path, normalized);
  return true;
}
function clearGridSelectionValues(grid, selection){
  if (!selection) return false;
  let changed = false;
  for (let row = selection.startRow; row <= selection.endRow; row++) {
    for (let col = selection.startCol; col <= selection.endCol; col++) {
      changed = writeGridCellValue(grid, row, col, '') || changed;
    }
  }
  return changed;
}
function pasteGridSelectionText(grid, target, text){
  if (!CAN_EDIT) return;
  const info = getGridCellInfo(target);
  if (!info || info.grid !== grid) return;
  const rows = String(text ?? '').replace(/\r/g, '').split('\n');
  while (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  const matrix = rows.map((line) => line.split('\t'));
  const sel = grid === 'repair-schedule' ? getRepairScheduleSelection() : getRepairPeriodicitySelection();
  const useSelection = !!(sel && sel.anchor && sel.focus);
  const startRow = useSelection ? sel.startRow : info.row;
  const startCol = useSelection ? sel.startCol : info.col;
  const sourceRows = matrix.length;
  const sourceCols = Math.max(...matrix.map((row) => row.length), 1);
  const targetRows = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endRow - sel.startRow + 1)
    : sourceRows;
  const targetCols = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endCol - sel.startCol + 1)
    : sourceCols;
  const fillSingle = matrix.length === 1 && matrix[0].length === 1 && useSelection;
  for (let r = 0; r < targetRows; r++) {
    for (let c = 0; c < targetCols; c++) {
      const sourceRow = fillSingle ? 0 : Math.min(r, matrix.length - 1);
      const sourceCol = fillSingle ? 0 : Math.min(c, matrix[sourceRow].length - 1);
      const value = matrix[sourceRow][sourceCol] ?? '';
      writeGridCellValue(grid, startRow + r, startCol + c, value);
    }
  }
  if (useSelection) {
    const nextFocus = { row: startRow + targetRows - 1, col: startCol + targetCols - 1 };
    if (grid === 'repair-schedule') setRepairScheduleSelection(sel.anchor, nextFocus);
    if (grid === 'repair-periodicity') setRepairPeriodicitySelection(sel.anchor, nextFocus);
  }
  updateRepairScheduleDerivedValues();
  markDirty(true);
  render();
}
function beginGridSelection(grid, e){
  if (!CAN_EDIT || e.button !== 0) return;
  const target = e.currentTarget || e.target;
  const info = getGridCellInfo(target);
  if (!info || info.grid !== grid) return;
  e.preventDefault();
  setLastCell(target);
  const currentSel = grid === 'repair-schedule' ? getRepairScheduleSelection() : getRepairPeriodicitySelection();
  const keepAnchor = e.shiftKey && currentSel && currentSel.anchor;
  const anchor = keepAnchor ? currentSel.anchor : info;
  if (grid === 'repair-schedule') setRepairScheduleSelection(anchor, info);
  if (grid === 'repair-periodicity') setRepairPeriodicitySelection(anchor, info);
  if (grid === 'repair-schedule') ui.repairScheduleDragging = true;
  if (grid === 'repair-periodicity') ui.repairPeriodicityDragging = true;
  focusCell(target);
}
function extendGridSelection(grid, e){
  const dragging = grid === 'repair-schedule' ? ui.repairScheduleDragging : ui.repairPeriodicityDragging;
  if (!dragging) return;
  const target = e.currentTarget || e.target;
  const info = getGridCellInfo(target);
  const sel = grid === 'repair-schedule' ? ui.repairScheduleSelection : ui.repairPeriodicitySelection;
  if (!info || !sel || !sel.anchor) return;
  if (sel.anchor.grid !== info.grid) return;
  const next = { row: info.row, col: info.col };
  if (grid === 'repair-schedule') setRepairScheduleSelection(sel.anchor, next);
  if (grid === 'repair-periodicity') setRepairPeriodicitySelection(sel.anchor, next);
}
function endGridSelection(){
  ui.repairScheduleDragging = false;
  ui.repairPeriodicityDragging = false;
}
function handleGridCopy(e){
  const target = e && e.target;
  const info = getGridCellInfo(target);
  if (!info) return;
  const sel = info.grid === 'repair-schedule' ? getRepairScheduleSelection() : info.grid === 'repair-periodicity' ? getRepairPeriodicitySelection() : null;
  if (!sel) return;
  const text = getGridSelectionText(info.grid, sel);
  if (text === '') return;
  e.preventDefault();
  e.clipboardData.setData('text/plain', text);
}
function handleGridPaste(e){
  if (!CAN_EDIT) return;
  if (e.defaultPrevented) return;
  const target = e && e.target;
  const info = getGridCellInfo(target);
  if (!info) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  e.preventDefault();
  pasteGridSelectionText(info.grid, target, text);
}
function moveGridCell(current, dx, dy, grid){
  const row = parseInt(current.dataset.row, 10);
  const col = parseInt(current.dataset.col, 10);
  const next = document.querySelector(`input[data-grid="${grid}"][data-row="${row + dy}"][data-col="${col + dx}"]`);
  if (next) next.focus();
}
function handleGridKeydown(e){
  const info = getGridCellInfo(e.target);
  if (!info) return;
  const keys = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter','Delete','Backspace'];
  if (!keys.includes(e.key)) return;

  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault();
    const sel = info.grid === 'repair-schedule' ? getRepairScheduleSelection() : getRepairPeriodicitySelection();
    const selected = sel && info.row >= sel.startRow && info.row <= sel.endRow && info.col >= sel.startCol && info.col <= sel.endCol;
    if (selected) {
      clearGridSelectionValues(info.grid, sel);
    } else {
      e.target.value = '';
      setPath(e.target.dataset.path, '');
    }
    if (info.grid === 'repair-schedule') updateRepairScheduleDerivedValues();
    markDirty(true);
    render();
    return;
  }

  let shouldMove = false;
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'Enter') {
    shouldMove = true;
  } else if (e.key === 'ArrowLeft') {
    if (e.target.selectionStart === 0) shouldMove = true;
  } else if (e.key === 'ArrowRight') {
    if (e.target.selectionEnd === e.target.value.length) shouldMove = true;
  }

  if (shouldMove) {
    const step = e.key === 'ArrowLeft' ? [-1,0] : (e.key === 'ArrowRight' || e.key === 'Enter') ? [1,0] : e.key === 'ArrowUp' ? [0,-1] : [0,1];
    e.preventDefault();
    if (info.grid === 'repair-schedule') {
      ui.repairScheduleSelection = null;
      applyRepairScheduleSelectionClasses();
    } else {
      ui.repairPeriodicitySelection = null;
      applyRepairPeriodicitySelectionClasses();
    }
    moveGridCell(e.target, step[0], step[1], info.grid);
  }
}
function getSelectedMonthSelection(){
  if (ui.section !== 'months' || !ui.monthSelection) return null;
  return ui.monthSelection;
}
function copyMonthSelectionText(){
  const sel = getSelectedMonthSelection();
  if (!sel) return '';
  const lines = [];
  for (let row = sel.startRow; row <= sel.endRow; row++) {
    const values = [];
    for (let col = sel.startCol; col <= sel.endCol; col++) {
      values.push(selectedMonthCellText({ monthIndex: sel.monthIndex, table: sel.table, row, col }));
    }
    lines.push(values.join('\t'));
  }
  return lines.join('\n');
}
function writeMonthCellValue(monthIndex, table, row, col, value){
  const selector = `input[data-month="${monthIndex}"][data-table="${table}"][data-row="${row}"][data-col="${col}"]`;
  const cell = document.querySelector(selector);
  if (!cell) return false;
  const normalized = value ?? '';
  cell.value = normalized;
  setPath(cell.dataset.path, normalized);
  return true;
}
function clearMonthSelectionValues(sel) {
  if (!sel) return false;
  let changed = false;
  for (let row = sel.startRow; row <= sel.endRow; row++) {
    for (let col = sel.startCol; col <= sel.endCol; col++) {
      changed = writeMonthCellValue(sel.monthIndex, sel.table, row, col, '') || changed;
    }
  }
  return changed;
}
function pasteMonthSelectionText(target, text){
  if (!CAN_EDIT) return;
  const info = getMonthCellInfo(target);
  if (!info || ui.section !== 'months') return;
  const rows = String(text ?? '').replace(/\r/g, '').split('\n');
  while (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  const matrix = rows.map((line) => line.split('\t'));
  const sel = getSelectedMonthSelection();
  const useSelection = sel && sel.monthIndex === info.monthIndex && sel.table === info.table;
  const startRow = useSelection ? sel.startRow : info.row;
  const startCol = useSelection ? sel.startCol : info.col;
  const sourceRows = matrix.length;
  const sourceCols = Math.max(...matrix.map((row) => row.length), 1);
  const targetRows = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endRow - sel.startRow + 1)
    : sourceRows;
  const targetCols = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endCol - sel.startCol + 1)
    : sourceCols;
  const fillSingle = matrix.length === 1 && matrix[0].length === 1 && useSelection;
  for (let r = 0; r < targetRows; r++) {
    for (let c = 0; c < targetCols; c++) {
      const sourceRow = fillSingle ? 0 : Math.min(r, matrix.length - 1);
      const sourceCol = fillSingle ? 0 : Math.min(c, matrix[sourceRow].length - 1);
      const value = matrix[sourceRow][sourceCol] ?? '';
      writeMonthCellValue(info.monthIndex, info.table, startRow + r, startCol + c, value);
    }
  }
  if (useSelection) setMonthSelection(sel.anchor, { monthIndex: info.monthIndex, table: info.table, row: startRow + targetRows - 1, col: startCol + targetCols - 1 });
  markDirty(true);
}
function handleMonthCopy(e){
  const sel = getSelectedMonthSelection();
  if (!sel) return;
  const text = copyMonthSelectionText();
  if (text === '') return;
  e.preventDefault();
  e.clipboardData.setData('text/plain', text);
}
function handleMonthPaste(e){
  if (!CAN_EDIT) return;
  if (e.defaultPrevented) return;
  const target = (e.target && e.target.dataset && e.target.dataset.month !== undefined)
    ? e.target
    : ui.lastCell;
  if (!target || !target.dataset || target.dataset.month === undefined) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  const sel = getSelectedMonthSelection();
  if (sel && sel.monthIndex !== Number(target.dataset.month)) {
    clearMonthSelection();
  }
  e.preventDefault();
  pasteMonthSelectionText(target, text);
}
document.addEventListener('mouseup', endMonthSelection, true);
document.addEventListener('mouseup', endGridSelection, true);
document.addEventListener('copy', handleMonthCopy, true);
document.addEventListener('copy', handleGridCopy, true);
document.addEventListener('paste', handleMonthPaste, true);
document.addEventListener('paste', handleGridPaste, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeJsonMenu();
});
document.addEventListener('click', event => {
  const wrap = document.getElementById('jsonMenuWrap');
  if (!wrap || !wrap.classList.contains('open')) return;
  if (wrap.contains(event.target)) return;
  closeJsonMenu();
});
function setPath(path, value){
  if (!CAN_EDIT) return;
  if (typeof value === 'string') value = value.toUpperCase();
  const p = path.split('.');
  let o = appState;
  for (let i=0; i<p.length-1; i++) o = o[p[i]];
  const last = p[p.length-1];
  o[last] = value;
  markDirty(true);
}
function handleGridInput(el){
  if (!el || !el.dataset) return;
  if (el.dataset.month !== undefined) setLastCell(el);
  const value = String(el.value ?? '').toUpperCase();
  if (el.value !== value) el.value = value;
  setPath(el.dataset.path, value);
  if (String(el.dataset.path || '').startsWith('repair_schedule.')) {
    updateRepairScheduleDerivedValues();
  }
}
function focusCell(el){ if (el) el.focus(); }
function monthCells(type){
  return Array.from(document.querySelectorAll(`input[data-month="${ui.monthIndex}"][data-table="${type}"]`));
}
function moveCell(current, dx, dy){
  const table = current.dataset.table;
  const row = parseInt(current.dataset.row, 10);
  const col = parseInt(current.dataset.col, 10);
  const targetRow = row + dy;
  const targetCol = col + dx;
  const next = document.querySelector(`input[data-month="${ui.monthIndex}"][data-table="${table}"][data-row="${targetRow}"][data-col="${targetCol}"]`);
  if (next) next.focus();
}
function handleMonthKeydown(e){
  const keys = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter','Delete','Backspace'];
  if (!keys.includes(e.key)) return;
  if (e.key === 'Delete' || e.key === 'Backspace'){
    e.preventDefault();
    const sel = getSelectedMonthSelection();
    const info = getMonthCellInfo(e.target);
    const selected = sel && info && sel.monthIndex === info.monthIndex && sel.table === info.table &&
                     info.row >= sel.startRow && info.row <= sel.endRow &&
                     info.col >= sel.startCol && info.col <= sel.endCol;
    if (selected) {
      clearMonthSelectionValues(sel);
    } else {
      e.target.value = '';
      setPath(e.target.dataset.path, '');
    }
    return;
  }
  let shouldMove = false;
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'Enter') {
    shouldMove = true;
  } else if (e.key === 'ArrowLeft') {
    if (e.target.selectionStart === 0) shouldMove = true;
  } else if (e.key === 'ArrowRight') {
    if (e.target.selectionEnd === e.target.value.length) shouldMove = true;
  }

  if (shouldMove) {
    const step = e.key === 'ArrowLeft' ? [-1,0] : (e.key === 'ArrowRight' || e.key === 'Enter') ? [1,0] : e.key === 'ArrowUp' ? [0,-1] : [0,1];
    e.preventDefault();
    clearMonthSelection();
    moveCell(e.target, step[0], step[1]);
  }
}
function bindNav(){
  document.getElementById('sectionNav').innerHTML = sections.map(s => `<button class="${ui.section===s.id || ui.modal===s.id ? 'active' : ''}" onclick="setSection('${s.id}')">${s.label}</button>`).join('');
}
function setSection(section){
  if (section === 'norms' || section === 'acts' || section === 'tu28') {
    ui.section = 'months';
    openSectionModal(section);
    return;
  }
  if (section === 'repairSchedule' && ui.section === 'repairSchedule' && !ui.modal) {
    ui.section = 'months';
    clearRepairScheduleSelection();
    render();
    return;
  }
  if (section === 'repairSummary' && ui.section === 'repairSummary' && !ui.modal) {
    ui.section = 'months';
    render();
    return;
  }
  ui.modal = null;
  ui.section = section;
  if (section !== 'repairSchedule') clearRepairScheduleSelection();
  render();
}
function setMonth(index){ ui.monthIndex = index; clearMonthSelection(); render(); }
function setMode(mode){ ui.mode = mode; render(); }
function currentMonth(){ return appState.months[ui.monthIndex]; }
function safeCurrentMonth(){
  const months = Array.isArray(appState.months) ? appState.months : [];
  return months[ui.monthIndex] || months[0] || { name:'', month:1, days:31, plan:[], fact:[] };
}
function isRepairSkipDay(year, month, day){
  if (hasSystemDate('holiday', month, day)) return true;
  if (hasSystemDate('transfer', month, day)) return true;
  return isWeekend(year, month, day);
}
function systemDates(){
  return appState.system_dates || { transfer: [], holiday: [] };
}
function hasSystemDate(kind, month, day){
  const items = systemDates()[kind] || [];
  return items.some(([m, d]) => m === month && d === day);
}
function dayClass(month, day){
  if (hasSystemDate('holiday', month, day)) return 'holiday-col';
  if (hasSystemDate('transfer', month, day) || isWeekend(appState.year, month, day)) return 'transfer-col';
  return '';
}
function isWeekend(year, month, day){
  const d = new Date(year, month - 1, day);
  const wd = d.getDay();
  return wd === 0 || wd === 6;
}
function ensureYearOptions(){
  const select = document.getElementById('yearInput');
  if (!select) return;
  const selectedYear = Number(appState.year) || new Date().getFullYear();
  const selected = String(selectedYear);
  const current = new Date().getFullYear();
  const minYear = Math.min(2020, selectedYear - 2, current - 2);
  const maxYear = Math.max(2100, selectedYear + 2, current + 2);
  const options = [];
  for (let y=minYear; y<=maxYear; y++) {
    options.push(`<option value="${y}" ${String(y)===selected ? 'selected' : ''}>${y}</option>`);
  }
  select.innerHTML = options.join('');
}
function render(){
  try {
    renderSafe();
  } catch (err) {
    const content = document.getElementById('content');
    if (content) {
      content.innerHTML = `<div style="padding:14px;border:1px solid #f0c2c2;background:#fff5f5;color:#9b1c1c;border-radius:12px;white-space:pre-wrap;font:14px/1.4 monospace;">${esc(err && err.stack ? err.stack : err)}</div>`;
    }
    throw err;
  }
}
function renderSafe(){
  ensureYearOptions();
  ensureLeaveGuard();
  document.title = `График ППР`;
  bindNav();
  updateSaveButtonState();
  const content = document.getElementById('content');
  if (!content) return;
  content.innerHTML = ui.section === 'repairSchedule'
    ? renderRepairSchedule()
    : ui.section === 'repairSummary'
      ? renderRepairSummary()
      : renderMonths();
  applyMonthSelectionClasses();
  applyRepairScheduleSelectionClasses();
  renderOpenModals();
  updateHistoryButtons();
}
window.addEventListener('error', (event) => {
  const content = document.getElementById('content');
  if (!content) return;
  const text = event && event.error && event.error.stack ? event.error.stack : (event && event.message ? event.message : 'Unknown error');
  content.innerHTML = `<div style="padding:14px;border:1px solid #f0c2c2;background:#fff5f5;color:#9b1c1c;border-radius:12px;white-space:pre-wrap;font:14px/1.4 monospace;">${esc(text)}</div>`;
});
function repairButtonsHtml(){
  return `
      <div class="repair-strip">
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО2')">ТО2</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО3')">ТО3</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР1')">ТР1</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР2')">ТР2</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР3')">ТР3</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО')">ТО</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР')">ТР</button>
      </div>
    `;
}
function rowActionsHtml(){
  return `
      <div class="row-actions">
        <button type="button" onclick="addRow('plan'); addRow('fact')">+ строку</button>
        <button type="button" class="danger" onclick="deleteRow('plan'); deleteRow('fact')">- строку</button>
        <button type="button" id="cancelButton" title="Отмена" aria-label="Отмена" onclick="cancelChanges()">↺</button>
        <button type="button" id="restoreButton" title="Вернуть" aria-label="Вернуть" onclick="restoreChanges()">↻</button>
      </div>
  `;
}
function rowActionsSpacerHtml(){
  return `
      <div class="row-actions row-actions-spacer" aria-hidden="true">
        <button type="button" tabindex="-1">+ строку</button>
        <button type="button" tabindex="-1" class="danger">- строку</button>
        <button type="button" tabindex="-1">↺</button>
        <button type="button" tabindex="-1">↻</button>
      </div>
  `;
}
function monthSelectHtml(){
  return `
    <select id="actsMonthSelect" onchange="setMonth(parseInt(this.value, 10))" style="border:1px solid var(--line); border-radius:8px; padding:2px 8px; font:inherit; font-size:15px; background:#fff; width:112px; min-width:112px; max-width:112px;">
      ${appState.months.map((m, i) => `<option value="${i}" ${i === ui.monthIndex ? 'selected' : ''}>${m.name}</option>`).join('')}
    </select>
  `;
}
function renderMonths(){
  const m = safeCurrentMonth();
  const headers = ['№','Серия','Номер','Категория',...Array.from({length:m.days},(_,i)=>String(i+1).padStart(2,'0')),'Примечание'];
  const monthButtons = appState.months.map((x,i)=>`<button class="${i===ui.monthIndex?'active':''}" onclick="setMonth(${i})">${x.name}</button>`).join('');
  return `
    <div class="months-row">
      <div class="month-strip">${monthButtons}</div>
    </div>
    ${renderMonthTable('plan', 'План', m, headers)}
    ${renderMonthTable('fact', 'Факт', m, headers)}
  `;
}
function defaultRepairScheduleState(){
  const columns = REPAIR_SCHEDULE_COLUMN_CODES.map((code) => ({ code }));
  return {
    columns,
    objects: [blankRepairScheduleObject(columns.length)],
  };
}
function blankRepairScheduleObject(columnCount){
  const cols = Number.isFinite(columnCount) ? columnCount : REPAIR_SCHEDULE_COLUMN_CODES.length;
  return {
    series: '',
    number: '',
    kr: { plan: '', fact: '' },
    plan: Array.from({ length: cols }, () => ''),
    fact: Array.from({ length: cols }, () => ''),
  };
}
function normalizeRepairSchedule(){
  let schedule = appState.repair_schedule;
  const defaults = defaultRepairScheduleState();
  const defaultColumns = defaults.columns;
  if (!schedule || typeof schedule !== 'object') {
    schedule = defaults;
  } else if (Array.isArray(schedule)) {
    schedule = {
      columns: defaultColumns.map((col) => ({ ...col })),
      objects: schedule.map((row) => {
        const obj = row && typeof row === 'object' ? row : {};
        return {
          series: String(obj.series ?? obj.unit ?? ''),
          number: String(obj.number ?? ''),
          kr: {
            plan: String(obj.kr?.plan ?? ''),
            fact: String(obj.kr?.fact ?? ''),
          },
          plan: Array.isArray(obj.plan) ? obj.plan.map((v) => String(v ?? '')) : [],
          fact: Array.isArray(obj.fact) ? obj.fact.map((v) => String(v ?? '')) : [],
        };
      }),
    };
  }
  if (!Array.isArray(schedule.columns) || schedule.columns.length === 0) {
    schedule.columns = defaultColumns.map((col) => ({ ...col }));
  } else {
    schedule.columns = schedule.columns.map((col, idx) => ({
      code: String((col && col.code) ?? defaultColumns[idx % defaultColumns.length].code ?? ''),
    }));
  }
  const colCount = schedule.columns.length;
  if (!Array.isArray(schedule.objects)) schedule.objects = [];
  schedule.objects = schedule.objects.map((row) => {
    const obj = row && typeof row === 'object' ? row : {};
    const plan = Array.isArray(obj.plan) ? obj.plan.slice(0, colCount).map((v) => String(v ?? '')) : [];
    const fact = Array.isArray(obj.fact) ? obj.fact.slice(0, colCount).map((v) => String(v ?? '')) : [];
    while (plan.length < colCount) plan.push('');
    while (fact.length < colCount) fact.push('');
    return {
      series: String(obj.series ?? obj.unit ?? ''),
      number: String(obj.number ?? ''),
      kr: {
        plan: String(obj.kr?.plan ?? ''),
        fact: String(obj.kr?.fact ?? ''),
      },
      plan,
      fact,
    };
  });
  if (!schedule.objects.length) {
    schedule.objects.push(blankRepairScheduleObject(colCount));
  }
  appState.repair_schedule = schedule;
  return schedule;
}
function repairSeriesKey(value){
  return String(value ?? '').trim().toUpperCase();
}
function parseRepairDate(value){
  const text = String(value ?? '').trim();
  if (!text) return null;
  const ruMatch = text.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  const isoMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!ruMatch && !isoMatch) return null;
  const day = Number(ruMatch ? ruMatch[1] : isoMatch[3]);
  const month = Number(ruMatch ? ruMatch[2] : isoMatch[2]);
  const year = Number(ruMatch ? ruMatch[3] : isoMatch[1]);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return date;
}
function formatRepairDate(date){
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
  return `${String(date.getDate()).padStart(2, '0')}.${String(date.getMonth() + 1).padStart(2, '0')}.${date.getFullYear()}`;
}
function repairDateTime(date){
  return (date instanceof Date && !Number.isNaN(date.getTime()))
    ? new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
    : NaN;
}
function addRepairDays(date, days){
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null;
  const result = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  result.setDate(result.getDate() + Number(days || 0));
  return result;
}
function addRepairMonths(date, months){
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null;
  const total = Number(months);
  if (!Number.isFinite(total) || total <= 0) return new Date(date.getTime());
  const whole = Math.trunc(total);
  const fraction = total - whole;
  const result = new Date(date.getTime());
  result.setMonth(result.getMonth() + whole);
  if (fraction) result.setDate(result.getDate() + Math.round(30 * fraction));
  return result;
}
function repairSchedulePeriodRow(seriesName){
  const schedule = normalizeRepairSchedule();
  const periodicity = schedule.periodicity || defaultRepairPeriodicityState();
  const target = repairSeriesKey(seriesName);
  let rowIndex = Array.isArray(periodicity.series)
    ? periodicity.series.findIndex((item) => repairSeriesKey(item) === target)
    : -1;
  if (rowIndex < 0) rowIndex = 0;
  return Array.isArray(periodicity.values) ? periodicity.values[rowIndex] || [] : [];
}
function repairScheduleColumnFactor(code){
  const normalized = normalizeRepairCode(code);
  if (normalized === 'ТР1') return 1;
  if (normalized === 'ТР2') return 0.5;
  if (normalized === 'ТР3') return 0.25;
  if (normalized === 'СР') return 0.125;
  if (normalized === 'КР') return 1;
  return 0;
}
function repairScheduleColumnPeriodMonths(code, seriesName){
  const row = repairSchedulePeriodRow(seriesName);
  const normalized = normalizeRepairCode(code);
  const indexMap = { 'ТР1': 0, 'ТР2': 1, 'ТР3': 2, 'СР': 3, 'КР': 4 };
  const idx = indexMap[normalized];
  if (!Number.isInteger(idx) || idx < 0 || idx >= row.length) return 0;
  const numeric = Number(String(row[idx] ?? '').replace(',', '.'));
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return numeric;
}
function updateRepairScheduleDerivedValues(){
  const schedule = normalizeRepairSchedule();
  const columns = schedule.columns || [];
  const objects = schedule.objects || [];
  objects.forEach((row, idx) => {
    if (!row.kr) row.kr = { plan: '', fact: '' };
    const krFactDate = parseRepairDate(row.kr.fact);
    const krPlanDate = krFactDate || parseRepairDate(row.kr.plan);
    row.kr.plan = formatRepairDate(krPlanDate);
    let sourceDate = krFactDate || krPlanDate;
    columns.forEach((col, cidx) => {
      const periodMonths = repairScheduleColumnPeriodMonths(col.code, row.series);
      const targetDate = sourceDate && periodMonths > 0 ? addRepairMonths(sourceDate, periodMonths * repairScheduleColumnFactor(col.code)) : null;
      const planned = formatRepairDate(targetDate);
      row.plan[cidx] = planned;
      const factDate = parseRepairDate(row.fact[cidx]);
      sourceDate = factDate || targetDate || sourceDate;
      const cell = document.querySelector(`input[data-path="repair_schedule.objects.${idx}.plan.${cidx}"]`);
      if (cell && cell.value !== planned) cell.value = planned;
    });
    const krCell = document.querySelector(`input[data-path="repair_schedule.objects.${idx}.kr.plan"]`);
    if (krCell && krCell.value !== row.kr.plan) krCell.value = row.kr.plan;
  });
  return schedule;
}
function defaultRepairPeriodicityState(){
  return {
    series: REPAIR_PERIODICITY_DEFAULT_SERIES.slice(),
    values: REPAIR_PERIODICITY_DEFAULT_SERIES.map(() => REPAIR_PERIODICITY_COLUMNS.map(() => '')),
  };
}
function normalizeRepairPeriodicity(){
  const schedule = normalizeRepairSchedule();
  let periodicity = schedule.periodicity;
  if (!periodicity || typeof periodicity !== 'object') {
    periodicity = defaultRepairPeriodicityState();
  }
  const series = Array.isArray(periodicity.series) ? periodicity.series.slice(0, REPAIR_PERIODICITY_DEFAULT_SERIES.length).map((v, i) => String(v ?? REPAIR_PERIODICITY_DEFAULT_SERIES[i] ?? '')) : [];
  while (series.length < REPAIR_PERIODICITY_DEFAULT_SERIES.length) series.push(REPAIR_PERIODICITY_DEFAULT_SERIES[series.length] || '');
  const values = Array.isArray(periodicity.values) ? periodicity.values.slice(0, series.length).map((row) => {
    const cells = Array.isArray(row) ? row.slice(0, REPAIR_PERIODICITY_COLUMNS.length).map((v) => String(v ?? '')) : [];
    while (cells.length < REPAIR_PERIODICITY_COLUMNS.length) cells.push('');
    return cells;
  }) : [];
  while (values.length < series.length) values.push(REPAIR_PERIODICITY_COLUMNS.map(() => ''));
  periodicity = { series, values };
  schedule.periodicity = periodicity;
  return periodicity;
}
function repairScheduleCell(path, value, cls='cell', gridRow=null, gridCol=null){
  const ro = CAN_EDIT ? '' : 'readonly';
  const derivedRo = String(path || '').includes('.plan.') ? 'readonly' : '';
  const gridAttrs = Number.isFinite(gridRow) && Number.isFinite(gridCol)
    ? ` data-grid="repair-schedule" data-row="${gridRow}" data-col="${gridCol}" onfocus="setLastCell(this)" onmousedown="beginGridSelection('repair-schedule', event)" onmouseenter="extendGridSelection('repair-schedule', event)" onmouseup="endGridSelection()" oncopy="handleGridCopy(event)" onpaste="handleGridPaste(event)" onkeydown="handleGridKeydown(event)"`
    : '';
  return `<input ${derivedRo || ro} class="${cls}" data-path="${path}" value="${esc(value || '')}"${gridAttrs} oninput="handleGridInput(this)">`;
}
function renderRepairSchedule(){
  const schedule = normalizeRepairSchedule();
  updateRepairScheduleDerivedValues();
  const columns = schedule.columns || [];
  const objects = schedule.objects || [];
  const headerCells = [
    '<th rowspan="2" class="col-idx">№</th>',
    '<th rowspan="2" class="col-series">Серия</th>',
    '<th rowspan="2" class="col-number">Номер</th>',
    '<th rowspan="2" class="col-planfact">План/факт</th>',
    '<th rowspan="2" class="repair-head">КР</th>',
    ...columns.map((col) => `<th rowspan="2" class="repair-head">${esc(normalizeRepairCode(col.code || ''))}</th>`),
  ].join('');
  const bodyHtml = objects.length
    ? objects.map((row, idx) => {
        const rowNum = idx + 1;
        const planCells = [`<td>${repairScheduleCell(`repair_schedule.objects.${idx}.kr.plan`, row.kr?.plan || '', 'cell center', idx * 2, 0)}</td>`]
          .concat(columns.map((_, cidx) => `<td>${repairScheduleCell(`repair_schedule.objects.${idx}.plan.${cidx}`, row.plan[cidx] || '', 'cell center', idx * 2, cidx + 1)}</td>`))
          .join('');
        const factCells = [`<td>${repairScheduleCell(`repair_schedule.objects.${idx}.kr.fact`, row.kr?.fact || '', 'cell center', idx * 2 + 1, 0)}</td>`]
          .concat(columns.map((_, cidx) => `<td>${repairScheduleCell(`repair_schedule.objects.${idx}.fact.${cidx}`, row.fact[cidx] || '', 'cell center', idx * 2 + 1, cidx + 1)}</td>`))
          .join('');
        return `
          <tr class="repair-group-start">
            <td class="col-idx" rowspan="2"><div class="rownum"><span>${rowNum}</span></div></td>
            <td class="col-series" rowspan="2">${repairScheduleCell(`repair_schedule.objects.${idx}.series`, row.series || '', 'cell')}</td>
            <td class="col-number" rowspan="2">${repairScheduleCell(`repair_schedule.objects.${idx}.number`, row.number || '', 'cell')}</td>
            <td class="col-planfact">План</td>
            ${planCells}
          </tr>
          <tr>
            <td class="col-planfact">Факт</td>
            ${factCells}
          </tr>
        `;
      }).join('')
    : `<tr><td colspan="${5 + columns.length}" class="empty-table-cell">Нет записей</td></tr>`;
  return `
    <div class="section-head repair-schedule-head">
      <div class="section-title">График ремонтов</div>
      <div class="row-actions">
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="openRepairSchedulePeriodicity()">Периодичность</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="deleteRepairScheduleRow()">- строку</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="addRepairScheduleRow()">+ строку</button>
      </div>
    </div>
    <div class="table-wrap repair-schedule-wrap">
      <table class="compact repair-schedule-table">
        <colgroup>
          <col style="width:45px">
          <col style="width:130px">
          <col style="width:110px">
          <col style="width:100px">
          <col style="width:92px">
          ${columns.map(() => '<col style="width:92px">').join('')}
        </colgroup>
        <thead>
          <tr>${headerCells}</tr>
        </thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}
function repairSummaryDefaultTypes(){
  const schedule = normalizeRepairSchedule();
  const codes = [];
  const seen = new Set();
  const add = (value) => {
    const code = normalizeRepairCode(value || '');
    if (!code || seen.has(code)) return;
    seen.add(code);
    codes.push(code);
  };
  add('КР');
  (schedule.columns || []).forEach((col) => add(col && col.code));
  return codes;
}
function repairSummaryMonthTypes(){
  const schedule = normalizeRepairSchedule();
  const seen = new Set();
  const codes = [];
  const add = (value) => {
    const code = normalizeRepairCode(value || '');
    if (!code || seen.has(code) || !/[A-ZА-Я]/u.test(code)) return;
    seen.add(code);
    codes.push(code);
  };
  add('КР');
  (schedule.columns || []).forEach((col) => add(col && col.code));
  (Array.isArray(appState.months) ? appState.months : []).forEach((month) => {
    (month?.fact || []).forEach((row) => {
      (row?.cells || []).forEach((value, idx) => {
        if (idx < 4) return;
        add(value);
      });
    });
  });
  return codes;
}
function repairSummaryDataset(source){
  const key = String(source ?? 'months').trim().toLowerCase() === 'schedule' ? 'schedule' : 'months';
  const data = appState && appState.repair_summary && appState.repair_summary[key];
  if (data && typeof data === 'object') return data;
  return null;
}
function repairSummaryKnownTypes(source, locoKey = ''){
  const data = repairSummaryDataset(source);
  const selectedLoco = String(locoKey ?? '').trim();
  const rows = data && Array.isArray(data.rows) ? data.rows : [];
  const seen = new Set();
  const codes = [];
  const add = (value) => {
    const code = normalizeRepairCode(value || '');
    if (!code || seen.has(code)) return;
    seen.add(code);
    codes.push(code);
  };

  const filteredRows = selectedLoco
    ? rows.filter((row) => repairSummaryRowMatchesLoco(row, selectedLoco))
    : rows;

  if (filteredRows.length) {
    filteredRows.forEach((row) => add(row?.repairCode));
    if (codes.length) return codes;
  }

  if (data && Array.isArray(data.types) && data.types.length) {
    data.types.forEach((value) => add(value));
    if (codes.length) return codes;
  }

  return normalizeRepairCode(source) === 'SCHEDULE'
    ? repairSummaryDefaultTypes()
    : repairSummaryMonthTypes();
}
function repairSummaryNormalizeState(){
  if (!ui.repairSummary || typeof ui.repairSummary !== 'object') {
    ui.repairSummary = { source: 'months', locomotive: '', dateFrom: '', dateTo: '', types: [], kpMeasurement: 'all' };
  }
  const source = String(ui.repairSummary.source ?? 'months').trim().toLowerCase() === 'schedule' ? 'schedule' : 'months';
  ui.repairSummary.source = source;
  ui.repairSummary.locomotive = String(ui.repairSummary.locomotive ?? '').trim();
  const defaults = repairSummaryKnownTypes(source, ui.repairSummary.locomotive);
  const currentTypes = Array.isArray(ui.repairSummary.types) ? ui.repairSummary.types.map((value) => normalizeRepairCode(value)).filter(Boolean) : [];
  const allowed = new Set(defaults);
  let types = currentTypes.filter((value) => allowed.has(value));
  ui.repairSummary.types = Array.from(new Set(types));
  ui.repairSummary.dateFrom = String(ui.repairSummary.dateFrom ?? '').trim();
  ui.repairSummary.dateTo = String(ui.repairSummary.dateTo ?? '').trim();
  const kpMeasurement = String(ui.repairSummary.kpMeasurement ?? 'all').trim().toLowerCase();
  ui.repairSummary.kpMeasurement = kpMeasurement === 'has' || kpMeasurement === 'none' ? kpMeasurement : 'all';
  return ui.repairSummary;
}
function repairSummaryLocomotiveOptions(){
  const state = repairSummaryNormalizeState();
  const data = repairSummaryDataset(state.source);
  if (data && Array.isArray(data.loco_options) && data.loco_options.length) {
    return data.loco_options.map((item) => ({ key: String(item.key ?? ''), label: String(item.label ?? '') }));
  }
  const useSchedule = state.source === 'schedule';
  const seen = new Set();
  const rows = [];
  if (useSchedule) {
    const schedule = normalizeRepairSchedule();
    (schedule.objects || []).forEach((row) => {
      const series = String(row.series ?? '').trim();
      const number = String(row.number ?? '').trim();
      if (!series && !number) return;
      const key = `${series}|${number}`;
      if (seen.has(key)) return;
      seen.add(key);
      rows.push({ key, label: [series, number].filter(Boolean).join(' ').trim() });
    });
  } else {
    (appState.months || []).forEach((month) => {
      (month?.fact || []).forEach((row) => {
        if (!row || row.excluded) return;
        const key = reportUnitKey(row);
        if (!key) return;
        const keyStr = key.join('|');
        if (seen.has(keyStr)) return;
        seen.add(keyStr);
        rows.push({ key: keyStr, label: key.join(' ').trim() });
      });
    });
  }
  rows.sort((a, b) => a.label.localeCompare(b.label, 'ru'));
  return rows;
}
function repairSummaryRowMatchesLoco(row, locoKey){
  if (!locoKey) return true;
  const current = `${String(row.series ?? '').trim()}|${String(row.number ?? '').trim()}`;
  return current === locoKey;
}
function repairSummaryDateInRange(dateValue, dateFrom, dateTo){
  const date = parseRepairDate(dateValue);
  if (!date) return false;
  if (dateFrom) {
    const from = parseRepairDate(dateFrom);
    if (from && date < from) return false;
  }
  if (dateTo) {
    const to = parseRepairDate(dateTo);
    if (to && date > to) return false;
  }
  return true;
}
function repairSummaryDateKey(date){
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}-${day}`;
}
function repairSummaryIsNonWorkingDate(date){
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return false;
  const key = repairSummaryDateKey(date);
  if (REPAIR_SUMMARY_FIXED_HOLIDAYS.has(key)) return true;
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const day = date.getDate();
  const calendar = appState?.repair_summary?.system_dates_by_year?.[String(year)]
    || (year === Number(appState.year) ? systemDates() : null);
  const containsDate = (kind) => (calendar?.[kind] || []).some(([m, d]) => Number(m) === month && Number(d) === day);
  if (containsDate('holiday')) return true;
  if (containsDate('transfer')) return true;
  const wd = date.getDay();
  return wd === 0 || wd === 6;
}
function repairSummaryCanBridgeGap(prevDate, nextDate){
  if (!(prevDate instanceof Date) || !(nextDate instanceof Date)) return false;
  if (Number.isNaN(prevDate.getTime()) || Number.isNaN(nextDate.getTime())) return false;
  if (nextDate <= prevDate) return false;
  let cursor = new Date(prevDate.getFullYear(), prevDate.getMonth(), prevDate.getDate());
  cursor.setDate(cursor.getDate() + 1);
  while (cursor < nextDate) {
    if (!repairSummaryIsNonWorkingDate(cursor)) return false;
    cursor.setDate(cursor.getDate() + 1);
  }
  return true;
}
function repairSummaryMonthDate(year, monthNumber, day){
  const date = new Date(year, monthNumber - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== monthNumber - 1 || date.getDate() !== day) return null;
  return date;
}
function collectRepairSummaryRowsFromSchedule(){
  const schedule = normalizeRepairSchedule();
  const filters = repairSummaryNormalizeState();
  const selectedTypes = new Set((filters.types || []).map((value) => normalizeRepairCode(value)).filter(Boolean));
  const rows = [];
  (schedule.objects || []).forEach((row, rowIndex) => {
    const series = String(row.series ?? '').trim();
    const number = String(row.number ?? '').trim();
    if (!series && !number) return;
    const locoLabel = [series, number].filter(Boolean).join(' ').trim();
    const locoKey = `${series}|${number}`;
    if (!repairSummaryRowMatchesLoco(row, filters.locomotive)) return;

    const pushRow = (repairCode, dateValue, columnIndex, sourceKind) => {
      const code = normalizeRepairCode(repairCode);
      const dateText = String(dateValue ?? '').trim();
      if (!code || !dateText || (selectedTypes.size && !selectedTypes.has(code))) return;
      if (!repairSummaryDateInRange(dateText, filters.dateFrom, filters.dateTo)) return;
      const parsed = parseRepairDate(dateText);
      rows.push({
        rowIndex,
        locoKey,
        locoLabel,
        series,
        number,
        repairCode: code,
        repairDate: dateText,
        repairDateSort: parsed ? parsed.getTime() : 0,
        columnIndex,
        sourceKind,
      });
    };

    pushRow('КР', row.kr?.fact || '', -1, 'kr');
    (schedule.columns || []).forEach((col, cidx) => {
      pushRow(col && col.code, row.fact?.[cidx] || '', cidx, 'fact');
    });
  });
  return rows;
}
function collectRepairSummaryRowsFromMonths(){
  const filters = repairSummaryNormalizeState();
  const selectedTypes = new Set((filters.types || []).map((value) => normalizeRepairCode(value)).filter(Boolean));
  const rows = [];
  const year = Number(appState.year) || new Date().getFullYear();
  (appState.months || []).forEach((month, monthIndex) => {
    const monthNumber = Number(month?.month || monthIndex + 1);
    if (!Number.isFinite(monthNumber) || monthNumber < 1 || monthNumber > 12) return;
    (month?.fact || []).forEach((row, rowIndex) => {
      if (!row || row.excluded) return;
      const key = reportUnitKey(row);
      if (!key) return;
      const locoLabel = key.join(' ').trim();
      const locoKey = key.join('|');
      if (!repairSummaryRowMatchesLoco(row, filters.locomotive)) return;
      (row.cells || []).forEach((value, cellIndex) => {
        if (cellIndex < 4) return;
        if (cellIndex >= 4 + month.days) return;
        const code = normalizeRepairCode(value);
        if (!code || (selectedTypes.size && !selectedTypes.has(code))) return;
        const day = cellIndex - 3;
        const date = repairSummaryMonthDate(year, monthNumber, day);
        if (!date) return;
        const dateText = formatRepairDate(date);
        if (!repairSummaryDateInRange(dateText, filters.dateFrom, filters.dateTo)) return;
        rows.push({
          rowIndex,
          locoKey,
          locoLabel,
          series: key[0],
          number: key[1],
          repairCode: code,
          repairDate: dateText,
          repairDateSort: date.getTime(),
          columnIndex: cellIndex,
          sourceKind: 'month',
        });
      });
    });
  });
  rows.sort((a, b) => {
    if (a.repairDateSort !== b.repairDateSort) return b.repairDateSort - a.repairDateSort;
    const locoCmp = a.locoLabel.localeCompare(b.locoLabel, 'ru');
    if (locoCmp !== 0) return locoCmp;
    const codeCmp = a.repairCode.localeCompare(b.repairCode, 'ru');
    if (codeCmp !== 0) return codeCmp;
    return a.columnIndex - b.columnIndex;
  });
  return rows;
}
function collectRepairSummaryRows(){
  const state = repairSummaryNormalizeState();
  const data = repairSummaryDataset(state.source);
  const rawRows = data && Array.isArray(data.rows) ? data.rows.slice() : (
    state.source === 'schedule'
      ? collectRepairSummaryRowsFromSchedule()
      : collectRepairSummaryRowsFromMonths()
  );
  const selectedTypes = new Set((state.types || []).map((value) => normalizeRepairCode(value)).filter(Boolean));
  return rawRows.filter((row) => {
    if (!row) return false;
    if (!repairSummaryRowMatchesLoco(row, state.locomotive)) return false;
    if (!repairSummaryDateInRange(row.repairDate, state.dateFrom, state.dateTo)) return false;
    return selectedTypes.size ? selectedTypes.has(normalizeRepairCode(row.repairCode)) : true;
  });
}
function groupRepairSummaryRows(rows){
  const sorted = Array.isArray(rows) ? rows.slice() : [];
  sorted.sort((a, b) => {
    if (a.locoLabel !== b.locoLabel) return a.locoLabel.localeCompare(b.locoLabel, 'ru');
    if (a.repairCode !== b.repairCode) return a.repairCode.localeCompare(b.repairCode, 'ru');
    if (a.repairDateSort !== b.repairDateSort) return a.repairDateSort - b.repairDateSort;
    return a.columnIndex - b.columnIndex;
  });
  const grouped = [];
  for (const row of sorted) {
    const prev = grouped[grouped.length - 1];
    const sameGroup = prev
      && prev.locoKey === row.locoKey
      && prev.repairCode === row.repairCode
      && prev.sourceKind === row.sourceKind;
    if (!sameGroup) {
      grouped.push({
        ...row,
        repairDateFrom: row.repairDate,
        repairDateTo: row.repairDate,
      });
      continue;
    }
    const prevDate = parseRepairDate(prev.repairDateTo || prev.repairDate);
    const currDate = parseRepairDate(row.repairDateFrom || row.repairDate);
    const diffDays = prevDate && currDate ? Math.round((currDate - prevDate) / 86400000) : NaN;
    if (diffDays >= 0 && diffDays <= 1) {
      prev.repairDateTo = row.repairDate;
      prev.repairDateSort = row.repairDateSort;
      prev.columnIndex = Math.min(prev.columnIndex, row.columnIndex);
      continue;
    }
    if (prevDate && currDate && repairSummaryCanBridgeGap(prevDate, currDate)) {
      prev.repairDateTo = row.repairDate;
      prev.repairDateSort = row.repairDateSort;
      prev.columnIndex = Math.min(prev.columnIndex, row.columnIndex);
      continue;
    }
    grouped.push({
      ...row,
      repairDateFrom: row.repairDate,
      repairDateTo: row.repairDate,
    });
  }
  return grouped.sort((a, b) => {
    if (a.repairDateSort !== b.repairDateSort) return b.repairDateSort - a.repairDateSort;
    if (a.locoLabel !== b.locoLabel) return a.locoLabel.localeCompare(b.locoLabel, 'ru');
    if (a.repairCode !== b.repairCode) return a.repairCode.localeCompare(b.repairCode, 'ru');
    return a.columnIndex - b.columnIndex;
  });
}
function repairSummaryKpMeasurements(){
  const values = appState?.repair_summary?.kp_measurements;
  return Array.isArray(values) ? values : [];
}
function repairSummaryKpMeasurementDates(row){
  const number = String(row?.number ?? '').trim();
  const repairCode = normalizeRepairCode(row?.repairCode);
  const dateFrom = parseRepairDate(row?.repairDateFrom || row?.repairDate);
  const dateTo = parseRepairDate(row?.repairDateTo || row?.repairDate);
  if (!number || !repairCode || !dateFrom || !dateTo) return [];
  const dates = repairSummaryKpMeasurements()
    .filter((item) => {
      if (String(item?.number ?? '').trim() !== number) return false;
      if (normalizeRepairCode(item?.repairCode) !== repairCode) return false;
      const measurementDate = parseRepairDate(item?.measurementDate);
      if (!measurementDate) return false;
      const diffStart = measurementDate - dateFrom;
      const diffEnd = measurementDate - dateTo;
      const tolerance = 15 * 24 * 60 * 60 * 1000; // 15 дней
      return diffStart >= -tolerance && diffEnd <= tolerance;
    })
    .map((item) => parseRepairDate(item.measurementDate))
    .filter(Boolean)
    .sort((a, b) => a - b);
  return Array.from(new Set(dates.map((date) => formatRepairDate(date))));
}
function setRepairSummaryFilter(name, value){
  const state = repairSummaryNormalizeState();
  state[name] = String(value ?? '').trim();
  render();
}
function toggleRepairSummaryType(code, checked){
  const state = repairSummaryNormalizeState();
  const normalized = normalizeRepairCode(code);
  const current = new Set((state.types || []).map((value) => normalizeRepairCode(value)).filter(Boolean));
  if (checked) current.add(normalized);
  else current.delete(normalized);
  state.types = Array.from(current);
  render();
}
function repairSummaryResetFilters(){
  const state = repairSummaryNormalizeState();
  state.source = 'months';
  state.locomotive = '';
  state.dateFrom = '';
  state.dateTo = '';
  state.types = [];
  state.kpMeasurement = 'all';
  render();
}
function renderRepairSummary(){
  const filters = repairSummaryNormalizeState();
  const locoOptions = repairSummaryLocomotiveOptions();
  const typeOptions = repairSummaryKnownTypes(filters.source, filters.locomotive);
  const rawRows = collectRepairSummaryRows();
  const groupedRows = groupRepairSummaryRows(rawRows);
  const rows = groupedRows.filter((row) => {
    const hasKp = repairSummaryKpMeasurementDates(row).length > 0;
    if (filters.kpMeasurement === 'has') return hasKp;
    if (filters.kpMeasurement === 'none') return !hasKp;
    return true;
  });
  const totalFacts = rawRows.length;
  return `
    <div class="section-head repair-summary-head">
      <div class="section-title">Сводная таблица ремонтов</div>
      <div class="repair-summary-counter">Показано: ${rows.length} · всего фактов: ${totalFacts}</div>
    </div>
    <div class="repair-summary-note">Берём только значения из факта. Одинаковые подряд идущие ремонты одной пары склеиваются в диапазон дат.</div>
    <div class="repair-summary-filters">
      <label>Источник
        <select id="repairSummarySource" style="width:220px" onchange="setRepairSummaryFilter('source', this.value)">
          <option value="months" ${filters.source === 'months' ? 'selected' : ''}>Перебирать месяцы</option>
          <option value="schedule" ${filters.source === 'schedule' ? 'selected' : ''}>График ремонтов</option>
        </select>
      </label>
      <label>Локомотив
        <select id="repairSummaryLoco" style="width:260px" onchange="setRepairSummaryFilter('locomotive', this.value)">
          <option value="" ${!filters.locomotive ? 'selected' : ''}>Все локомотивы</option>
          ${locoOptions.map((item) => `<option value="${esc(item.key)}" ${filters.locomotive === item.key ? 'selected' : ''}>${esc(item.label)}</option>`).join('')}
        </select>
      </label>
      <label>С
        <input id="repairSummaryDateFrom" type="date" style="width:160px" value="${esc(filters.dateFrom)}" onchange="setRepairSummaryFilter('dateFrom', this.value)">
      </label>
      <label>По
        <input id="repairSummaryDateTo" type="date" style="width:160px" value="${esc(filters.dateTo)}" onchange="setRepairSummaryFilter('dateTo', this.value)">
      </label>
      <label>Замер КП
        <select id="repairSummaryKpMeasurement" style="width:160px" onchange="setRepairSummaryFilter('kpMeasurement', this.value)">
          <option value="all" ${filters.kpMeasurement === 'all' ? 'selected' : ''}>Все</option>
          <option value="has" ${filters.kpMeasurement === 'has' ? 'selected' : ''}>Есть</option>
          <option value="none" ${filters.kpMeasurement === 'none' ? 'selected' : ''}>Нет</option>
        </select>
      </label>
      <button type="button" onclick="repairSummaryResetFilters()">Сбросить</button>
    </div>
    <div class="repair-summary-types">
      ${typeOptions.map((code) => `<label class="repair-summary-type"><input type="checkbox" ${filters.types.includes(code) ? 'checked' : ''} onchange="toggleRepairSummaryType('${esc(code)}', this.checked)"> <span>${esc(code)}</span></label>`).join('')}
    </div>
    <div class="table-wrap repair-summary-wrap">
      <table class="compact repair-summary-table">
        <colgroup>
          <col class="col-loco">
          <col class="col-repair">
          <col class="col-date">
          <col class="col-date">
          <col class="col-kp-measure">
        </colgroup>
        <thead>
          <tr>
            <th>Локомотив</th>
            <th>Вид ремонта</th>
            <th>От</th>
            <th>До</th>
            <th>Замер КП</th>
          </tr>
        </thead>
        <tbody>
          ${rows.length ? rows.map((row) => {
            const kpDates = repairSummaryKpMeasurementDates(row);
            return `
              <tr>
                <td>${esc(row.locoLabel || '—')}</td>
                <td>${esc(row.repairCode || '—')}</td>
                <td>${esc(row.repairDateFrom || row.repairDate || '—')}</td>
                <td>${esc(row.repairDateTo || row.repairDate || '—')}</td>
                <td><span class="kp-measure-status ${kpDates.length ? 'has-measurement' : 'no-measurement'}">${kpDates.length ? `Есть · ${esc(kpDates.join(', '))}` : 'Нет'}</span></td>
              </tr>
            `;
          }).join('') : `<tr><td colspan="5" class="empty-table-cell">Нет ремонтов, подходящих под фильтры</td></tr>`}
        </tbody>
      </table>
    </div>
  `;
}
function addRepairScheduleRow(){
  if (!CAN_EDIT) return;
  const schedule = normalizeRepairSchedule();
  schedule.objects.push(blankRepairScheduleObject((schedule.columns || []).length));
  markDirty(true);
  render();
}
function deleteRepairScheduleRow(index){
  if (!CAN_EDIT) return;
  const schedule = normalizeRepairSchedule();
  if (schedule.objects.length <= 1) return;
  const rowIndex = Number.isFinite(index) ? index : schedule.objects.length - 1;
  schedule.objects.splice(rowIndex, 1);
  markDirty(true);
  render();
}
function openRepairSchedulePeriodicity(){
  if (!CAN_EDIT) return;
  const periodicity = normalizeRepairPeriodicity();
  const body = document.getElementById('repairPeriodicityModalBody');
  const modal = document.getElementById('repairPeriodicityModal');
  if (!body || !modal) return;
  body.innerHTML = `
    <div style="display:grid; gap:10px;">
      <div class="table-wrap repair-periodicity-wrap">
        <table class="compact repair-periodicity-table">
          <colgroup>
            <col style="width:150px">
            <col style="width:120px">
            <col style="width:120px">
            <col style="width:120px">
            <col style="width:120px">
            <col style="width:120px">
          </colgroup>
          <thead>
            <tr>
              <th>Серия</th>
              ${REPAIR_PERIODICITY_COLUMNS.map((label) => `<th>${label}</th>`).join('')}
            </tr>
          </thead>
          <tbody>
            ${periodicity.series.map((series, rowIdx) => `
              <tr>
                <td>${repairPeriodicityCell(`series.${rowIdx}`, series, 'cell', rowIdx, 0)}</td>
                ${periodicity.values[rowIdx].map((value, colIdx) => `<td>${repairPeriodicityCell(`values.${rowIdx}.${colIdx}`, value, 'cell center', rowIdx, colIdx + 1)}</td>`).join('')}
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
  applyRepairPeriodicitySelectionClasses();
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
}
function repairPeriodicityCell(path, value, cls='cell', rowIdx=null, colIdx=null){
  const ro = CAN_EDIT ? '' : 'readonly';
  const gridAttrs = Number.isFinite(rowIdx) && Number.isFinite(colIdx)
    ? ` data-grid="repair-periodicity" data-row="${rowIdx}" data-col="${colIdx}" onfocus="setLastCell(this)" onmousedown="beginGridSelection('repair-periodicity', event)" onmouseenter="extendGridSelection('repair-periodicity', event)" onmouseup="endGridSelection()" oncopy="handleGridCopy(event)" onpaste="handleGridPaste(event)" onkeydown="handleGridKeydown(event)"`
    : '';
  return `<input ${ro} class="${cls}" data-periodicity="1" data-path="${path}" value="${esc(value || '')}"${gridAttrs} oninput="handleRepairPeriodicityInput(this)">`;
}
function saveRepairSchedulePeriodicity(){
  if (!CAN_EDIT) return;
  normalizeRepairPeriodicity();
  updateRepairScheduleDerivedValues();
  markDirty(true);
  render();
  closeRepairPeriodicityModal();
}
function closeRepairPeriodicityModal(){
  const modal = document.getElementById('repairPeriodicityModal');
  if (!modal) return;
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
}
function handleRepairPeriodicityInput(el){
  if (!el || !el.dataset || !el.dataset.periodicity) return;
  const path = String(el.dataset.path || '');
  const parts = path.split('.');
  const periodicity = normalizeRepairPeriodicity();
  const value = String(el.value ?? '').toUpperCase();
  if (el.value !== value) el.value = value;
  if (parts[0] === 'series' && parts.length === 2) {
    const rowIdx = Number(parts[1]);
    if (Number.isFinite(rowIdx) && periodicity.series[rowIdx] !== undefined) periodicity.series[rowIdx] = value;
  } else if (parts[0] === 'values' && parts.length === 3) {
    const rowIdx = Number(parts[1]);
    const colIdx = Number(parts[2]);
    if (Number.isFinite(rowIdx) && Number.isFinite(colIdx) && periodicity.values[rowIdx] && periodicity.values[rowIdx][colIdx] !== undefined) {
      periodicity.values[rowIdx][colIdx] = value;
    }
  }
  updateRepairScheduleDerivedValues();
  markDirty(true);
}
function handleRepairPeriodicityPaste(e){
  const target = e && e.target;
  if (!target || !target.dataset || !target.dataset.periodicity) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  const path = String(target.dataset.path || '');
  const parts = path.split('.');
  if (parts.length < 2) return;
  const periodicity = normalizeRepairPeriodicity();
  const rows = String(text).replace(/\r/g, '').split('\n').map((line) => line.split('\t'));
  while (rows.length && rows[rows.length - 1].every((v) => v === '')) rows.pop();
  if (!rows.length) return;
  const startRow = Number(parts[1]);
  const startCol = parts[0] === 'series' ? 0 : Number(parts[2]);
  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < rows[r].length; c++) {
      const value = String(rows[r][c] ?? '').toUpperCase();
      const rr = startRow + r;
      const cc = startCol + c;
      if (parts[0] === 'series') {
        if (cc === 0 && periodicity.series[rr] !== undefined) periodicity.series[rr] = value;
        else if (cc > 0 && periodicity.values[rr] && periodicity.values[rr][cc - 1] !== undefined) periodicity.values[rr][cc - 1] = value;
      } else if (periodicity.values[rr] && periodicity.values[rr][cc] !== undefined) {
        periodicity.values[rr][cc] = value;
      }
    }
  }
  e.preventDefault();
  updateRepairScheduleDerivedValues();
  markDirty(true);
  render();
}
function unitKeyFromCells(cells){
  const series = String(cells?.[1] ?? '').trim().toUpperCase();
  const number = String(cells?.[2] ?? '').trim().toUpperCase();
  return series && number ? `${series}|${number}` : '';
}
function latestKpMeasurementByUnit(){
  const result = new Map();
  const measurements = appState?.repair_summary?.kp_measurements || [];
  measurements.forEach((item) => {
    const number = String(item?.number ?? '').trim().toUpperCase();
    const date = parseRepairDate(item?.measurementDate);
    if (!number || !date) return;
    const time = repairDateTime(date);
    (appState.months || []).forEach((month) => {
      [...(month.plan || []), ...(month.fact || [])].forEach((row) => {
        const cells = row?.cells || [];
        const rowNumber = String(cells[2] ?? '').trim().toUpperCase();
        if (rowNumber !== number) return;
        const key = unitKeyFromCells(cells);
        if (!key) return;
        const prev = result.get(key);
        if (!prev || time > prev.time) result.set(key, { date, time });
      });
    });
  });
  return result;
}
function kpRecheckPlanHighlights(){
  const latestByUnit = latestKpMeasurementByUnit();
  const bestByUnit = new Map();
  (appState.months || []).forEach((month, monthIndex) => {
    const monthNumber = Number(month?.month || monthIndex + 1);
    if (!Number.isFinite(monthNumber)) return;
    (month.plan || []).forEach((row, rowIndex) => {
      const cells = row?.cells || [];
      const unitKey = unitKeyFromCells(cells);
      const latest = latestByUnit.get(unitKey);
      if (!unitKey || !latest) return;
      const deadline = addRepairDays(latest.date, KP_RECHECK_DAYS);
      const deadlineTime = repairDateTime(deadline);
      if (!Number.isFinite(deadlineTime)) return;
      for (let col = 4; col < 4 + Number(month.days || 0); col++) {
        if (!normalizeRepairCode(cells[col])) continue;
        const day = col - 3;
        const candidateDate = new Date(Number(appState.year), monthNumber - 1, day);
        const candidateTime = repairDateTime(candidateDate);
        if (!Number.isFinite(candidateTime) || candidateTime > deadlineTime) continue;
        const prev = bestByUnit.get(unitKey);
        if (!prev || candidateTime > prev.time) {
          bestByUnit.set(unitKey, { time: candidateTime, monthIndex, rowIndex, col });
        }
      }
    });
  });
  return new Set(Array.from(bestByUnit.values()).map((item) => `${item.monthIndex}|${item.rowIndex}|${item.col}`));
}
function renderMonthTable(type, title, m, headers){
  const kpHighlights = type === 'plan' ? kpRecheckPlanHighlights() : new Set();
  const tableRows = m[type].map((row, rIdx) => {
    const rowHtml = [];
    rowHtml.push(`<td class="col-idx"><div class="rownum"><span>${rIdx+1}</span></div></td>`);
    rowHtml.push(`<td class="col-series">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.1`, row.cells[1] || '', 'cell', ui.monthIndex, type, rIdx, 1) }</td>`);
    rowHtml.push(`<td class="col-number">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.2`, row.cells[2] || '', 'cell', ui.monthIndex, type, rIdx, 2) }</td>`);
    rowHtml.push(`<td class="col-cat">${catButton(ui.monthIndex, type, rIdx, row.excluded)}</td>`);
    for (let d=0; d<m.days; d++) {
      const cls = dayClass(m.month, d + 1);
      const colIndex = 4 + d;
      const isKpHighlight = type === 'plan' && kpHighlights.has(`${ui.monthIndex}|${rIdx}|${colIndex}`);
      const inputStyle = row.excluded ? 'color:#9aa5b1;' : '';
      rowHtml.push(`<td class="col-day ${cls}${isKpHighlight ? ' kp-recheck-cell' : ''}">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${colIndex}`, row.cells[colIndex] || '', `cell small center ${cls} day-cell${isKpHighlight ? ' kp-recheck-input' : ''}`, ui.monthIndex, type, rIdx, colIndex, inputStyle) }</td>`);
    }
    rowHtml.push(`<td class="col-note">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${4+m.days}`, row.cells[4+m.days] || '', 'cell', ui.monthIndex, type, rIdx, 4+m.days) }</td>`);
    return `<tr class="${row.excluded ? 'excluded-row' : ''}">${rowHtml.join('')}</tr>`;
  }).join('');
  const headHtml = headers.map((h, idx) => {
    if (idx < 4 || idx === headers.length - 1) return `<th>${h}</th>`;
    const day = idx - 3;
    return `<th class="${dayClass(m.month, day)}">${h}</th>`;
  }).join('');
  const colHtml = [
    '<col style="width:45px">',
    '<col style="width:var(--series-col-width)">',
    '<col style="width:var(--number-col-width)">',
    '<col style="width:var(--cat-col-width)">',
    ...Array.from({length:m.days}, (_, d) => `<col style="width:36px" class="${dayClass(m.month, d + 1)}">`),
    '<col style="width:120px">'
  ].join('');
  const controlsHtml = type === 'plan' ? rowActionsHtml() : rowActionsSpacerHtml();
  return `
    <div class="section-head month-table-head" style="margin-top:16px;">
      <div class="month-table-actions">
        ${repairButtonsHtml()}
      </div>
      <div class="section-title month-table-title">${title}</div>
      ${controlsHtml}
    </div>
    <div class="table-wrap month-table-wrap">
      <table class="compact month-table">
        <colgroup>${colHtml}</colgroup>
        <thead><tr>${headHtml}</tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;
}
function catButton(monthIndex, type, rowIndex, excluded){
  const label = excluded ? '↺' : '–';
  return `<button class="rowbtn cat-toggle" onclick="toggleExcluded(${monthIndex},'${type}',${rowIndex})">${label}</button>`;
}
function insertRepair(text){
  if (!CAN_EDIT) return;
  const el = document.activeElement;
  const cell = (el && el.dataset && el.dataset.month !== undefined) ? el : null;
  const targetCell = cell || (ui.lastCell ? document.querySelector(`input[data-table="${ui.lastCell.table}"][data-row="${ui.lastCell.row}"][data-col="${ui.lastCell.col}"]`) : null);
  if (!targetCell || !targetCell.dataset) return;
  const month = currentMonth();
  const row = parseInt(targetCell.dataset.row, 10);
  const col = parseInt(targetCell.dataset.col, 10);
  if (!Number.isFinite(row) || !Number.isFinite(col) || col < 4 || col >= 4 + month.days) return;
  const apply = (targetCol, value) => {
    const target = document.querySelector(`input[data-month="${ui.monthIndex}"][data-table="${targetCell.dataset.table}"][data-row="${row}"][data-col="${targetCol}"]`);
    if (target) {
      target.value = value;
      setPath(target.dataset.path, value);
    }
  };
  apply(col, text);
  const days = REPAIR_AUTO_FILL_DAYS[text] || 0;
  if (!days) return;
  const year = appState.year;
  const day = col - 3;
  let filled = 0;
  let check = day + 1;
  while (filled < days && check <= month.days) {
    if (!isRepairSkipDay(year, month.month, check)) {
      apply(check + 3, text);
      filled += 1;
    }
    check += 1;
  }
}
function renderNorms(){
  const leftRows = [
    { kind:'group', label:'Тепловозы' },
    ...TEM_NORM_ROWS.map((label, idx) => ({ kind:'item', group:'h_tep', idx, label })),
    { kind:'group', label:'Тяговые агрегаты' },
    ...AGR_NORM_ROWS.map((label, idx) => ({ kind:'item', group:'h_agr', idx, label })),
  ];
  const parkRows = Array.from({length:12}, (_, idx) => {
    const month = String(idx + 1).padStart(2, '0');
    const tep = appState.norms.p_tep[idx] || {k: month, v: ''};
    const agr = appState.norms.p_agr[idx] || {k: month, v: ''};
    return { idx, month, tep, agr };
  });
  const rows = Array.from({length: 12}, (_, idx) => ({ left: leftRows[idx] || null, park: parkRows[idx] }));
  const bodyHtml = rows.map((entry, rowIndex) => {
    const left = entry.left;
    const park = entry.park;
    const leftHtml = left && left.kind === 'item'
      ? `<td>${left.label}</td><td>${cell(`norms.${left.group}.${left.idx}.v`, (appState.norms[left.group][left.idx] || {v:''}).v, 'cell center')}</td>`
      : `<td class="group-row" colspan="2">${left ? left.label : ''}</td>`;
    return `<tr onclick="selectRow('norms', ${rowIndex})">${leftHtml}<td>${park.month}</td><td>${cell(`norms.p_tep.${park.idx}.v`, park.tep.v, 'cell center')}</td><td>${cell(`norms.p_agr.${park.idx}.v`, park.agr.v, 'cell center')}</td></tr>`;
  }).join('');
  return `
    <div class="section-head" style="justify-content:center; text-align:center;">
      <div style="width:100%;">
      </div>
    </div>
    <div class="table-wrap" style="margin:0 auto 14px; width:100%; max-width:none; padding:0;">
      <table class="compact norms-table">
        <colgroup>
          <col class="col-name">
          <col class="col-hours">
          <col class="col-month">
          <col class="col-tep">
          <col class="col-agr">
        </colgroup>
        <thead>
          <tr>
            <th rowspan="2">Вид ремонта</th>
            <th rowspan="2">Часы</th>
            <th colspan="3">ПЛАН ИСПРАВНЫХ НА ${appState.year} г.</th>
          </tr>
          <tr>
            <th>Месяц</th>
            <th>Тепловозы</th>
            <th>Тяговые агрегаты</th>
          </tr>
        </thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}
function reportUnitKey(row){
  const cells = row && row.cells ? row.cells : [];
  const series = String(cells[1] ?? '').trim().toUpperCase();
  const number = String(cells[2] ?? '').trim().toUpperCase();
  if (!series || !number) return null;
  return [series, number];
}
function buildRowsByUnit(monthData, tableType){
  const rowsByUnit = {};
  if (!monthData || !monthData[tableType]) return rowsByUnit;
  monthData[tableType].forEach((row, idx) => {
    if (!row || row.excluded) return;
    const key = reportUnitKey(row);
    if (key) rowsByUnit[key.join('|')] = idx;
  });
  return rowsByUnit;
}
function rowCellIsNumeric(row, day){
  if (!row || !row.cells) return false;
  const idx = day + 3;
  const raw = String(row.cells[idx] ?? '').trim();
  if (!raw) return false;
  const numeric = Number(raw.replace(',', '.'));
  return Number.isFinite(numeric);
}
function collectUnplannedStartsAcrossMonths(monthIndex, tableType, rowKey){
  const months = appState.months || [];
  if (!rowKey || !months.length || monthIndex < 0 || monthIndex >= months.length) return [];
  const year = Number(appState.year) || new Date().getFullYear();
  const rowKeyStr = rowKey.join('|');
  const rowMaps = months.slice(0, monthIndex + 1).map((month) => buildRowsByUnit(month, tableType));
  const currMonth = months[monthIndex];
  const currMonthNum = Number(currMonth.month || monthIndex + 1);
  const prevMonthNum = monthIndex > 0 ? Number(months[monthIndex - 1].month || monthIndex) : null;
  const windowStart = prevMonthNum ? new Date(year, prevMonthNum - 1, 26) : new Date(year, currMonthNum - 1, 1);
  const windowEnd = new Date(year, currMonthNum - 1, 25);
  const rowForDate = (date) => {
    const monthIdx = date.getMonth();
    if (monthIdx < 0 || monthIdx >= rowMaps.length) return null;
    const rowIdx = (rowMaps[monthIdx] || {})[rowKeyStr];
    const rows = months[monthIdx][tableType] || [];
    return Number.isInteger(rowIdx) && rowIdx < rows.length ? rows[rowIdx] : null;
  };
  const numericOn = (date) => rowCellIsNumeric(rowForDate(date), date.getDate());
  const starts = [];
  const seen = new Set();
  const addStart = (date) => {
    const key = `${date.getMonth() + 1}-${date.getDate()}`;
    if (seen.has(key)) return;
    seen.add(key);
    starts.push(new Date(date));
  };
  if (numericOn(windowStart)) {
    let start = new Date(windowStart);
    let prev = new Date(start);
    prev.setDate(prev.getDate() - 1);
    while (prev.getFullYear() === year && prev >= new Date(year, 0, 1) && numericOn(prev)) {
      start = new Date(prev);
      prev.setDate(prev.getDate() - 1);
    }
    addStart(start);
  }
  let prevIsNum = numericOn(windowStart);
  for (let day = new Date(windowStart); day <= windowEnd; day.setDate(day.getDate() + 1)) {
    if (day.getTime() === windowStart.getTime()) continue;
    const isNum = numericOn(day);
    if (isNum && !prevIsNum) addStart(day);
    prevIsNum = isNum;
  }
  return starts.map((date) => `Акт № ${String(date.getDate()).padStart(2, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(rowKey[1] || '').trim().toUpperCase()}`);
}
function collectActNumbersFromRow(currRow, monthIndex, tableType, rowKey){
  const cells = currRow && currRow.cells ? currRow.cells : [];
  const note = String(cells[cells.length - 1] ?? '').trim();
  const candidates = collectUnplannedStartsAcrossMonths(monthIndex, tableType, rowKey);
  const seen = new Set();
  const result = [];
  const add = (value) => {
    const clean = String(value || '').replace(/^Акт №\\s*/i, '').trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    result.push(clean);
  };
  candidates.forEach(add);
  if (!result.length && /^Акт №\\s*\\d{2}-\\d{2}-/i.test(note)) add(note);
  return result;
}
function parseActSortKey(act){
  const clean = String(act || '').replace(/^Акт №\\s*/i, '').trim();
  const parts = clean.split('-').map((x) => x.trim());
  if (parts.length < 3) return { month: 99, day: 99, tail: clean };
  const day = Number(parts[0]);
  const month = Number(parts[1]);
  return {
    month: Number.isFinite(month) ? month : 99,
    day: Number.isFinite(day) ? day : 99,
    tail: parts.slice(2).join('-'),
    raw: clean,
  };
}
function compareActsByDate(a, b){
  const aa = parseActSortKey(a);
  const bb = parseActSortKey(b);
  if (aa.month !== bb.month) return aa.month - bb.month;
  if (aa.day !== bb.day) return aa.day - bb.day;
  if (aa.tail !== bb.tail) return aa.tail.localeCompare(bb.tail, 'ru');
  return aa.raw.localeCompare(bb.raw, 'ru');
}
function collectActRowsForMonth(monthIndex){
  const month = appState.months[monthIndex];
  if (!month) return [];
  const savedActs = (appState.acts && appState.acts[month.name]) || {};
  
  const getSaved = (cleanAct) => {
    const prefixed = `Акт № ${cleanAct}`;
    const s1 = savedActs[cleanAct] || {};
    const s2 = savedActs[prefixed] || {};
    return {
      is_done: s1.is_done || s2.is_done || false,
      sap_order_done: s1.sap_order_done || s2.sap_order_done || false
    };
  };

  const rows = [];
  const seen = new Set();
  (month.fact || []).forEach((row, rowIndex) => {
    if (!row || row.excluded) return;
    const key = reportUnitKey(row);
    if (!key) return;
    const acts = collectActNumbersFromRow(row, monthIndex, 'fact', key);
    acts.forEach((act) => {
      const clean = act.replace(/^Акт №\s*/i, '').trim();
      if (seen.has(clean)) return;
      seen.add(clean);
      rows.push({ act: clean, saved: getSaved(clean), rowIndex });
    });
  });
  Object.keys(savedActs).sort().forEach((actKey) => {
    const clean = actKey.replace(/^Акт №\s*/i, '').trim();
    if (seen.has(clean)) return;
    seen.add(clean);
    rows.push({ act: clean, saved: getSaved(clean), rowIndex: null });
  });
  return rows.sort((a, b) => compareActsByDate(a.act, b.act));
}
function renderActs(){
  const month = currentMonth().name;
  const rows = collectActRowsForMonth(ui.monthIndex).map(({ act, saved }) => {
    const x = saved || {};
    return `<tr>
      <td>${esc(act)}</td>
      <td style="text-align:center; font-size:16px;"><button class="act-start" style="width:100%; height:100%; min-height:34px; display:flex; align-items:center; justify-content:center;" ${CAN_EDIT ? '' : 'disabled'} onclick="startAct('${month}', '${act}')">Пуск</button></td>
      <td class="center"><input type="checkbox" ${x.is_done ? 'checked' : ''} ${!CAN_EDIT ? 'disabled' : ''} onchange="setActInfoFlag('${month}', '${act}', 'is_done', this.checked)"></td>
      <td class="center"><input type="checkbox" ${x.sap_order_done ? 'checked' : ''} ${!CAN_EDIT ? 'disabled' : ''} onchange="setActInfoFlag('${month}', '${act}', 'sap_order_done', this.checked)"></td>
    </tr>`;
  }).join('');
  return `
    <div class="section-head">
      <div style="display:flex; justify-content:center; width:100%;">
        ${monthSelectHtml()}
      </div>
    </div>
    <div class="table-wrap" style="width:fit-content; max-width:100%; margin:0 auto;">
      <table class="acts-table">
        <colgroup>
          <col style="width:150px;">
          <col style="width:120px;">
          <col style="width:120px;">
          <col style="width:130px;">
        </colgroup>
        <thead><tr><th>№<br>акта</th><th>Сформировать<br>акт</th><th>Сформирован<br>акт</th><th>Создан заказ<br>в SAP</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4">Нет данных</td></tr>'}</tbody>
      </table>
    </div>
  `;
}
function ensureActStateBucket(month, act){
  if (!appState.acts) appState.acts = {};
  if (!appState.acts[month]) appState.acts[month] = {};
  if (!appState.acts[month][act]) appState.acts[month][act] = { is_done: false, sap_order_done: false };
  return appState.acts[month][act];
}
function setActInfoFlag(month, act, key, value){
  if (!CAN_EDIT) return;
  const bucket = ensureActStateBucket(month, act);
  bucket[key] = !!value;
  markDirty(true);
}
function tu28Month(){
  return appState.months[ui.tu28MonthIndex] || currentMonth();
}
function tu28CandidatesForMonth(monthIndex){
  const month = appState.months[monthIndex];
  if (!month) return [];
  const rows = month.fact || [];
  const candidates = [];
  rows.forEach((row, rowIndex) => {
    if (!row || row.excluded) return;
    const cells = row.cells || [];
    for (let col = 4; col < 4 + month.days; col++) {
      const code = normalizeRepairCode(String(cells[col] ?? ''));
      if (['ТО3','ТР1','ТР2','ТР3','СР','КР'].includes(code)) {
        const range = tu28RepairRange(row, month);
        candidates.push({
          rowIndex,
          date: `${String(col - 3).padStart(2, '0')}.${String(month.month).padStart(2, '0')}.${appState.year}`,
          dateFrom: range ? formatRepairDate(range.start) : `${String(col - 3).padStart(2, '0')}.${String(month.month).padStart(2, '0')}.${appState.year}`,
          dateTo: range ? formatRepairDate(range.end) : `${String(col - 3).padStart(2, '0')}.${String(month.month).padStart(2, '0')}.${appState.year}`,
          code: String(cells[col] ?? '').trim().toUpperCase(),
          series: String(cells[1] ?? '').trim(),
          number: String(cells[2] ?? '').trim(),
        });
        break;
      }
    }
  });
  return candidates;
}
function tu28KpMeasurementDates(candidate){
  return repairSummaryKpMeasurementDates({
    number: candidate?.number || '',
    repairCode: candidate?.code || '',
    repairDateFrom: candidate?.dateFrom || candidate?.date || '',
    repairDateTo: candidate?.dateTo || candidate?.date || '',
  });
}
function tu28RepairRange(row, month){
  if (!row || !month) return null;
  const cells = row.cells || [];
  const days = [];
  for (let col = 4; col < 4 + Number(month.days || 0); col++) {
    const code = normalizeRepairCode(String(cells[col] ?? ''));
    if (['ТО3','ТР1','ТР2','ТР3','СР','КР'].includes(code)) days.push(col - 3);
  }
  if (!days.length) return null;
  const year = Number(appState.year);
  const monthNumber = Number(month.month);
  const start = new Date(year, monthNumber - 1, days[0]);
  const end = new Date(year, monthNumber - 1, days[days.length - 1]);
  return { start, end };
}
function selectedTu28RepairRange(){
  const month = tu28Month();
  const row = month && ui.tu28RowIndex != null ? month.fact?.[ui.tu28RowIndex] : null;
  return tu28RepairRange(row, month);
}
function employeeVacationHit(name, range){
  const cleanName = String(name || '').trim();
  if (!cleanName || !range || !range.start || !range.end) return null;
  const vacations = EMPLOYEE_VACATIONS[cleanName] || [];
  for (const item of vacations) {
    const start = parseRepairDate(item.start);
    const end = parseRepairDate(item.end);
    if (!start || !end) continue;
    if (repairDateTime(start) <= repairDateTime(range.end) && repairDateTime(end) >= repairDateTime(range.start)) {
      return item;
    }
  }
  return null;
}
function renderTu28(){
  const month = tu28Month();
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  if (ui.tu28RowIndex == null && candidates.length) ui.tu28RowIndex = candidates[0].rowIndex;
  if (!candidates.some((x) => x.rowIndex === ui.tu28RowIndex)) {
    ui.tu28RowIndex = candidates.length ? candidates[0].rowIndex : null;
  }
  const rows = candidates.map((c, idx) => {
    const kpDates = tu28KpMeasurementDates(c);
    return `
      <tr class="${c.rowIndex === ui.tu28RowIndex ? 'selected-row' : ''}" onclick="selectTu28Row(${c.rowIndex})">
        <td>${idx + 1}</td>
        <td>${esc(c.series)}</td>
        <td>${esc(c.number)}</td>
        <td>${esc(c.date)}</td>
        <td>${esc(c.code)}</td>
        <td><span class="kp-measure-status ${kpDates.length ? 'has-measurement' : 'no-measurement'}">${kpDates.length ? `Есть · ${esc(kpDates.join(', '))}` : 'Нет'}</span></td>
      </tr>
    `;
  }).join('');
  const m = appState.months[ui.tu28MonthIndex];
  const rowObj = m && ui.tu28RowIndex != null ? m.fact[ui.tu28RowIndex] : null;
  const extraList = rowObj && rowObj.tu28_extra ? rowObj.tu28_extra : [];
  const locked = rowObj && rowObj.tu28_locked ? true : false;
  const disableExtra = !rowObj || locked;
  const disableLock = !rowObj || !CAN_EDIT;
  const extraRows = extraList.map((txt, idx) => `
    <div style="display:flex; gap:8px; margin-top:8px;">
      <input type="text" class="input" style="flex:1;" value="${esc(txt)}" ${disableExtra ? 'disabled' : ''} onchange="updateTu28Extra(${idx}, this.value)">
      <button class="danger" style="width:40px;" ${disableExtra ? 'disabled' : ''} onclick="removeTu28Extra(${idx})">🗑</button>
    </div>
  `).join('');
  return `
    <div class="section-head">
      <div style="display:flex; justify-content:center; width:100%;">
        <select id="tu28MonthSelect" onchange="setTu28Month(this.value)" style="border:1px solid var(--line); border-radius:8px; background:#fff; padding:10px 12px; font:inherit;">
          ${appState.months.map((m, i) => `<option value="${i}" ${i === ui.tu28MonthIndex ? 'selected' : ''}>${m.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="table-wrap" style="margin:0 auto; width:fit-content; max-width:100%;">
      <table class="acts-table" style="width:max-content; min-width:0; table-layout:auto;">
        <colgroup>
          <col style="width:70px;">
          <col style="width:160px;">
          <col style="width:120px;">
          <col style="width:120px;">
          <col style="width:130px;">
          <col style="width:170px;">
        </colgroup>
        <thead>
          <tr>
            <th>№</th>
            <th>Серия</th>
            <th>Номер</th>
            <th>Дата</th>
            <th>Ремонт</th>
            <th>Замер КП</th>
          </tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="6">В месяце нет ремонтов для ТУ-28</td></tr>'}</tbody>
      </table>
    </div>
    <div style="margin-top:16px; padding:0 8px; text-align:left; max-width:600px; margin-left:auto; margin-right:auto;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <strong style="color:var(--text); font-size:16px;">Дополнительные работы:</strong>
            <label style="display:flex; align-items:center; gap:8px; font-size:14px; color:var(--text); cursor:pointer;">
                <input type="checkbox" ${locked ? 'checked' : ''} ${disableLock ? 'disabled' : ''} onchange="toggleTu28Locked(this.checked)">
                Блокировать редактирование
            </label>
        </div>
        ${extraRows}
        <div style="margin-top:12px;">
            <button onclick="addTu28Extra()" style="background:#e2e8f0; color:#102033; font-weight:600; padding:6px 12px; border-radius:6px; font-size:13px;" ${disableExtra ? 'disabled' : ''}>+ Добавить Доп. ремонт</button>
        </div>
    </div>
  `;
}
function renderTu28Staff(){
  const rows = [
    "Дизель, топливная, вспом. оборуд.",
    "Экипаж",
    "Экипаж",
    "Аккумуляторная батарея",
    "Электрические машины",
    "Эл. аппаратура, КИП, АЛСН, рация",
    "Тормозное оборудование",
  ];
  const range = selectedTu28RepairRange();
  const currentStaff = ui.tu28Staff[ui.tu28RowIndex] || [];
  const optionHtml = (current) => ['<option value=""></option>'].concat(EMPLOYEE_NAMES.map((name) => {
    const vacation = employeeVacationHit(name, range);
    const selected = name === current ? ' selected' : '';
    const label = vacation ? `${name} - отпуск ${vacation.label || ''}` : name;
    return `<option value="${esc(name)}"${selected}>${esc(label)}</option>`;
  })).join('');
  const tableRows = rows.map((label, idx) => {
    const current = currentStaff[idx] || '';
    const vacation = employeeVacationHit(current, range);
    return `
      <tr class="${vacation ? 'tu28-vacation-row' : ''}">
        <td>${idx + 1}</td>
        <td>${esc(label)}</td>
        <td>
          <select data-index="${idx}" class="tu28-staff-select">
            ${optionHtml(current)}
          </select>
          ${vacation ? `<div class="tu28-vacation-note">Отпуск ${esc(vacation.label || '')}</div>` : ''}
        </td>
      </tr>
    `;
  }).join('');
  return `
    <div style="margin-bottom:10px; font-weight:700;">Выберите ФИО исполнителей из списка:</div>
    <div class="table-wrap" style="margin:0 auto; width:fit-content; max-width:100%;">
      <table class="acts-table" style="width:max-content; table-layout:auto;">
        <colgroup>
          <col style="width:40px;">
          <col style="width:auto;">
          <col style="width:260px;">
        </colgroup>
        <thead>
          <tr>
            <th>#</th>
            <th>Вид работ (узел)</th>
            <th>ФИО</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;
}
async function saveTu28ExtraLocal() {
  const m = appState.months[ui.tu28MonthIndex];
  if (!m || ui.tu28RowIndex == null) return;
  const rowObj = m.fact[ui.tu28RowIndex];
  if (!rowObj || rowObj.tu28_locked) return;
  const payload = {
    year: appState.year,
    month_name: m.name,
    r: ui.tu28RowIndex,
    extra: rowObj.tu28_extra || []
  };
  await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/tu28_extra`, { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(payload) });
  if (CAN_EDIT) markDirty(true);
}
function addTu28Extra(){
  const m = appState.months[ui.tu28MonthIndex];
  if (!m || ui.tu28RowIndex == null) return;
  const rowObj = m.fact[ui.tu28RowIndex];
  if (!rowObj || rowObj.tu28_locked) return;
  if (!rowObj.tu28_extra) rowObj.tu28_extra = [];
  rowObj.tu28_extra.push("");
  saveTu28ExtraLocal();
  render();
}
function updateTu28Extra(idx, val){
  const m = appState.months[ui.tu28MonthIndex];
  if (!m || ui.tu28RowIndex == null) return;
  const rowObj = m.fact[ui.tu28RowIndex];
  if (!rowObj || rowObj.tu28_locked) return;
  rowObj.tu28_extra[idx] = val;
  saveTu28ExtraLocal();
}
function toggleTu28Locked(checked) {
  if (!CAN_EDIT) return;
  const m = appState.months[ui.tu28MonthIndex];
  if (!m || ui.tu28RowIndex == null) return;
  const rowObj = m.fact[ui.tu28RowIndex];
  if (!rowObj) return;
  rowObj.tu28_locked = checked;
  markDirty(true);
  document.getElementById('tu28ModalBody').innerHTML = renderTu28();
}
function removeTu28Extra(idx){
  const m = appState.months[ui.tu28MonthIndex];
  if (!m || ui.tu28RowIndex == null) return;
  const rowObj = m.fact[ui.tu28RowIndex];
  if (!rowObj || rowObj.tu28_locked) return;
  if (rowObj.tu28_extra) {
    rowObj.tu28_extra.splice(idx, 1);
    saveTu28ExtraLocal();
    render();
  }
}
function openTu28Modal(){
  ui.tu28RowIndex = null;
  ui.modal = 'tu28';
  render();
}
function bindTu28StaffSelects(){
  const tu28StaffBody = document.getElementById('tu28StaffModalBody');
  const selects = document.querySelectorAll('.tu28-staff-select');
  selects.forEach((sel) => {
    sel.onchange = (e) => {
      const idx = Number(e.target.dataset.index);
      if (!ui.tu28Staff[ui.tu28RowIndex]) ui.tu28Staff[ui.tu28RowIndex] = [];
      ui.tu28Staff[ui.tu28RowIndex][idx] = e.target.value;
      if (tu28StaffBody) {
        tu28StaffBody.innerHTML = renderTu28Staff();
        requestAnimationFrame(bindTu28StaffSelects);
      }
    };
  });
}
function renderOpenModals(){
  const normsModal = document.getElementById('normsModal');
  const normsBody = document.getElementById('normsModalBody');
  const actsModal = document.getElementById('actsModal');
  const actsBody = document.getElementById('actsModalBody');
  const tu28Modal = document.getElementById('tu28Modal');
  const tu28Body = document.getElementById('tu28ModalBody');
  if (normsModal && normsBody) {
    if (ui.modal === 'norms') {
      normsModal.classList.add('visible');
      normsModal.setAttribute('aria-hidden', 'false');
      normsBody.innerHTML = renderNorms();
    } else {
      normsModal.classList.remove('visible');
      normsModal.setAttribute('aria-hidden', 'true');
      normsBody.innerHTML = '';
    }
  }
  if (actsModal && actsBody) {
    if (ui.modal === 'acts') {
      actsModal.classList.add('visible');
      actsModal.setAttribute('aria-hidden', 'false');
      actsBody.innerHTML = renderActs();
      requestAnimationFrame(() => {
        const select = document.getElementById('actsMonthSelect');
        if (select) select.focus();
      });
    } else {
      actsModal.classList.remove('visible');
      actsModal.setAttribute('aria-hidden', 'true');
      actsBody.innerHTML = '';
    }
  }
  if (tu28Modal && tu28Body) {
    if (ui.modal === 'tu28') {
      tu28Modal.classList.add('visible');
      tu28Modal.setAttribute('aria-hidden', 'false');
      tu28Body.innerHTML = renderTu28();
      const btnTu28Staff = document.getElementById('btnTu28Staff');
      if (btnTu28Staff) {
        btnTu28Staff.style.display = CAN_EDIT ? '' : 'none';
      }
    } else {
      tu28Modal.classList.remove('visible');
      tu28Modal.setAttribute('aria-hidden', 'true');
      tu28Body.innerHTML = '';
    }
  }
  const tu28StaffModal = document.getElementById('tu28StaffModal');
  const tu28StaffBody = document.getElementById('tu28StaffModalBody');
  if (tu28StaffModal && tu28StaffBody) {
    if (ui.modal === 'tu28staff') {
      tu28StaffModal.classList.add('visible');
      tu28StaffModal.setAttribute('aria-hidden', 'false');
      tu28StaffBody.innerHTML = renderTu28Staff();
      requestAnimationFrame(bindTu28StaffSelects);
    } else {
      tu28StaffModal.classList.remove('visible');
      tu28StaffModal.setAttribute('aria-hidden', 'true');
      tu28StaffBody.innerHTML = '';
    }
  }
}
function openSectionModal(section){
  ui.modal = section;
  render();
}
function closeNormsModal(){
  if (ui.modal === 'norms') {
    ui.modal = null;
    render();
  }
}
function closeActsModal(){
  if (ui.modal === 'acts') {
    ui.modal = null;
    render();
  }
}
function closeTu28Modal(){
  if (ui.modal === 'tu28') {
    ui.modal = null;
    render();
  }
}
function openTu28StaffModal(){
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  const row = candidates.find((x) => x.rowIndex === ui.tu28RowIndex) || candidates[0];
  if (!row) { alert('В месяце нет ремонтов для ТУ-28'); return; }
  ui.tu28RowIndex = row.rowIndex;
  const rowObj = appState.months[ui.tu28MonthIndex].fact[ui.tu28RowIndex];
  if (!rowObj.tu28_staff) {
    rowObj.tu28_staff = ["", "", "", "", "", "", ""];
  }
  ui.modal = 'tu28staff';
  render();
}
function closeTu28StaffModal(){
  if (ui.modal === 'tu28staff') {
    ui.modal = 'tu28';
    render();
  }
}
function setTu28Month(index){
  ui.tu28MonthIndex = Number(index);
  ui.tu28RowIndex = null;
  render();
}
function selectTu28Row(rowIndex){
  if (ui.tu28RowIndex !== Number(rowIndex)) {
    ui.tu28RowIndex = Number(rowIndex);
    render();
  }
}
function downloadTu28(){
  const month = tu28Month();
  if (!month) return;
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  const row = candidates.find((x) => x.rowIndex === ui.tu28RowIndex) || candidates[0];
  if (!row) { alert('В месяце нет ремонтов для ТУ-28'); return; }
  const rowObj = appState.months[ui.tu28MonthIndex].fact[row.rowIndex] || {};
  const payload = { month: month.name, year: appState.year, row: row.rowIndex, staff: ui.tu28Staff[row.rowIndex] || [], extra_repairs: rowObj.tu28_extra || [] };
  fetch(`${window.APP_CONFIG.APP_PREFIX}/api/tu28-export`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json; charset=utf-8'},
    body: JSON.stringify(payload),
  }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      try {
        const err = JSON.parse(text || '{}');
        showErrorModal(err.error || text || 'Не удалось сформировать ТУ-28');
      } catch (_) {
        showErrorModal(text ? `Не удалось сформировать ТУ-28:\n${text}` : 'Не удалось сформировать ТУ-28');
      }
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ТУ-28_${month.name}_${appState.year}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    closeTu28StaffModal();
    closeTu28Modal();
  }).catch((err) => showErrorModal(err && err.stack ? err.stack : 'Не удалось сформировать ТУ-28'));
}
function confirmTu28Staff(){
  downloadTu28();
}
async function saveActsAndClose(){
  if (dirty && CAN_EDIT) {
    await saveState();
  }
  closeActsModal();
}
async function startAct(month, act){
  if (!CAN_EDIT) return;
  setActInfoFlag(month, act, 'is_done', true);
  await saveState();
  const url = `${window.APP_CONFIG.APP_PREFIX}/api/act-export?month=${encodeURIComponent(month)}&act=${encodeURIComponent(act)}&year=${encodeURIComponent(appState.year)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
}
let reportDialogState = null;
function openReportModalShell(title){
  document.getElementById('reportTitle').textContent = title;
  document.getElementById('reportBody').innerHTML = '<div class="report-loading">Подготовка отчета...</div>';
  document.getElementById('reportModal').classList.add('visible');
  document.getElementById('reportModal').setAttribute('aria-hidden', 'false');
}
function closeReportModal(){
  const modal = document.getElementById('reportModal');
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
  reportDialogState = null;
}
function setReportNote(key, value){
  if (!CAN_EDIT) return;
  if (!reportDialogState) return;
  const month = reportDialogState.month;
  if (!appState.notes[month]) appState.notes[month] = {};
  appState.notes[month][key] = value;
  reportDialogState.rows = reportDialogState.rows.map((row) => row.key === key ? {...row, note: value} : row);
  autosizeReportNotes();
  markDirty(true);
}
function autosizeReportNotes(){
  document.querySelectorAll('#reportBody textarea.report-note').forEach((el) => {
    el.style.height = '0px';
    el.style.height = `${el.scrollHeight}px`;
  });
}
async function refreshReportDialog(){
  if (!reportDialogState) return;
  if (dirty && CAN_EDIT) {
    await saveState({ refreshReport: false });
  }
  const month = reportDialogState.month;
  const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/report-preview?month=${encodeURIComponent(month)}&year=${encodeURIComponent(reportDialogState.year)}&_=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) return;
  reportDialogState = await res.json();
  renderReportBody();
}
function renderReportBody(){
  if (!reportDialogState) return;
  const excluded = new Set([
    ...((reportDialogState.excluded && reportDialogState.excluded.plan) || []),
    ...((reportDialogState.excluded && reportDialogState.excluded.fact) || []),
  ]);
  const rows = reportDialogState.rows.map((row) => {
    const rowClass = row.key && (row.excluded || excluded.has(row.key)) ? 'excluded-row' : '';
    if (row.kind === 'group') {
      return `
        <tr class="group-row ${rowClass}">
          <td class="group-cell col-report-name">${esc(row.label)}</td>
          <td class="num-cell col-report-num">${esc(row.plan)}</td>
          <td class="num-cell col-report-num">${esc(row.fact)}</td>
          <td class="group-cell col-report-note">${esc(row.note || '')}</td>
        </tr>
      `;
    }
    return `
      <tr class="${rowClass}">
        <td class="col-report-name">${esc(row.label)}</td>
        <td class="num-cell col-report-num">${esc(row.plan)}</td>
        <td class="num-cell col-report-num">${esc(row.fact)}</td>
        <td class="col-report-note"><textarea rows="1" class="report-note" ${CAN_EDIT ? '' : 'readonly'} oninput="setReportNote('${row.key}', this.value)">${esc(row.note || '')}</textarea></td>
      </tr>
    `;
  }).join('');
  document.getElementById('reportBody').innerHTML = `
    <div class="table-wrap report-wrap" style="margin:0 auto; width:fit-content; max-width:100%; padding:0;">
    <table class="report-table">
      <colgroup>
        <col class="col-report-name">
        <col class="col-report-num">
        <col class="col-report-num">
        <col class="col-report-note">
      </colgroup>
      <thead>
        <tr>
          <th>Показатель</th>
          <th>План</th>
          <th>Факт</th>
          <th>Примечание</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    </div>
  `;
  autosizeReportNotes();
}
async function openReport(){
  if (dirty && CAN_EDIT) {
    await saveState();
  }
  const month = currentMonth().name;
  openReportModalShell(`Отчет ${month} ${appState.year}`);
  const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/report-preview?month=${encodeURIComponent(month)}&year=${encodeURIComponent(appState.year)}&_=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) {
    document.getElementById('reportBody').innerHTML = '<div class="report-loading">Не удалось подготовить отчет.</div>';
    return;
  }
  reportDialogState = await res.json();
  renderReportBody();
}
async function saveReportAndClose(){
  if (CAN_EDIT && dirty) {
    await saveState();
  }
  closeReportModal();
}
function downloadReportExcel(){
  if (!reportDialogState) return;
  const month = reportDialogState.month;
  const url = `${window.APP_CONFIG.APP_PREFIX}/api/report-export?month=${encodeURIComponent(month)}&year=${encodeURIComponent(reportDialogState.year)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
}
function cell(path, value, cls, month, table, row, col, style=''){
  const ro = CAN_EDIT ? '' : 'readonly';
  const styleAttr = style ? ` style="${esc(style)}"` : '';
  return `<input ${ro} class="${cls}" data-path="${path}" data-month="${month}" data-table="${table}" data-row="${row}" data-col="${col}" value="${esc(value)}"${styleAttr} onfocus="setLastCell(this)" onmousedown="beginMonthSelection(event)" onmouseenter="extendMonthSelection(event)" onmouseup="endMonthSelection()" oninput="handleGridInput(this)" onkeydown="handleMonthKeydown(event)" oncopy="handleMonthCopy(event)" onpaste="handleMonthPaste(event)">`;
}
function addRow(type){
  if (!CAN_EDIT) return;
  const m = currentMonth();
  m[type].push({ excluded:false, cells:[String(m[type].length+1),'','','',...Array.from({length:m.days},()=>''),''] });
  markDirty(true); render();
}
function deleteRow(type){ if (!CAN_EDIT) return; const m = currentMonth(); if (m[type].length>0) { m[type].pop(); markDirty(true); render(); } }
async function toggleExcluded(mi, tt, r){
  if (!CAN_EDIT) return;
  const m = appState.months[mi];
  const next = !(m[tt][r] && m[tt][r].excluded);
  ['plan', 'fact'].forEach((kind) => {
    if (m[kind] && m[kind][r]) m[kind][r].excluded = next;
  });
  markDirty(true);
  if (reportDialogState && document.getElementById('reportModal').classList.contains('visible')) {
    await refreshReportDialog();
  } else {
    render();
  }
}
function addNorm(){ if (!CAN_EDIT) return; appState.norms.h_tep.push({k:'', v:''}); markDirty(true); render(); }
function removeNorm(cat, idx){ if (!CAN_EDIT) return; appState.norms[cat].splice(idx,1); markDirty(true); render(); }
function selectRow(section, idx){ ui.selected[section] = idx; }
async function saveState(options = {}){
  const refreshReport = options.refreshReport !== false;
  if (!CAN_EDIT) { alert('Нужен вход'); return; }
  updateRepairScheduleDerivedValues();
  setStatus('Сохранение...');
  const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/state`, { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(appState) });
  if (!res.ok) { setStatus('Ошибка'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  setStatus('Сохранено');
  render();
  if (refreshReport && reportDialogState && document.getElementById('reportModal') && document.getElementById('reportModal').classList.contains('visible')) {
    await refreshReportDialog();
  }
}
function downloadJson(){
  const b = new Blob([JSON.stringify(appState, null, 2)], {type:'application/json;charset=utf-8'});
  const u = URL.createObjectURL(b);
  const a = document.createElement('a'); a.href = u; a.download = `grafik_ppr_${appState.year}.json`; a.click(); URL.revokeObjectURL(u);
}
async function importJson(event){
  if (!CAN_EDIT) { alert('Нужен вход'); return; }
  const f = event.target.files[0]; event.target.value = ''; if (!f) return;
  const payload = JSON.parse(await f.text());
  const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/import`, { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(payload) });
  if (!res.ok) { alert('Импорт не удался'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  render();
}
async function loadYear(year){
  const res = await fetch(`${window.APP_CONFIG.APP_PREFIX}/api/state?year=${encodeURIComponent(year)}`);
  if (!res.ok) { alert('Не удалось загрузить год'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  render();
}
async function loadYearFromInput(){
  const year = parseInt(document.getElementById('yearInput').value, 10);
  if (!year) return;
  promptLeave('Есть несохранённые изменения. Сохранить перед открытием другого года?', () => loadYear(year));
}
function requestHomeClick(event){
  if (event) event.preventDefault();
  return promptLeave('Есть несохранённые изменения. Сохранить перед переходом на главную?', () => { location.href = 'http://yrtps.ru/'; });
}
function cancelChanges(){
  if (!CAN_EDIT || !savedMonthsState) return;
  canceledMonthsState = cloneState(appState.months);
  appState.months = cloneState(savedMonthsState);
  markDirty(JSON.stringify(appState) !== JSON.stringify(savedAppState));
  render();
}
function restoreChanges(){
  if (!CAN_EDIT || !canceledMonthsState) return;
  appState.months = cloneState(canceledMonthsState);
  canceledMonthsState = null;
  markDirty(JSON.stringify(appState) !== JSON.stringify(savedAppState));
  render();
}
window.addEventListener('beforeunload', (e)=>{ if (dirty && CAN_EDIT) { e.preventDefault(); e.returnValue=''; } });
window.addEventListener('popstate', () => {
  if (!leaveGuardInstalled || !CAN_EDIT) return;
  promptLeave('Есть несохранённые изменения. Сохранить перед уходом?', () => { location.href = 'http://yrtps.ru/'; });
});
savedAppState = cloneState(appState);
savedMonthsState = cloneState(appState.months);
updateHistoryButtons();
render();

document.addEventListener('focusin', function(e) {
  if (e.target && e.target.classList && (e.target.classList.contains('cell') || e.target.classList.contains('report-note'))) {
    const td = e.target.closest('td');
    if (td) td.classList.add('active-td');
  }
});

document.addEventListener('focusout', function(e) {
  if (e.target && e.target.classList && (e.target.classList.contains('cell') || e.target.classList.contains('report-note'))) {
    const td = e.target.closest('td');
    if (td) td.classList.remove('active-td');
  }
});


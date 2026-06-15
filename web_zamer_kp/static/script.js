
// Global variables injected from index.html
const INPUT_ROWS = 12;
let state = null;
let dirty = false;
let currentRepairType = '';
let savedState = null;
let canceledState = null;
let savedRepairType = '';
let canceledRepairType = '';
let kpRows = [];
let kpSelectedLoco = '';
let kpAllMode = false;
let kpSearchText = '';
let kpLoading = false;
let kpSelectedStatus = null;
let kpSelectionAnchor = null;
let kpSelectionFocus = null;
let kpSuppressFocusSelection = false;
let archiveRows = [];
let archiveSortDesc = true;
let archiveSelectedMeasurementKey = null;
let selectionAnchor = null;
let selectionFocus = null;
let clipboardCache = '';
let archiveSelectionAnchor = null;
let archiveSelectionFocus = null;
let locomotiveInputSource = 'loaded';
let initialLoadPromise = null;
let locomotiveSwitchPromise = null;
let normsRows = [];

function esc(value){
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
}
function fmt(value){
  if (value === null || value === undefined || value === '') return '';
  let s = String(value).trim();
  if (/^-?\d+\.\d+$/.test(s) || /^-?\d+$/.test(s)) return s.replace('.', ',');
  return s;
}
function normalizeRepairType(value){
  return String(value ?? '')
    .trim()
    .toUpperCase()
    .replace(/\s+/g, '')
    .replace(/-/g, '');
}
function parse_float(value){
  if (value === null || value === undefined || value === '') return null;
  const x = parseFloat(String(value ?? '').replace(',', '.'));
  return Number.isFinite(x) ? x : null;
}
function n(value){
  return parse_float(value);
}
function clampCell(row, col){
  return {
    row: Math.max(0, row),
    col: Math.max(0, Math.min(9, col)),
  };
}
function getVisibleAxisCount(){
  return getAxisCount(getCurrentLoco());
}
function isCellInBounds(row, col){
  return row >= 0 && col >= 0 && col < 10 && row < getVisibleAxisCount();
}
function clearSelection(){
  selectionAnchor = null;
  selectionFocus = null;
  document.querySelectorAll('#inputBody td.measure-cell.selected').forEach(td => td.classList.remove('selected'));
}
function selectionRect(){
  if (!selectionAnchor || !selectionFocus) return null;
  const top = Math.min(selectionAnchor.row, selectionFocus.row);
  const bottom = Math.max(selectionAnchor.row, selectionFocus.row);
  const left = Math.min(selectionAnchor.col, selectionFocus.col);
  const right = Math.max(selectionAnchor.col, selectionFocus.col);
  return { top, bottom, left, right };
}
function renderSelectionHighlight(){
  document.querySelectorAll('#inputBody td.measure-cell.selected').forEach(td => {
    td.classList.remove('selected');
    td.style.boxShadow = '';
    const input = td.querySelector('input');
    if (input) input.style.boxShadow = '';
  });
  const rect = selectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#inputBody tr[data-row="${r}"] td.measure-cell[data-col="${c}"]`);
      if (td) {
        td.classList.add('selected');
        const shadows = [];
        if (r === rect.top) shadows.push('inset 0 1.5px 0 0 #2f6fed');
        if (r === rect.bottom) shadows.push('inset 0 -1.5px 0 0 #2f6fed');
        if (c === rect.left) shadows.push('inset 1.5px 0 0 0 #2f6fed');
        if (c === rect.right) shadows.push('inset -1.5px 0 0 0 #2f6fed');
        if (shadows.length > 0) td.style.setProperty('box-shadow', shadows.join(', '), 'important');
        else td.style.boxShadow = '';
      }
    }
  }
}
function selectCell(row, col, extend = false){
  const cell = clampCell(row, col);
  if (!extend || !selectionAnchor) {
    selectionAnchor = cell;
  }
  selectionFocus = cell;
  renderSelectionHighlight();
}
function focusCell(row, col, extend = false){
  const cell = clampCell(row, col);
  if (!isCellInBounds(cell.row, cell.col)) return;
  selectCell(cell.row, cell.col, extend);
  const target = document.querySelector(`input[data-row="${cell.row}"][data-col="${cell.col}"]`);
  if (target) target.focus();
}
function cellValue(row, col){
  return state?.measurements?.[row]?.[col] ?? '';
}
function setCellValue(row, col, value){
  if (!state?.measurements?.[row]) return;
  state.measurements[row][col] = value;
  const input = document.querySelector(`input[data-row="${row}"][data-col="${col}"]`);
  if (input && input.value !== value) input.value = value;
}
function readClipboardText(){
  if (navigator.clipboard?.readText) {
    return navigator.clipboard.readText().catch(() => clipboardCache || '');
  }
  return Promise.resolve(clipboardCache || '');
}
function writeClipboardText(text){
  clipboardCache = String(text ?? '');
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(clipboardCache).catch(() => undefined);
  }
  const ta = document.createElement('textarea');
  ta.value = clipboardCache;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } finally {
    ta.remove();
  }
  return Promise.resolve();
}
function renderNormsTable(){
  const body = document.getElementById('normsBody');
  if (!body) return;
  body.innerHTML = normsRows.map((row, index) => `
    <tr data-index="${index}">
      <td>
        <input
          value="${esc(row.label)}"
          data-field="label"
          data-index="${index}"
          ${row.is_default || !CAN_EDIT ? 'readonly' : ''}
        >
      </td>
      <td>
        <select data-field="condition" data-index="${index}" ${CAN_EDIT ? '' : 'disabled'}>
          <option value="меньше или равно" ${row.condition === 'меньше или равно' ? 'selected' : ''}>меньше или равно</option>
          <option value="больше или равно" ${row.condition === 'больше или равно' ? 'selected' : ''}>больше или равно</option>
        </select>
      </td>
      <td><input value="${esc(fmt(row.yellow_value))}" data-field="yellow_value" data-index="${index}" ${CAN_EDIT ? '' : 'readonly'}></td>
      <td><input value="${esc(fmt(row.red_value))}" data-field="red_value" data-index="${index}" ${CAN_EDIT ? '' : 'readonly'}></td>
    </tr>
  `).join('');
}
async function openNormsDialog(){
  const modal = document.getElementById('normsModal');
  const status = document.getElementById('normsStatus');
  const saveBtn = document.getElementById('saveNormsBtn');
  const addBtn = document.getElementById('addNormBtn');
  if (saveBtn) saveBtn.disabled = !CAN_EDIT;
  if (addBtn) addBtn.disabled = !CAN_EDIT;
  if (status) status.textContent = 'Загрузка...';
  if (modal) modal.classList.add('open');
  try {
    const res = await fetch(`${API}/api/norms`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Не удалось загрузить нормы');
    const payload = await res.json();
    normsRows = payload.rows || [];
    renderNormsTable();
    if (status) status.textContent = CAN_EDIT ? '' : 'Режим просмотра';
  } catch (error) {
    normsRows = [];
    renderNormsTable();
    if (status) status.textContent = error.message || 'Не удалось загрузить нормы';
  }
}
function closeNormsDialog(){
  const modal = document.getElementById('normsModal');
  if (modal) modal.classList.remove('open');
}
function addNormRow(){
  if (!CAN_EDIT) return;
  const suffix = Math.random().toString(16).slice(2, 10);
  normsRows.push({
    metric_key: `custom_${suffix}`,
    label: 'Новый показатель',
    condition: 'меньше или равно',
    yellow_value: '',
    red_value: '',
    is_default: false,
  });
  renderNormsTable();
  const index = normsRows.length - 1;
  const input = document.querySelector(`#normsBody input[data-index="${index}"][data-field="label"]`);
  if (input) input.focus();
}
function collectNormsRows(){
  const rows = normsRows.map(row => ({ ...row }));
  document.querySelectorAll('#normsBody [data-index][data-field]').forEach(input => {
    const index = Number(input.dataset.index);
    const field = input.dataset.field;
    if (!rows[index] || !field) return;
    rows[index][field] = input.value;
  });
  return rows;
}
function applyNormRows(rows){
  if (!state) return;
  const map = {};
  (rows || []).forEach(row => {
    map[row.metric_key] = {
      label: row.label || '',
      condition: row.condition || '',
      yellow_value: row.yellow_value || '',
      red_value: row.red_value || '',
    };
  });
  state.norms = map;
  renderTable();
}
async function saveNormsDialog(){
  if (!CAN_EDIT) return;
  const status = document.getElementById('normsStatus');
  const saveBtn = document.getElementById('saveNormsBtn');
  const rows = collectNormsRows();
  if (status) status.textContent = 'Сохранение...';
  if (saveBtn) saveBtn.disabled = true;
  try {
    const res = await fetch(`${API}/api/norms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    });
    const payload = await res.json();
    if (!res.ok || payload.error) throw new Error(payload.error || 'Не удалось сохранить нормы');
    normsRows = payload.rows || [];
    applyNormRows(normsRows);
    renderNormsTable();
    if (status) status.textContent = 'Сохранено';
    closeNormsDialog();
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось сохранить нормы';
  } finally {
    if (saveBtn) saveBtn.disabled = !CAN_EDIT;
  }
}
async function downloadBlob(url, fallbackName, statusElement){
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.error || 'Не удалось скачать файл');
  }
  const blob = await res.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  if (statusElement) statusElement.textContent = 'Файл скачан';
}
async function downloadArchiveTemplate(){
  const status = document.getElementById('archiveStatus');
  try {
    if (status) status.textContent = 'Файл готовится...';
    await downloadBlob(`${API}/api/archive-excel-template`, 'Шаблон_импорта_архива.xlsx', status);
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось скачать шаблон';
  }
}
function toggleArchiveActionsMenu(event){
  if (event) event.stopPropagation();
  const menu = document.getElementById('archiveActionsMenu');
  if (!menu) return;
  menu.classList.toggle('open');
}
function closeArchiveActionsMenu(){
  const menu = document.getElementById('archiveActionsMenu');
  if (menu) menu.classList.remove('open');
}
document.addEventListener('click', (event) => {
  const menu = document.getElementById('archiveActionsMenu');
  if (!menu || !menu.classList.contains('open')) return;
  if (menu.contains(event.target)) return;
  closeArchiveActionsMenu();
});
function renderArchiveExportLocomotives(){
  const select = document.getElementById('archiveExportLocomotives');
  if (!select) return;
  const numbers = [];
  const seen = new Set();
  archiveRows.forEach(row => {
    const number = String(row.locomotive || '').trim();
    if (number && !seen.has(number)) {
      seen.add(number);
      numbers.push(number);
    }
  });
  (state?.locomotives || LOCOMOTIVE_CHOICES || []).forEach(item => {
    const number = String(item.number || '').trim();
    if (number && !seen.has(number)) {
      seen.add(number);
      numbers.push(number);
    }
  });
  select.innerHTML = numbers.map(number => `<option value="${esc(number)}">${esc(number)}</option>`).join('');
}
function openArchiveExportDialog(){
  const modal = document.getElementById('archiveExportModal');
  const status = document.getElementById('archiveExportStatus');
  renderArchiveExportLocomotives();
  if (status) status.textContent = 'Если локомотивы не выбраны, экспортируются все.';
  if (modal) modal.classList.add('open');
  closeArchiveActionsMenu();
}
function closeArchiveExportDialog(){
  const modal = document.getElementById('archiveExportModal');
  if (modal) modal.classList.remove('open');
}
function selectedArchiveExportLocomotives(){
  const select = document.getElementById('archiveExportLocomotives');
  if (!select) return [];
  return Array.from(select.selectedOptions || []).map(option => option.value).filter(Boolean);
}
function downloadArchiveExport(){
  const status = document.getElementById('archiveExportStatus');
  const params = new URLSearchParams();
  selectedArchiveExportLocomotives().forEach(loco => params.append('locomotive', loco));
  const dateFrom = document.getElementById('archiveExportDateFrom')?.value || '';
  const dateTo = document.getElementById('archiveExportDateTo')?.value || '';
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (status) status.textContent = 'Файл готовится...';
  downloadBlob(`${API}/api/archive-excel-export?${params.toString()}`, 'Экспорт_архива.xlsx', status)
    .then(() => closeArchiveExportDialog())
    .catch(error => {
      if (status) status.textContent = error.message || 'Не удалось скачать экспорт';
    });
}
function chooseArchiveExcelFile(){
  if (!CAN_EDIT) return;
  const input = document.getElementById('archiveExcelFile');
  if (!input) return;
  input.value = '';
  input.click();
}
function readFileAsBase64(file){
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',').pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error('Не удалось прочитать файл'));
    reader.readAsDataURL(file);
  });
}
async function importArchiveExcelFile(file){
  if (!CAN_EDIT || !file) return;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Импорт Excel...';
  try {
    const data = await readFileAsBase64(file);
    const res = await fetch(`${API}/api/archive-excel-import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ filename: file.name, data }),
    });
    const payload = await res.json();
    if (!res.ok || payload.error) throw new Error(payload.error || 'Не удалось импортировать Excel');
    await loadState(getCurrentLoco());
    await loadArchive();
    const skipped = payload.errors?.length ? ` Пропущено строк: ${payload.errors.length}.` : '';
    if (status) status.textContent = `Импортировано замеров: ${payload.imported_measurements}; ячеек: ${payload.imported_cells}.${skipped}`;
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось импортировать Excel';
  }
}
async function copySelectionToClipboard(){
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (selectionFocus || selectionAnchor);
  if (!start || !isCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(cellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  setStatus('Скопировано');
}
function applyPastedBlock(text, startRow, startCol){
  if (!CAN_EDIT || !state) return;
  const rows = String(text ?? '').replace(/\\r/g, '').split('\\n');
  if (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  let touched = false;
  const axisCount = getVisibleAxisCount();
  for (let i = 0; i < rows.length; i += 1) {
    const cells = rows[i].split('\\t');
    for (let j = 0; j < cells.length; j += 1) {
      const tr = startRow + i;
      const tc = startCol + j;
      if (tr >= axisCount || tc >= 10) continue;
      const value = String(cells[j] ?? '').trim().replace('.', ',');
      setCellValue(tr, tc, value);
      touched = true;
    }
  }
  if (!touched) return;
  setDirty(true);
  for (let r = startRow; r < Math.min(axisCount, startRow + rows.length); r += 1) {
    refreshRowClasses(r);
  }
  recalcDiameters();
}
async function pasteClipboardIntoSelection(row, col){
  const text = await readClipboardText();
  if (!text) return;
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : clampCell(row, col);
  applyPastedBlock(text, start.row, start.col);
  focusCell(start.row, start.col);
  setStatus('Вставлено');
}
function clearSelectedCells(){
  if (!CAN_EDIT || !state) return;
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (selectionFocus || selectionAnchor);
  if (!start || !isCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const axisCount = getVisibleAxisCount();
  let touched = false;
  for (let r = start.row; r <= end.row; r += 1) {
    if (r >= axisCount) continue;
    for (let c = start.col; c <= end.col; c += 1) {
      if (c >= 10) continue;
      setCellValue(r, c, '');
      touched = true;
      refreshRowClasses(r);
    }
  }
  if (!touched) return;
  setDirty(true);
  recalcDiameters();
  setStatus('Очищено');
}
function archiveRowMeta(row){
  return archiveRows[row] || null;
}
function archiveMeasurementKey(meta){
  if (!meta) return '';
  return [meta.year, meta.measurement_date, meta.locomotive, meta.repair_type].map(value => String(value ?? '')).join('|');
}
function setArchiveSelectedMeasurement(rowIndex){
  const meta = archiveRowMeta(rowIndex);
  archiveSelectedMeasurementKey = archiveMeasurementKey(meta) || null;
  renderArchiveMeasurementSelection();
}
function renderArchiveMeasurementSelection(){
  document.querySelectorAll('#archiveBody tr').forEach(tr => {
    tr.classList.remove('selected-measurement', 'selected-measurement-start', 'selected-measurement-end');
  });
  if (!archiveSelectedMeasurementKey) return;
  document.querySelectorAll('#archiveBody tr').forEach(tr => {
    const rowIndex = Number(tr.dataset.row || -1);
    const row = archiveRows[rowIndex];
    if (!row) return;
    const key = archiveMeasurementKey(row);
    if (key !== archiveSelectedMeasurementKey) return;
    const prev = archiveRows[rowIndex - 1];
    const next = archiveRows[rowIndex + 1];
    const prevKey = prev ? archiveMeasurementKey(prev) : '';
    const nextKey = next ? archiveMeasurementKey(next) : '';
    tr.classList.add('selected-measurement');
    if (prevKey !== archiveSelectedMeasurementKey) tr.classList.add('selected-measurement-start');
    if (nextKey !== archiveSelectedMeasurementKey) tr.classList.add('selected-measurement-end');
  });
}
function archiveCellElement(row, col){
  return document.querySelector(`#archiveBody input[data-row="${row}"][data-col="${col}"]`);
}
function archiveCellValue(row, col){
  const input = archiveCellElement(row, col);
  if (input) return input.value ?? '';
  return archiveRowMeta(row)?.values?.[col] ?? '';
}
function archiveCellInBounds(row, col){
  return row >= 0 && row < archiveRows.length && col >= 10 && col <= 19;
}
function clearArchiveSelection(){
  archiveSelectionAnchor = null;
  archiveSelectionFocus = null;
  document.querySelectorAll('#archiveBody td.selected').forEach(td => td.classList.remove('selected'));
}
function archiveSelectionRect(){
  if (!archiveSelectionAnchor || !archiveSelectionFocus) return null;
  return {
    top: Math.min(archiveSelectionAnchor.row, archiveSelectionFocus.row),
    bottom: Math.max(archiveSelectionAnchor.row, archiveSelectionFocus.row),
    left: Math.min(archiveSelectionAnchor.col, archiveSelectionFocus.col),
    right: Math.max(archiveSelectionAnchor.col, archiveSelectionFocus.col),
  };
}
function renderArchiveSelectionHighlight(){
  document.querySelectorAll('#archiveBody td.selected').forEach(td => {
    td.classList.remove('selected');
    td.style.boxShadow = '';
    const input = td.querySelector('input');
    if (input) input.style.boxShadow = '';
  });
  const rect = archiveSelectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#archiveBody tr[data-row="${r}"] td[data-col="${c}"]`);
      if (td) {
        td.classList.add('selected');
        const shadows = [];
        if (r === rect.top) shadows.push('inset 0 1.5px 0 0 #2f6fed');
        if (r === rect.bottom) shadows.push('inset 0 -1.5px 0 0 #2f6fed');
        if (c === rect.left) shadows.push('inset 1.5px 0 0 0 #2f6fed');
        if (c === rect.right) shadows.push('inset -1.5px 0 0 0 #2f6fed');
        if (shadows.length > 0) td.style.setProperty('box-shadow', shadows.join(', '), 'important');
        else td.style.boxShadow = '';
      }
    }
  }
}
function selectArchiveCell(row, col, extend = false){
  const cell = { row, col };
  if (!extend || !archiveSelectionAnchor) {
    archiveSelectionAnchor = cell;
  }
  archiveSelectionFocus = cell;
  renderArchiveSelectionHighlight();
}
function focusArchiveCell(row, col, extend = false){
  if (!archiveCellInBounds(row, col)) return;
  selectArchiveCell(row, col, extend);
  const target = archiveCellElement(row, col);
  if (target) target.focus();
}
function archiveCellChangePayload(row, col, value){
  const meta = archiveRowMeta(row);
  if (!meta) return null;
  return {
    year: meta.year,
    measurement_date: meta.measurement_date,
    locomotive: meta.locomotive,
    repair_type: meta.repair_type,
    source_r: meta.source_r,
    display_col: col,
    value,
  };
}
async function saveArchiveChanges(changes, statusText){
  if (!CAN_EDIT) return false;
  if (!changes.length) return true;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = statusText || 'Сохранение архива...';
  const res = await fetch(`${API}/api/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ changes }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await loadArchive();
    if (status) status.textContent = err.error || err.message || 'Ошибка сохранения архива';
    return false;
  }
  await loadArchive();
  clearArchiveSelection();
  if (status) status.textContent = 'Архив обновлен';
  return true;
}
async function copyArchiveSelectionToClipboard(){
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (archiveSelectionFocus || archiveSelectionAnchor);
  if (!start || !archiveCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(archiveCellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Скопировано';
}
async function applyArchivePastedBlock(text, startRow, startCol){
  if (!CAN_EDIT) return false;
  const rows = String(text ?? '').replace(/\\r/g, '').split('\\n');
  if (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return false;
  const changes = [];
  for (let i = 0; i < rows.length; i += 1) {
    const cells = rows[i].split('\t');
    for (let j = 0; j < cells.length; j += 1) {
      const tr = startRow + i;
      const tc = startCol + j;
      if (!archiveCellInBounds(tr, tc)) continue;
      const input = archiveCellElement(tr, tc);
      if (!input) continue;
      const value = String(cells[j] ?? '').trim().replace('.', ',');
      input.value = value;
      input.dataset.original = value;
      const payload = archiveCellChangePayload(tr, tc, value);
      if (payload) changes.push(payload);
    }
  }
  if (!changes.length) return false;
  return saveArchiveChanges(changes, 'Сохранение архива...');
}
async function clearArchiveSelectedCells(){
  if (!CAN_EDIT) return false;
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (archiveSelectionFocus || archiveSelectionAnchor);
  if (!start || !archiveCellInBounds(start.row, start.col)) return false;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const changes = [];
  for (let r = start.row; r <= end.row; r += 1) {
    for (let c = start.col; c <= end.col; c += 1) {
      if (!archiveCellInBounds(r, c)) continue;
      const input = archiveCellElement(r, c);
      if (!input) continue;
      input.value = '';
      input.dataset.original = '';
      const payload = archiveCellChangePayload(r, c, '');
      if (payload) changes.push(payload);
    }
  }
  if (!changes.length) return false;
  return saveArchiveChanges(changes, 'Очистка архива...');
}
function handleArchiveCellMouseDown(event, row, col){
  if (!CAN_EDIT) return true;
  if (event.button !== 0) return true;
  setArchiveSelectedMeasurement(row);
  if (event.shiftKey && archiveSelectionAnchor) {
    selectArchiveCell(archiveSelectionAnchor.row, archiveSelectionAnchor.col, true);
    selectArchiveCell(row, col, true);
  } else {
    selectArchiveCell(row, col, false);
  }
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleArchiveCellFocus(row, col){
  setArchiveSelectedMeasurement(row);
  if (!archiveSelectionAnchor || !archiveSelectionFocus || archiveSelectionAnchor.row !== row || archiveSelectionAnchor.col !== col || archiveSelectionFocus.row !== row || archiveSelectionFocus.col !== col) {
    selectArchiveCell(row, col, false);
  }
}
async function handleArchiveCellChange(row, col, value, input){
  if (!CAN_EDIT) return;
  const meta = archiveRowMeta(row);
  if (!meta) return;
  const current = String(input?.dataset?.original ?? '');
  const next = String(value ?? '').trim().replace('.', ',');
  if (input) input.value = next;
  if (current === next) return;
  const ok = confirm('Вы уверены, что хотите изменить данные в архиве?');
  if (!ok) {
    if (input) input.value = current;
    return;
  }
  const saved = await saveArchiveChanges([archiveCellChangePayload(row, col, next)], 'Сохранение архива...');
  if (!saved && input) {
    input.value = current;
  }
}
async function handleArchiveKeydown(event, row, col){
  const key = event.key;
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    await copyArchiveSelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    const ok = confirm('Вы уверены, что хотите вставить данные в архив?');
    if (!ok) return;
    const text = await readClipboardText();
    if (!text) return;
    const rect = archiveSelectionRect();
    const start = rect ? { row: rect.top, col: rect.left } : { row, col };
    await applyArchivePastedBlock(text, start.row, start.col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    const ok = confirm('Вы уверены, что хотите очистить выбранные ячейки в архиве?');
    if (!ok) return;
    await clearArchiveSelectedCells();
    return;
  }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) return;
  event.preventDefault();
  if (event.shiftKey) {
    if (!archiveSelectionAnchor) archiveSelectionAnchor = { row, col };
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 10) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 19) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < (archiveRows.length - 1)) nextRow = row + 1;
    focusArchiveCell(nextRow, nextCol, true);
    return;
  }
  if (key === 'ArrowLeft' && col > 10) focusArchiveCell(row, col - 1, false);
  if (key === 'ArrowRight' && col < 19) focusArchiveCell(row, col + 1, false);
  if (key === 'ArrowUp' && row > 0) focusArchiveCell(row - 1, col, false);
  if (key === 'ArrowDown' && row < (archiveRows.length - 1)) focusArchiveCell(row + 1, col, false);
}
function setStatus(text){
  document.getElementById('status').textContent = text || '';
}
function setDirty(flag){
  dirty = !!flag;
  updateHistoryButtons();
}
function cloneState(value){
  return value ? JSON.parse(JSON.stringify(value)) : null;
}
function updateHistoryButtons(){
  const cancelBtn = document.getElementById('cancelBtn');
  const restoreBtn = document.getElementById('restoreBtn');
  if (cancelBtn) cancelBtn.style.display = '';
  if (restoreBtn) restoreBtn.style.display = '';
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || !savedState;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledState;
}
function setActiveTab(tab){
  const inputTab = document.getElementById('tabInput');
  const kpTab = document.getElementById('tabKp');
  const archiveTab = document.getElementById('tabArchive');
  const panelInput = document.getElementById('panelInput');
  const panelKp = document.getElementById('panelKp');
  const panelArchive = document.getElementById('panelArchive');
  if (inputTab) inputTab.classList.toggle('active', tab === 'input');
  if (kpTab) kpTab.classList.toggle('active', tab === 'kp');
  if (archiveTab) archiveTab.classList.toggle('active', tab === 'archive');
  if (panelInput) panelInput.classList.toggle('active', tab === 'input');
  if (panelKp) panelKp.classList.toggle('active', tab === 'kp');
  if (panelArchive) panelArchive.classList.toggle('active', tab === 'archive');
}
async function switchTab(tab){
  setActiveTab(tab);
  if (tab === 'kp') {
    renderKpLocomotiveOptions();
    await loadKpData(document.getElementById('kpLocomotive')?.value || kpSelectedLoco || state?.locomotive || '');
  }
  if (tab === 'archive') {
    await loadArchive();
  }
}
function getCurrentLoco(){
  return document.getElementById('locomotive').value.trim();
}
function isKnownLocomotive(number){
  return (LOCOMOTIVE_CHOICES || []).some(item => item.number === String(number || '').trim());
}
function getInventoryItem(number){
  const target = String(number || '').trim();
  if (!target) return null;
  const items = state?.locomotives || LOCOMOTIVE_CHOICES || [];
  return items.find(item => String(item.number || '').trim() === target) || null;
}
function currentWheelPairCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.wheel_pair_count))) {
    return Number(state.wheel_pair_count) || 12;
  }
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.wheelPairCount)) && Number(item.wheelPairCount) > 0) {
    return Math.max(1, Number(item.wheelPairCount) || 12);
  }
  return 12;
}
function currentSectionCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.section_count))) {
    return Math.max(1, Number(state.section_count) || 1);
  }
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.sectionCount)) && Number(item.sectionCount) > 0) {
    return Math.max(1, Number(item.sectionCount) || 1);
  }
  return 0;
}
function getSeries(number){
  const item = (state?.locomotives || []).find(x => x.number === number);
  return item ? (item.series || '') : '';
}
function getAxisCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.wheel_pair_count))) {
    return Math.max(1, Number(state.wheel_pair_count) || 12);
  }
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.wheelPairCount)) && Number(item.wheelPairCount) > 0) {
    return Math.max(1, Number(item.wheelPairCount) || 12);
  }
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) return 12;
  if (text.includes('тэм') || text.includes('tem')) return 6;
  return 12;
}
function defaultSectionCount(axisCount){
  return Number(axisCount) <= 6 ? 1 : 3;
}
function allowedRepairs(number){
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) {
    return ['', 'ТО', 'ТР', 'СР', 'КР'];
  }
  return ['', 'ТО2', 'ТО3', 'ТО4', 'ТР1', 'ТР2', 'ТР3', 'СР', 'КР'];
}
function sectionSpec(axisCount, sectionCount){
  const total = Math.max(1, Number(axisCount) || 1);
  const sections = Math.max(1, Math.min(Number(sectionCount) || defaultSectionCount(total), total));
  const base = Math.floor(total / sections);
  const remainder = total % sections;
  const result = [];
  let start = 0;
  for (let i = 0; i < sections; i += 1) {
    const span = base + (i < remainder ? 1 : 0);
    result.push({ start, span, value: String(i + 1) });
    start += span;
  }
  return result;
}
function measurementClass(col, value){
  const val = n(value);
  if (val === null) return '';
  const norm = state?.norms || {};
  const pair = (left, right) => col === left || col === right;
  let item = null;
  if (pair(0,1)) item = norm.max_prokat;
  if (pair(2,3)) item = norm.min_greben;
  if (pair(4,5)) item = norm.min_krut;
  if (pair(6,7)) item = norm.min_bandage_thickness;
  if (!item) return '';
  const yellow = n(item.yellow_value), red = n(item.red_value);
  const less = String(item.condition || '').toLowerCase().includes('меньше');
  if (red !== null && (less ? val <= red : val >= red)) return 'bad';
  if (yellow !== null && (less ? val <= yellow : val >= yellow)) return 'warn';
  return '';
}
function renderLocoOptions(){
  const input = document.getElementById('locomotive');
  const items = state?.locomotives || [];
  const choices = LOCOMOTIVE_CHOICES || [];
  if (!input) return;
  if (state?.locomotive && (items.some(x => x.number === state.locomotive) || choices.some(x => x.number === state.locomotive))) {
    input.value = state.locomotive;
  } else if (choices.length && !input.value) {
    input.value = choices[0].number;
  }
  renderLocoDropdown('', false);
  renderMeta();
}
function renderLocoDropdown(filterText = '', open = true){
  const dropdown = document.getElementById('locomotiveDropdown');
  const items = (LOCOMOTIVE_CHOICES && LOCOMOTIVE_CHOICES.length ? LOCOMOTIVE_CHOICES : (state?.locomotives || []));
  if (!dropdown) return;
  const textValue = String(filterText || '').trim().toLowerCase();
  const filtered = textValue
    ? items.filter(item => String(item.number || '').toLowerCase().includes(textValue) || String(item.label || '').toLowerCase().includes(textValue))
    : items;
  if (!filtered.length) {
    dropdown.innerHTML = '<button type="button" disabled>Нет совпадений</button>';
    dropdown.classList.toggle('open', !!open);
    return;
  }
  dropdown.innerHTML = filtered
    .map(item => `<button type="button" data-loco="${esc(item.number)}">${esc(item.number)}</button>`)
    .join('');
  dropdown.classList.toggle('open', !!open);
}
function hideLocoDropdown(){
  const dropdown = document.getElementById('locomotiveDropdown');
  if (dropdown) dropdown.classList.remove('open');
}
function showLocoDropdown(){
  renderLocoDropdown('', true);
}
function chooseLoco(value){
  const input = document.getElementById('locomotive');
  if (!input) return;
  locomotiveInputSource = 'picked';
  input.value = value;
  hideLocoDropdown();
  onLocomotiveCommit();
}
function parsePositiveInt(value){
  const n = parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}
async function promptManualLocoCounts(loco){
  const fallbackWheelPairs = 12;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const wheelPairText = prompt(`Локомотив ${loco} не найден в справочнике.\nСколько у него колесных пар?`, String(fallbackWheelPairs));
    if (wheelPairText === null) return null;
    const wheelPairCount = parsePositiveInt(wheelPairText);
    if (!wheelPairCount) {
      alert('Введите положительное число колесных пар.');
      continue;
    }
    const defaultSections = wheelPairCount <= 6 ? 1 : 3;
    const sectionText = prompt(`Сколько секций у локомотива ${loco}?`, String(defaultSections));
    if (sectionText === null) return null;
    const sectionCount = parsePositiveInt(sectionText);
    if (!sectionCount || sectionCount > wheelPairCount) {
      alert('Число секций должно быть положительным и не больше числа колесных пар.');
      continue;
    }
    return { wheel_pair_count: wheelPairCount, section_count: sectionCount };
  }
  return null;
}
function renderArchiveLocomotives(){
  const select = document.getElementById('archiveLocomotive');
  const items = LOCOMOTIVE_CHOICES || [];
  const current = select?.value || '';
  if (!select) return;
  select.innerHTML = items.length
    ? ['<option value="">Все локомотивы</option>']
        .concat(items.map(x => `<option value="${esc(x.number)}">${esc(x.number)}</option>`))
        .join('')
    : '<option value="">Нет локомотивов в справочнике</option>';
  if (current && items.some(x => x.number === current)) {
    select.value = current;
  } else if (state?.locomotive && items.some(x => x.number === state.locomotive)) {
    select.value = state.locomotive;
  }
}
function kpStatusLabel(status, allMode, rowCount){
  if (allMode) {
    return rowCount ? `Показано строк: ${rowCount}` : 'Нет данных по КП';
  }
  if (status === 'green') return 'Диаметры заполнены полностью';
  if (status === 'yellow') return 'Есть неполные данные по диаметрам';
  return 'Данных по диаметрам нет';
}
function renderKpLocomotiveOptions(){
  const select = document.getElementById('kpLocomotive');
  const items = LOCOMOTIVE_CHOICES || [];
  if (!select) return;
  const current = select.value || kpSelectedLoco || state?.locomotive || '';
  select.innerHTML = items.length
    ? ['<option value="">Выберите локомотив</option>', '<option value="Все локомотивы">Все локомотивы</option>']
        .concat(items.map(x => `<option value="${esc(x.number)}">${esc(x.number)}</option>`))
        .join('')
    : '<option value="">Нет локомотивов в справочнике</option>';
  if (current && (current === 'Все локомотивы' || items.some(x => x.number === current))) {
    select.value = current;
  } else if (state?.locomotive && items.some(x => x.number === state.locomotive)) {
    select.value = state.locomotive;
  } else if (items.length) {
    select.value = items[0].number;
  }
  kpSelectedLoco = select.value || '';
}
function renderKpStatus(textValue){
  const status = document.getElementById('kpStatus');
  if (status) status.textContent = textValue || '';
}
function renderKpTable(){
  const head = document.getElementById('kpHead');
  const body = document.getElementById('kpBody');
  const colgroup = document.getElementById('kpColgroup');
  if (!head || !body || !colgroup) return;

  const allMode = kpAllMode;
  if (allMode) clearKpSelection();
  const headers = allMode
    ? ['Локомотив', '№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав']
    : ['№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав'];
  const widths = allMode ? [120, 120, 160, 160, 160] : [160, 160, 160, 160];
  colgroup.innerHTML = widths.map(w => `<col style="width:${w}px">`).join('');
  head.innerHTML = `<tr>${headers.map(value => `<th>${value}</th>`).join('')}</tr>`;

  if (!kpRows.length) {
    clearKpSelection();
    body.innerHTML = `<tr><td colspan="${headers.length}" style="padding:14px;color:var(--muted);">Нет данных</td></tr>`;
    renderKpStatus(kpStatusLabel(null, allMode, 0));
    return;
  }

  body.innerHTML = kpRows.map((row, rowIndex) => {
    const values = row.values || [];
    const search = row.search || values.map(value => String(value ?? '').trim().toLowerCase()).join(' ');
    const editable = !!row.editable && CAN_EDIT && !allMode;
    if (allMode) {
      return `
        <tr data-row="${rowIndex}" data-search="${esc(search)}">
          ${values.map((value, colIndex) => {
            const cls = colIndex === 0 ? 'readonly' : '';
            return `<td class="${cls}">${esc(value)}</td>`;
          }).join('')}
        </tr>`;
    }
    return `
      <tr data-row="${rowIndex}" data-search="${esc(search)}">
        <td class="readonly">${esc(values[0] ?? '')}</td>
        ${[1, 2, 3].map(colIndex => `
          <td data-col="${colIndex}"><input
              value="${esc(fmt(values[colIndex]))}"
              ${editable ? '' : 'readonly'}
              data-row="${rowIndex}"
              data-col="${colIndex}"
              onfocus="handleKpCellFocus(${rowIndex}, ${colIndex}, this)"
              onmousedown="return handleKpCellMouseDown(event, ${rowIndex}, ${colIndex})"
              onchange="handleKpCellChange(${rowIndex}, ${colIndex}, this.value, this)"
              onkeydown="handleKpKeydown(event, ${rowIndex}, ${colIndex})"
            >
          </td>`).join('')}
      </tr>`;
  }).join('');
  applyKpSearchFilter();
  renderKpSelectionHighlight();
  renderKpStatus(kpStatusLabel(kpSelectedStatus, allMode, kpRows.length));
}
function applyKpSearchFilter(){
  const textValue = (document.getElementById('kpSearch')?.value || kpSearchText || '').trim().toLowerCase();
  kpSearchText = textValue;
  document.querySelectorAll('#kpBody tr').forEach(tr => {
    const haystack = (tr.dataset.search || tr.textContent || '').toLowerCase();
    tr.style.display = !textValue || haystack.includes(textValue) ? '' : 'none';
  });
}
function kpCellElement(row, col){
  return document.querySelector(`#kpBody input[data-row="${row}"][data-col="${col}"]`);
}
function kpCellInBounds(row, col){
  return row >= 0 && row < kpRows.length && col >= 1 && col <= 3 && !kpAllMode;
}
function clearKpSelection(){
  kpSelectionAnchor = null;
  kpSelectionFocus = null;
  document.querySelectorAll('#kpBody td.selected').forEach(td => td.classList.remove('selected'));
}
function kpSelectionRect(){
  if (!kpSelectionAnchor || !kpSelectionFocus) return null;
  return {
    top: Math.min(kpSelectionAnchor.row, kpSelectionFocus.row),
    bottom: Math.max(kpSelectionAnchor.row, kpSelectionFocus.row),
    left: Math.min(kpSelectionAnchor.col, kpSelectionFocus.col),
    right: Math.max(kpSelectionAnchor.col, kpSelectionFocus.col),
  };
}
function renderKpSelectionHighlight(){
  document.querySelectorAll('#kpBody td.selected').forEach(td => {
    td.classList.remove('selected');
    td.style.boxShadow = '';
    const input = td.querySelector('input');
    if (input) input.style.boxShadow = '';
  });
  const rect = kpSelectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#kpBody tr[data-row="${r}"] td[data-col="${c}"]`);
      if (td) {
        td.classList.add('selected');
        const shadows = [];
        if (r === rect.top) shadows.push('inset 0 1.5px 0 0 #2f6fed');
        if (r === rect.bottom) shadows.push('inset 0 -1.5px 0 0 #2f6fed');
        if (c === rect.left) shadows.push('inset 1.5px 0 0 0 #2f6fed');
        if (c === rect.right) shadows.push('inset -1.5px 0 0 0 #2f6fed');
        if (shadows.length > 0) td.style.setProperty('box-shadow', shadows.join(', '), 'important');
        else td.style.boxShadow = '';
      }
    }
  }
}
function selectKpCell(row, col, extend = false){
  if (!kpCellInBounds(row, col)) return;
  const cell = { row, col };
  if (!extend || !kpSelectionAnchor) {
    kpSelectionAnchor = cell;
  }
  kpSelectionFocus = cell;
  renderKpSelectionHighlight();
}
function focusKpCell(row, col, extend = false){
  if (!kpCellInBounds(row, col)) return;
  selectKpCell(row, col, extend);
  const input = kpCellElement(row, col);
  if (input) {
    kpSuppressFocusSelection = true;
    input.focus();
    kpSuppressFocusSelection = false;
  }
}
function kpCellValue(row, col){
  const input = kpCellElement(row, col);
  if (input) return input.value || '';
  return kpRows[row]?.values?.[col] ?? '';
}
function setKpCellValue(row, col, value){
  if (!kpRows[row] || !kpCellInBounds(row, col)) return false;
  const next = String(value ?? '').trim().replace('.', ',');
  kpRows[row].values[col] = next;
  const input = kpCellElement(row, col);
  if (input && input.value !== next) input.value = next;
  return true;
}
async function copyKpSelectionToClipboard(){
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (kpSelectionFocus || kpSelectionAnchor);
  if (!start || !kpCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(kpCellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  renderKpStatus('Скопировано');
}
async function pasteKpClipboard(row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const text = await readClipboardText();
  if (!text) return;
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : { row, col };
  const lines = String(text).replace(/\\r/g, '').split('\\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  let touched = false;
  for (let r = 0; r < lines.length; r += 1) {
    const cells = lines[r].split('\\t');
    for (let c = 0; c < cells.length; c += 1) {
      const targetRow = start.row + r;
      const targetCol = start.col + c;
      if (!kpCellInBounds(targetRow, targetCol)) continue;
      touched = setKpCellValue(targetRow, targetCol, cells[c]) || touched;
    }
  }
  if (!touched) return;
  focusKpCell(start.row, start.col);
  await saveKpDataChanges();
}
async function clearKpSelectedCells(row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (kpSelectionFocus || kpSelectionAnchor || { row, col });
  if (!kpCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  let touched = false;
  for (let r = start.row; r <= end.row; r += 1) {
    for (let c = start.col; c <= end.col; c += 1) {
      touched = setKpCellValue(r, c, '') || touched;
    }
  }
  if (!touched) return;
  focusKpCell(start.row, start.col);
  await saveKpDataChanges();
}
function kpRowValues(rowIndex){
  const row = kpRows[rowIndex];
  if (!row) return [];
  return row.values || [];
}
function handleKpCellFocus(row, col, input){
  if (!kpAllMode && !kpSuppressFocusSelection) selectKpCell(row, col, false);
  if (!input) return;
  input.select?.();
}
function handleKpCellMouseDown(event, row, col){
  if (!CAN_EDIT || kpAllMode) return true;
  if (event.button !== 0) return true;
  const input = event.currentTarget;
  if (input) {
    kpSuppressFocusSelection = true;
    input.focus();
    kpSuppressFocusSelection = false;
  }
  if (event.shiftKey && kpSelectionAnchor) {
    selectKpCell(kpSelectionAnchor.row, kpSelectionAnchor.col, true);
    selectKpCell(row, col, true);
  } else {
    selectKpCell(row, col, false);
  }
  if (input) input.select?.();
  event.preventDefault();
  return false;
}
function handleKpCellChange(row, col, value, input){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const next = String(value ?? '').trim().replace('.', ',');
  if (!kpRows[row]) return;
  kpRows[row].values[col] = next;
  if (input) input.value = next;
  saveKpDataChanges();
}
function handleKpKeydown(event, row, col){
  if (kpAllMode) return;
  const key = event.key;
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    copyKpSelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    pasteKpClipboard(row, col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    clearKpSelectedCells(row, col);
    return;
  }
  if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) {
    event.preventDefault();
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 1) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 3) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < kpRows.length - 1) nextRow = row + 1;
    focusKpCell(nextRow, nextCol, event.shiftKey);
  }
}
function collectKpRowsFromView(){
  return kpRows.map((row, rowIndex) => {
    if (kpAllMode) return row.values || [];
    const values = [`${rowIndex + 1}`, '', '', ''];
    values[1] = kpCellElement(rowIndex, 1)?.value ?? row.values?.[1] ?? '';
    values[2] = kpCellElement(rowIndex, 2)?.value ?? row.values?.[2] ?? '';
    values[3] = kpCellElement(rowIndex, 3)?.value ?? row.values?.[3] ?? '';
    return values.map(value => String(value ?? '').trim());
  });
}
async function saveKpDataChanges(){
  if (!CAN_EDIT || kpAllMode || kpLoading) return false;
  const loco = (kpSelectedLoco || '').trim();
  if (!loco || loco === 'Все локомотивы') return false;
  const rows = collectKpRowsFromView();
  kpLoading = true;
  renderKpStatus('Сохранение КП данных...');
    try {
      const res = await fetch(`${API}/api/kp-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ locomotive: loco, rows }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        kpLoading = false;
        await loadKpData(loco);
        renderKpStatus(err.error || 'Не удалось сохранить КП данные');
        return false;
      }
    const payload = await res.json();
    kpSelectedLoco = payload.selected_locomotive || loco;
    kpAllMode = !!payload.all_mode;
    kpSelectedStatus = payload.status || null;
    kpRows = payload.rows || [];
    if (state && kpSelectedLoco && kpSelectedLoco === state.locomotive) {
      state.kp = payload.kp_map || {};
      recalcDiameters();
    }
    renderKpLocomotiveOptions();
    renderKpTable();
    renderKpStatus(kpStatusLabel(kpSelectedStatus, kpAllMode, kpRows.length));
    return true;
  } finally {
    kpLoading = false;
  }
}
async function loadKpData(nextValue){
  const select = document.getElementById('kpLocomotive');
  const value = String(nextValue ?? select?.value ?? kpSelectedLoco ?? state?.locomotive ?? '').trim();
  if (select && value && select.value !== value) {
    select.value = value;
  }
  kpSelectedLoco = value || (state?.locomotive || '');
  clearKpSelection();
  kpLoading = true;
  renderKpStatus('Загрузка КП данных...');
  try {
    const res = await fetch(`${API}/api/kp-data?locomotive=${encodeURIComponent(kpSelectedLoco)}`, { cache: 'no-store' });
    if (!res.ok) {
      kpRows = [];
      kpAllMode = false;
      renderKpTable();
      renderKpStatus('Не удалось загрузить КП данные');
      return;
    }
    const payload = await res.json();
    kpSelectedLoco = payload.selected_locomotive || kpSelectedLoco;
    kpAllMode = !!payload.all_mode;
    kpSelectedStatus = payload.status || null;
    kpRows = payload.rows || [];
    renderKpLocomotiveOptions();
    renderKpTable();
    renderKpStatus(kpStatusLabel(kpSelectedStatus, kpAllMode, kpRows.length));
  } finally {
    kpLoading = false;
  }
}
function renderRepairOptions(){
  const select = document.getElementById('repairType');
  const current = normalizeRepairType(currentRepairType || '');
  const options = allowedRepairs(getCurrentLoco());
  select.innerHTML = options.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
  select.value = options.includes(current) ? current : '';
  currentRepairType = select.value || '';
}
function updateArchiveSortButton(){
  const btn = document.getElementById('archiveSortBtn');
  if (!btn) return;
  if (archiveSortDesc) {
    btn.textContent = '⬇ НОВЫЕ → СТАРЫЕ';
    btn.title = 'Показать замеры от новых к старым';
  } else {
    btn.textContent = '⬆ СТАРЫЕ → НОВЫЕ';
    btn.title = 'Показать замеры от старых к новым';
  }
}
function renderMeta(){
  const meta = document.getElementById('inputMeta');
  if (!meta) return;
  meta.textContent = '';
}
function renderArchiveTable(){
  const tbody = document.getElementById('archiveBody');
  if (!tbody) return;
  if (!archiveRows.length) {
    archiveSelectedMeasurementKey = null;
    tbody.innerHTML = '<tr><td colspan="20" style="padding:14px;color:var(--muted);">Архив пуст</td></tr>';
    return;
  }
  const measurementSpans = new Map();
  const sectionSpans = new Map();
  let start = 0;
  while (start < archiveRows.length) {
    const base = archiveRows[start];
    const key = `${base.year}|${base.measurement_date}|${base.locomotive}|${base.repair_type}`;
    let end = start + 1;
    while (end < archiveRows.length) {
      const row = archiveRows[end];
      const rowKey = `${row.year}|${row.measurement_date}|${row.locomotive}|${row.repair_type}`;
      if (rowKey !== key) break;
      end += 1;
    }
    measurementSpans.set(start, end - start);
    start = end;
  }
  start = 0;
  while (start < archiveRows.length) {
    const base = archiveRows[start];
    const key = `${base.year}|${base.measurement_date}|${base.locomotive}|${base.repair_type}`;
    const section = String(base.section || base.values?.[0] || '1').trim() || '1';
    let end = start + 1;
    while (end < archiveRows.length) {
      const row = archiveRows[end];
      const rowKey = `${row.year}|${row.measurement_date}|${row.locomotive}|${row.repair_type}`;
      const rowSection = String(row.section || row.values?.[0] || '1').trim() || '1';
      if (rowKey !== key || rowSection !== section) break;
      end += 1;
    }
    sectionSpans.set(start, end - start);
    start = end;
  }
  // Определяем секции, которые являются последними в своём замере
  // (нужно для нижней синей рамки rowspan-ячеек статистики)
  const lastSectionStarts = new Set();
  for (const [startIdx, sSpan] of sectionSpans.entries()) {
    const lastRowOfSection = startIdx + sSpan - 1;
    const rowKey = archiveMeasurementKey(archiveRows[startIdx]);
    const nextIdx = lastRowOfSection + 1;
    if (nextIdx >= archiveRows.length || archiveMeasurementKey(archiveRows[nextIdx]) !== rowKey) {
      lastSectionStarts.add(startIdx);
    }
  }
  tbody.innerHTML = archiveRows.map((row, rowIndex) => {
    const values = row.values || [];
    const rowMeta = archiveRows[rowIndex];
    const rowKey = archiveMeasurementKey(rowMeta);
    const prevKey = rowIndex > 0 ? archiveMeasurementKey(archiveRows[rowIndex - 1]) : '';
    const nextKey = rowIndex < archiveRows.length - 1 ? archiveMeasurementKey(archiveRows[rowIndex + 1]) : '';
    const rowClasses = ['measurement-row'];
    if (rowKey && rowKey !== prevKey) rowClasses.push('measurement-start');
    if (rowKey && rowKey !== nextKey) rowClasses.push('measurement-end');
    const rowSection = String(row.section || row.values?.[0] || '1').trim() || '1';
    const prevRow = rowIndex > 0 ? archiveRows[rowIndex - 1] : null;
    const prevRowKey = prevRow ? archiveMeasurementKey(prevRow) : '';
    const prevRowSection = prevRow ? (String(prevRow.section || prevRow.values?.[0] || '1').trim() || '1') : '';
    if (rowKey !== prevRowKey || rowSection !== prevRowSection) rowClasses.push('section-start');
    const cells = values.map((value, index) => {
      if (index === 0) {
        const span = measurementSpans.get(rowIndex);
        if (!span) return '';
        return `<td class="first-col archive-sticky-col measurement-span" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index === 1) {
        const span = sectionSpans.get(rowIndex);
        if (!span) return '';
        const isLast = lastSectionStarts.has(rowIndex);
        return `<td class="section-merged archive-sticky-col${isLast ? ' section-last' : ''}" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index >= 2 && index <= 8) {
        const span = sectionSpans.get(rowIndex);
        if (!span) return '';
        const isLast = lastSectionStarts.has(rowIndex);
        return `<td class="summary-merged archive-sticky-col${isLast ? ' section-last' : ''}" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index >= 10) {
        return `
          <td class="measure-cell archive-raw" data-col="${index}"><input
              value="${esc(fmt(value))}"
              data-row="${rowIndex}"
              data-col="${index}"
              data-original="${esc(value)}"
              ${CAN_EDIT ? '' : 'readonly'}
              onmousedown="return handleArchiveCellMouseDown(event, ${rowIndex}, ${index})"
              onfocus="handleArchiveCellFocus(${rowIndex}, ${index})"
              onchange="handleArchiveCellChange(${rowIndex}, ${index}, this.value, this)"
              onkeydown="handleArchiveKeydown(event, ${rowIndex}, ${index})"
            >
          </td>`;
      }
      const cls = index === 9 ? 'axis-col archive-sticky-col' : 'summary archive-sticky-col';
      return `<td class="${cls}" data-col="${index}">${esc(value)}</td>`;
    }).filter(Boolean).join('');
    return `<tr class="${rowClasses.join(' ')}" data-row="${rowIndex}" data-year="${esc(row.year)}" data-measurement-date="${esc(row.measurement_date)}" data-locomotive="${esc(row.locomotive)}" data-repair-type="${esc(row.repair_type)}" data-source-r="${esc(row.source_r)}" onmousedown="setArchiveSelectedMeasurement(${rowIndex})">${cells}</tr>`;
  }).join('');
  renderArchiveSelectionHighlight();
  renderArchiveMeasurementSelection();
}
function renderTable(){
  const tbody = document.getElementById('inputBody');
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const sectionCount = (state && String(loco) === String(state.locomotive || ''))
    ? Math.max(1, Number(state.section_count) || defaultSectionCount(axisCount))
    : Math.max(1, currentSectionCount(loco) || defaultSectionCount(axisCount));
  const visibleRows = Math.max(1, Math.min(axisCount, INPUT_ROWS));
  const sections = sectionSpec(axisCount, sectionCount);
  const sectionMap = new Map(sections.map(item => [item.start, item]));
  const rows = state?.measurements || [];
  let html = '';
  for (let r = 0; r < visibleRows; r += 1) {
    const section = sectionMap.get(r);
    html += `<tr data-row="${r}">`;
    if (section) {
      html += `<td class="fixed section-col" rowspan="${section.span}">${esc(section.value)}</td>`;
    }
    html += `<td class="fixed number-col">${r + 1}</td>`;
    for (let c = 0; c < 10; c += 1) {
      const value = rows[r]?.[c] ?? '';
      const cls = measurementClass(c, value);
      html += `
        <td class="measure-cell ${cls}" data-col="${c}"><input
            value="${esc(fmt(value))}"
            ${CAN_EDIT ? '' : 'readonly'}
            data-row="${r}"
            data-col="${c}"
            onmousedown="return handleCellMouseDown(event, ${r}, ${c})"
            onfocus="handleCellFocus(${r}, ${c})"
            oninput="handleCellInput(${r}, ${c}, this.value, this)"
            onkeydown="handleKeydown(event, ${r}, ${c})"
          >
        </td>`;
    }
    html += '</tr>';
  }
  tbody.innerHTML = html;
  recalcDiameters();
  renderSelectionHighlight();
}
async function loadArchive(){
  const status = document.getElementById('archiveStatus');
  const loco = document.getElementById('archiveLocomotive')?.value || '';
  const search = document.getElementById('archiveSearch')?.value || '';
  if (status) status.textContent = 'Загрузка архива...';
  clearArchiveSelection();
  updateArchiveSortButton();
  const res = await fetch(`${API}/api/archive?locomotive=${encodeURIComponent(loco)}&search=${encodeURIComponent(search)}&sort=${archiveSortDesc ? 'desc' : 'asc'}`, { cache: 'no-store' });
  if (!res.ok) {
    archiveRows = [];
    renderArchiveTable();
    if (status) status.textContent = 'Не удалось загрузить архив';
    return;
  }
  const payload = await res.json();
  archiveRows = (payload.rows || []).map((row) => ({
    ...row,
    repair_type: normalizeRepairType(row.repair_type),
  }));
  if (archiveSelectedMeasurementKey && !archiveRows.some(row => archiveMeasurementKey(row) === archiveSelectedMeasurementKey)) {
    archiveSelectedMeasurementKey = null;
  }
  renderArchiveTable();
  if (status) status.textContent = archiveRows.length ? `Записей: ${archiveRows.length}` : 'Архив пуст';
}
function toggleArchiveSort(){
  archiveSortDesc = !archiveSortDesc;
  loadArchive();
}
async function deleteSelectedArchiveMeasurement(){
  if (!CAN_EDIT) return;
  const focusMeta = archiveSelectionFocus ? archiveRowMeta(archiveSelectionFocus.row) : null;
  const selectedMeta = focusMeta || archiveRows.find(row => archiveMeasurementKey(row) === archiveSelectedMeasurementKey);
  if (!selectedMeta) {
    alert('Выберите строку архива для удаления.');
    return;
  }
  const labelParts = [selectedMeta.locomotive, selectedMeta.measurement_date, normalizeRepairType(selectedMeta.repair_type)].filter(Boolean);
  const ok = confirm(`Удалить замер из архива?\n\n${labelParts.join(' / ')}`);
  if (!ok) return;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Удаление из архива...';
  const res = await fetch(`${API}/api/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({
      action: 'delete',
      year: selectedMeta.year,
      measurement_date: selectedMeta.measurement_date,
      locomotive: selectedMeta.locomotive,
      repair_type: normalizeRepairType(selectedMeta.repair_type),
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if (status) status.textContent = err.error || err.message || 'Не удалось удалить запись архива';
    return;
  }
  archiveSelectedMeasurementKey = null;
  clearArchiveSelection();
  await loadArchive();
  if (status) status.textContent = 'Запись архива удалена';
}
function refreshRowClasses(rowIndex){
  const row = document.querySelector(`tr[data-row="${rowIndex}"]`);
  if (!row) return;
  for (let c = 0; c < 10; c += 1) {
    const td = row.querySelector(`td[data-col="${c}"]`);
    const input = td ? td.querySelector('input') : null;
    if (!td || !input) continue;
    td.className = measurementClass(c, input.value);
  }
}
function recalcDiameters(){
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const kpMap = state?.kp || {};
  const rows = state?.measurements || [];
  for (let r = 0; r < axisCount; r += 1) {
    const kpRow = r;
    const leftKp = n(kpMap[kpRow]?.[2]);
    const rightKp = n(kpMap[kpRow]?.[3]);
    const leftBand = n(rows[r]?.[6]);
    const rightBand = n(rows[r]?.[7]);
    const leftValue = (leftKp !== null && leftBand !== null) ? String(Math.round(leftKp + leftBand * 2)) : '';
    const rightValue = (rightKp !== null && rightBand !== null) ? String(Math.round(rightKp + rightBand * 2)) : '';
    rows[r][8] = leftValue;
    rows[r][9] = rightValue;
    const leftInput = document.querySelector(`input[data-row="${r}"][data-col="8"]`);
    const rightInput = document.querySelector(`input[data-row="${r}"][data-col="9"]`);
    if (leftInput) leftInput.value = leftValue;
    if (rightInput) rightInput.value = rightValue;
    refreshRowClasses(r);
  }
}
function handleCellInput(row, col, value, inputEl){
  if (!CAN_EDIT) return;
  const next = value.replace('.', ',');
  if (value !== next && inputEl) {
    let start = inputEl.selectionStart;
    inputEl.value = next;
    inputEl.selectionStart = inputEl.selectionEnd = start;
  }
  state.measurements[row][col] = next;
  setDirty(true);
  refreshRowClasses(row);
  if (col === 6 || col === 7) {
    recalcDiameters();
  }
}
function handleCellMouseDown(event, row, col){
  if (!CAN_EDIT) return true;
  if (event.button !== 0) return true;
  if (event.shiftKey && selectionAnchor) {
    selectCell(selectionAnchor.row, selectionAnchor.col, true);
    selectCell(row, col, true);
  } else {
    selectCell(row, col, false);
  }
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleCellFocus(row, col){
  if (!selectionAnchor || !selectionFocus || selectionAnchor.row !== row || selectionAnchor.col !== col || selectionFocus.row !== row || selectionFocus.col !== col) {
    selectCell(row, col, false);
  }
}
function moveFocus(row, col){
  focusCell(row, col, false);
}
function handleKeydown(event, row, col){
  const key = event.key;
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    copySelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    pasteClipboardIntoSelection(row, col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    clearSelectedCells();
    return;
  }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) return;
  event.preventDefault();
  if (event.shiftKey) {
    if (!selectionAnchor) selectionAnchor = { row, col };
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 0) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 9) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < (getVisibleAxisCount() - 1)) nextRow = row + 1;
    focusCell(nextRow, nextCol, true);
    return;
  }
  if (key === 'ArrowLeft' && col > 0) moveFocus(row, col - 1);
  if (key === 'ArrowRight' && col < 9) moveFocus(row, col + 1);
  if (key === 'ArrowUp' && row > 0) moveFocus(row - 1, col);
  if (key === 'ArrowDown' && row < (getVisibleAxisCount() - 1)) moveFocus(row + 1, col);
}
async function fetchStatePayload(locomotive){
  const loco = String(locomotive ?? '').trim();
  const res = await fetch(`${API}/api/state?locomotive=${encodeURIComponent(loco)}`, { cache: 'no-store' });
  if (!res.ok) {
    return null;
  }
  return res.json();
}
async function loadState(nextLocomotive, preloadedState = null, manualConfig = null){
  const loco = (nextLocomotive ?? getCurrentLoco()).trim();
  setStatus('Загрузка...');
  let loaded = preloadedState;
  if (!loaded) {
    loaded = await fetchStatePayload(loco);
  }
  if (!loaded) {
    setStatus('Не удалось загрузить данные');
    return;
  }
  if (manualConfig && !loaded.has_manual_meta) {
    loaded.wheel_pair_count = manualConfig.wheel_pair_count;
    loaded.section_count = manualConfig.section_count;
    const res = await fetch(`${API}/api/state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        locomotive: loaded.locomotive,
        measurement_date: loaded.measurement_date,
        measurements: loaded.measurements,
        wheel_pair_count: loaded.wheel_pair_count,
        section_count: loaded.section_count,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setStatus(err.error || 'Не удалось сохранить параметры локомотива');
      return;
    }
    loaded = await res.json();
  }
  state = loaded;
  locomotiveInputSource = 'loaded';
  state.locomotives = state.locomotives && state.locomotives.length ? state.locomotives : (LOCOMOTIVE_CHOICES || []);
  savedState = cloneState(state);
  canceledState = null;
  currentRepairType = normalizeRepairType(state.repair_type || currentRepairType || '');
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderArchiveLocomotives();
  renderKpLocomotiveOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  updateArchiveSortButton();
  await loadArchive();
  setDirty(false);
  setStatus('Готово');
}
async function maybeSwitchLocomotive(nextValue){
  if (locomotiveSwitchPromise) {
    await locomotiveSwitchPromise.catch(() => undefined);
  }
  locomotiveSwitchPromise = switchLocomotive(String(nextValue ?? '').trim()).finally(() => {
    locomotiveSwitchPromise = null;
  });
  return locomotiveSwitchPromise;
}
async function switchLocomotive(next){
  if (initialLoadPromise) {
    await initialLoadPromise.catch(() => undefined);
  }
  const current = state?.locomotive || '';
  if (!next) {
    const input = document.getElementById('locomotive');
    if (input) input.value = current;
    return;
  }
  if (next === current) {
    locomotiveInputSource = 'loaded';
    renderMeta();
    hideLocoDropdown();
    return;
  }
  if (dirty && current) {
    const ok = confirm('Есть несохранённые изменения. Сохранить перед сменой локомотива?');
    if (!ok) {
      document.getElementById('locomotive').value = current;
      return;
    }
    await saveDraft();
  }
  if (locomotiveInputSource === 'typed') {
    const preview = await fetchStatePayload(next);
    if (!preview) {
      document.getElementById('locomotive').value = current;
      setStatus('Не удалось загрузить данные локомотива');
      return;
    }
    if (preview.has_manual_meta) {
      await loadState(next, preview);
      return;
    }
    const manualConfig = await promptManualLocoCounts(next);
    if (!manualConfig) {
      document.getElementById('locomotive').value = current;
      return;
    }
    await loadState(next, preview, manualConfig);
    return;
  }
  const known = isKnownLocomotive(next);
  if (!known) {
    const preview = await fetchStatePayload(next);
    if (!preview) {
      document.getElementById('locomotive').value = current;
      setStatus('Не удалось загрузить данные локомотива');
      return;
    }
    if (!preview.has_manual_meta) {
      const manualConfig = await promptManualLocoCounts(next);
      if (!manualConfig) {
        document.getElementById('locomotive').value = current;
        return;
      }
      await loadState(next, preview, manualConfig);
      return;
    }
    await loadState(next, preview);
    return;
  }
  await loadState(next);
}
function onLocomotiveCommit(){
  return maybeSwitchLocomotive(document.getElementById('locomotive').value);
}
function onDateChange(){
  setDirty(true);
}
function onRepairChange(){
  currentRepairType = document.getElementById('repairType').value || '';
}
async function saveDraft(){
  if (!CAN_EDIT) return;
  if (!state) return;
  state.locomotive = getCurrentLoco();
  state.measurement_date = document.getElementById('measurementDate').value || state.measurement_date || new Date().toISOString().slice(0, 10);
  currentRepairType = document.getElementById('repairType').value || '';
  setStatus('Сохранение...');
  const res = await fetch(`${API}/api/state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({
      locomotive: state.locomotive,
      measurement_date: state.measurement_date,
      measurements: state.measurements,
      wheel_pair_count: state.wheel_pair_count,
      section_count: state.section_count,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    setStatus(err.error || 'Ошибка сохранения');
    return;
  }
  state = await res.json();
  savedState = cloneState(state);
  canceledState = null;
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderRepairOptions();
  renderMeta();
  renderTable();
  await loadArchive();
  setDirty(false);
  setStatus('Сохранено');
}

function blankMeasurements(){
  return Array.from({ length: 12 }, () => Array.from({ length: 10 }, () => ''));
}

async function saveToArchive(){
  if (!CAN_EDIT) return;
  if (!state) return;
  const payload = {
    locomotive: getCurrentLoco(),
    measurement_date: document.getElementById('measurementDate').value || state.measurement_date || new Date().toISOString().slice(0, 10),
    repair_type: normalizeRepairType(document.getElementById('repairType').value || ''),
    measurements: state.measurements,
    wheel_pair_count: state.wheel_pair_count,
    section_count: state.section_count,
    overwrite: false,
  };
  state.locomotive = payload.locomotive;
  state.measurement_date = payload.measurement_date;
  currentRepairType = normalizeRepairType(payload.repair_type);
  setStatus('Сохранение в архив...');
  const sendRequest = async (overwrite) => {
    const res = await fetch(`${API}/api/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ ...payload, overwrite }),
    });
    return res;
  };

  let res = await sendRequest(false);
  if (res.status === 409) {
    const err = await res.json().catch(() => ({}));
    const ok = confirm((err.message || 'Запись уже есть в архиве.') + '\\n\\nПерезаписать существующую запись?');
    if (!ok) {
      setStatus('Сохранение в архив отменено');
      return;
    }
    res = await sendRequest(true);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    setStatus(err.error || err.message || 'Ошибка архивации');
    return;
  }

  state = await res.json();
  state.measurements = blankMeasurements();
  savedState = cloneState(state);
  canceledState = null;
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  renderRepairOptions();
  renderMeta();
  renderTable();
  await loadArchive();
  setDirty(false);
  setStatus('Данные сохранены в архив');
}

function cancelChanges(){
  if (!CAN_EDIT || !savedState) return;
  canceledState = cloneState(state);
  canceledRepairType = currentRepairType;
  state = cloneState(savedState);
  currentRepairType = savedRepairType || '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderKpLocomotiveOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  setDirty(false);
  setStatus('Отменено');
}

function restoreChanges(){
  if (!CAN_EDIT || !canceledState) return;
  state = cloneState(canceledState);
  currentRepairType = canceledRepairType || '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderKpLocomotiveOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  setDirty(true);
  setStatus('Восстановлено');
  canceledState = null;
  canceledRepairType = '';
}

document.getElementById('locomotive').addEventListener('change', onLocomotiveCommit);
document.getElementById('locomotive').addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    hideLocoDropdown();
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    onLocomotiveCommit();
  }
});
document.getElementById('locomotive').addEventListener('focus', showLocoDropdown);
document.getElementById('locomotive').addEventListener('click', showLocoDropdown);
document.getElementById('locomotive').addEventListener('input', event => {
  locomotiveInputSource = 'typed';
  renderLocoDropdown(event.target.value);
});
document.getElementById('locomotive').addEventListener('blur', () => setTimeout(hideLocoDropdown, 150));
document.getElementById('locomotiveDropdown').addEventListener('mousedown', event => {
  const btn = event.target.closest('button[data-loco]');
  if (!btn) return;
  event.preventDefault();
  chooseLoco(btn.dataset.loco || '');
});
document.addEventListener('mousedown', event => {
  const picker = event.target.closest?.('.loco-picker');
  if (!picker) hideLocoDropdown();
});
document.getElementById('normsModal').addEventListener('mousedown', event => {
  if (event.target.id === 'normsModal') closeNormsDialog();
});
document.getElementById('archiveExportModal').addEventListener('mousedown', event => {
  if (event.target.id === 'archiveExportModal') closeArchiveExportDialog();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.getElementById('normsModal')?.classList.contains('open')) {
    closeNormsDialog();
  }
  if (event.key === 'Escape' && document.getElementById('archiveExportModal')?.classList.contains('open')) {
    closeArchiveExportDialog();
  }
});
document.getElementById('measurementDate').addEventListener('change', onDateChange);
document.getElementById('repairType').addEventListener('change', onRepairChange);
document.getElementById('kpLocomotive').addEventListener('change', e => loadKpData(e.target.value));
document.getElementById('kpSearch').addEventListener('input', applyKpSearchFilter);
document.getElementById('archiveLocomotive').addEventListener('change', loadArchive);
document.getElementById('archiveSearch').addEventListener('input', loadArchive);
document.getElementById('archiveExcelFile').addEventListener('change', event => {
  const file = event.target.files?.[0];
  if (file) importArchiveExcelFile(file);
});
document.getElementById('saveBtn').style.display = CAN_EDIT ? '' : 'none';
updateHistoryButtons();
initialLoadPromise = loadState();
if (!CAN_EDIT) switchTab('kp');

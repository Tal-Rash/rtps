
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
let kpVersions = [];
let kpSelectedVersion = null;
let kpSelectionAnchor = null;
let kpSelectionFocus = null;
let kpSuppressFocusSelection = false;
let wearRows = [];
let wearSelectedLoco = '';
let wearDateFrom = '';
let wearDateTo = '';
let wearLoading = false;
let wearChartPairs = [];
let wearChartMetrics = [];
let wearChartMode = 'pair';
let wearChartPairChoice = '';
let wearChartMetricChoice = '';
let wearPageView = 'charts';
let archiveRows = [];
let archiveSortDesc = true;
let archiveSelectedMeasurementKey = null;
let selectionAnchor = null;
let selectionFocus = null;
let selectionDragging = false;
let clipboardCache = '';
let archiveSelectionAnchor = null;
let archiveSelectionFocus = null;
let archiveSelectionDragging = false;
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
function wearPageViewValue(){
  return wearPageView === 'table' ? 'table' : 'charts';
}
function applyWearPageView(){
  const chartsView = document.getElementById('wearChartsView');
  const tableView = document.getElementById('wearTableView');
  const toggleBtn = document.getElementById('wearViewToggleBtn');
  const exportBtn = document.getElementById('wearChartExportBtn');
  const view = wearPageViewValue();
  if (chartsView) chartsView.classList.toggle('wear-view-hidden', view !== 'charts');
  if (tableView) tableView.classList.toggle('wear-view-hidden', view !== 'table');
  if (toggleBtn) toggleBtn.textContent = view === 'charts' ? 'Таблица' : 'График';
  if (exportBtn) exportBtn.style.display = view === 'charts' ? '' : 'none';
}
function setWearPageView(view){
  wearPageView = String(view).trim() === 'table' ? 'table' : 'charts';
  applyWearPageView();
  writeWearPageState();
}
function toggleWearView(){
  setWearPageView(wearPageViewValue() === 'charts' ? 'table' : 'charts');
  renderWearChartsGrid();
  renderWearAnalysisTable();
}
function readWearPageState(){
  try {
    if (typeof sessionStorage === 'undefined') return null;
    const raw = sessionStorage.getItem('wear_charts_page_state');
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return null;
    return data;
  } catch {
    return null;
  }
}
function writeWearPageState(extra = {}){
  try {
    if (typeof sessionStorage === 'undefined') return;
    const payload = {
      locomotive: String(wearSelectedLoco || '').trim(),
      dateFrom: String(wearDateFrom || '').trim(),
      dateTo: String(wearDateTo || '').trim(),
      mode: wearChartModeValue(),
      pair: String(wearChartPairChoice || document.getElementById('wearChartPair')?.value || '').trim(),
      metric: String(wearChartMetricChoice || document.getElementById('wearChartMetric')?.value || '').trim(),
      view: wearPageViewValue(),
      ...extra,
    };
    sessionStorage.setItem('wear_charts_page_state', JSON.stringify(payload));
  } catch {
    // ignore storage errors
  }
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
    <tr 
      data-index="${index}"
      draggable="${CAN_EDIT ? 'true' : 'false'}"
      ondragstart="handleNormsDragStart(event, ${index})"
      ondragover="handleNormsDragOver(event)"
      ondragleave="handleNormsDragLeave(event)"
      ondrop="handleNormsDrop(event, ${index})"
      ondragend="handleNormsDragEnd(event)"
    >
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

let normsDragIndex = null;
function handleNormsDragStart(e, index) {
  if (!CAN_EDIT) return;
  normsDragIndex = index;
  e.dataTransfer.effectAllowed = 'move';
  e.target.classList.add('dragging');
}
function handleNormsDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const tr = e.target.closest('tr');
  if (tr) tr.classList.add('drag-over');
}
function handleNormsDragLeave(e) {
  const tr = e.target.closest('tr');
  if (tr) tr.classList.remove('drag-over');
}
function handleNormsDragEnd(e) {
  e.target.classList.remove('dragging');
  document.querySelectorAll('#normsBody tr').forEach(tr => tr.classList.remove('drag-over'));
}
function handleNormsDrop(e, index) {
  e.preventDefault();
  handleNormsDragEnd(e);
  if (normsDragIndex === null || normsDragIndex === index || !CAN_EDIT) return;
  const moved = normsRows.splice(normsDragIndex, 1)[0];
  normsRows.splice(index, 0, moved);
  renderNormsTable();
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
  select.innerHTML = numbers.map(number => {
    const item = (state?.locomotives || LOCOMOTIVE_CHOICES || []).find(x => String(x.number).trim() === number);
    const label = String(item?.label || item?.number || number).trim();
    return `<option value="${esc(number)}">${esc(label)}</option>`;
  }).join('');
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
    lines.push(rowValues.join('\t'));
  }
  await writeClipboardText(lines.join('\n'));
  setStatus('Скопировано');
}
function selectionClipboardText(){
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (selectionFocus || selectionAnchor);
  if (!start || !isCellInBounds(start.row, start.col)) return '';
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(cellValue(r, c));
    }
    lines.push(rowValues.join('\t'));
  }
  return lines.join('\n');
}
function handleCellCopy(event){
  const text = selectionClipboardText();
  if (!text) return;
  event.preventDefault();
  event.clipboardData?.setData('text/plain', text);
  clipboardCache = text;
  setStatus('Скопировано');
}
function handleCellPaste(event, row, col){
  if (!CAN_EDIT) return;
  const text = event.clipboardData?.getData('text/plain') || '';
  if (!text) return;
  event.preventDefault();
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : clampCell(row, col);
  applyPastedBlock(text, start.row, start.col);
  focusCell(start.row, start.col);
  setStatus('Вставлено');
}
function applyPastedBlock(text, startRow, startCol){
  if (!CAN_EDIT || !state) return;
  const rows = String(text ?? '').replace(/\r/g, '').split('\n');
  if (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  let touched = false;
  const axisCount = getVisibleAxisCount();
  for (let i = 0; i < rows.length; i += 1) {
    const cells = rows[i].split('\t');
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
    lines.push(rowValues.join('\t'));
  }
  await writeClipboardText(lines.join('\n'));
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Скопировано';
}
function archiveSelectionClipboardText(){
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (archiveSelectionFocus || archiveSelectionAnchor);
  if (!start || !archiveCellInBounds(start.row, start.col)) return '';
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(archiveCellValue(r, c));
    }
    lines.push(rowValues.join('\t'));
  }
  return lines.join('\n');
}
function handleArchiveCellCopy(event){
  const text = archiveSelectionClipboardText();
  if (!text) return;
  event.preventDefault();
  event.clipboardData?.setData('text/plain', text);
  clipboardCache = text;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Скопировано';
}
async function handleArchiveCellPaste(event, row, col){
  if (!CAN_EDIT) return;
  const text = event.clipboardData?.getData('text/plain') || '';
  if (!text) return;
  event.preventDefault();
  const ok = confirm('Вы уверены, что хотите вставить данные в архив?');
  if (!ok) return;
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : { row, col };
  await applyArchivePastedBlock(text, start.row, start.col);
}
async function applyArchivePastedBlock(text, startRow, startCol){
  if (!CAN_EDIT) return false;
  const rows = String(text ?? '').replace(/\r/g, '').split('\n');
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
  archiveSelectionDragging = true;
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleArchiveCellMouseEnter(event, row, col){
  if (!CAN_EDIT || !archiveSelectionDragging || !(event.buttons & 1)) return;
  setArchiveSelectedMeasurement(row);
  selectArchiveCell(row, col, true);
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
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
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
  const wearTab = document.getElementById('tabWear');
  const panelInput = document.getElementById('panelInput');
  const panelKp = document.getElementById('panelKp');
  const panelArchive = document.getElementById('panelArchive');
  const panelWear = document.getElementById('panelWear');
  if (inputTab) inputTab.classList.toggle('active', tab === 'input');
  if (kpTab) kpTab.classList.toggle('active', tab === 'kp');
  if (archiveTab) archiveTab.classList.toggle('active', tab === 'archive');
  if (wearTab) wearTab.classList.toggle('active', tab === 'wear');
  if (panelInput) panelInput.classList.toggle('active', tab === 'input');
  if (panelKp) panelKp.classList.toggle('active', tab === 'kp');
  if (panelArchive) panelArchive.classList.toggle('active', tab === 'archive');
  if (panelWear) panelWear.classList.toggle('active', tab === 'wear');
}
async function switchTab(tab){
  setActiveTab(tab);
  if (tab === 'kp') {
    renderKpLocomotiveOptions();
    await loadKpData(document.getElementById('kpLocomotive')?.value || kpSelectedLoco || state?.locomotive || '').catch(error => {
      console.error(error);
    });
  }
  if (tab === 'archive') {
    await loadArchive().catch(error => {
      console.error(error);
    });
  }
  if (tab === 'wear') {
    renderWearLocomotiveOptions();
    await loadWearAnalysis(document.getElementById('wearLocomotive')?.value || wearSelectedLoco || state?.locomotive || kpSelectedLoco || '').catch(error => {
      console.error(error);
    });
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
function summaryClass(col, value){
  const val = n(value);
  if (val === null) return '';
  const norm = state?.norms || {};
  let item = null;
  if (col === 2) item = norm.max_prokat;
  if (col === 3) item = norm.min_greben;
  if (col === 4) item = norm.min_krut;
  if (col === 5) item = norm.min_bandage_thickness;
  if (col === 6) item = norm.max_diameter_diff;
  if (col === 8) item = norm.prokat_6_count;
  if (!item) return '';
  const yellow = n(item.yellow_value), red = n(item.red_value);
  const less = String(item.condition || '').toLowerCase().includes('меньш');
  if (red !== null && (less ? val <= red : val >= red)) return 'bad';
  if (yellow !== null && (less ? val <= yellow : val >= yellow)) return 'warn';
  return '';
}

function renderLocoOptions(){
  const select = document.getElementById('locomotive');
  const items = (LOCOMOTIVE_CHOICES && LOCOMOTIVE_CHOICES.length ? LOCOMOTIVE_CHOICES : (state?.locomotives || []));
  if (!select) return;
  const current = select.value || state?.locomotive || '';
  select.innerHTML = items.length
    ? items.map(x => {
        const number = String(x.number || '').trim();
        const label = String(x.label || number || '').trim();
        return `<option value="${esc(number)}">${esc(label)}</option>`;
      }).join('')
    : '<option value="">Нет локомотивов</option>';
  if (current && items.some(x => x.number === current)) {
    select.value = current;
  } else if (items.length) {
    select.value = items[0].number;
  }
  renderMeta();
}
function parsePositiveInt(value){
  const n = parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}
function renderArchiveLocomotives(){
  const select = document.getElementById('archiveLocomotive');
  const items = LOCOMOTIVE_CHOICES || [];
  const current = select?.value || '';
  if (!select) return;
  select.innerHTML = items.length
    ? ['<option value="">Все локомотивы</option>']
        .concat(items.map(x => {
          const number = String(x.number || '').trim();
          const label = String(x.label || number || '').trim();
          return `<option value="${esc(number)}">${esc(label)}</option>`;
        }))
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
        .concat(items.map(x => {
          const number = String(x.number || '').trim();
          const label = String(x.label || number || '').trim();
          return `<option value="${esc(number)}">${esc(label)}</option>`;
        }))
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
function renderKpVersionControls(){
  const select = document.getElementById('kpVersion');
  const dateInput = document.getElementById('kpValidTo');
  const newBtn = document.getElementById('kpNewVersionBtn');
  const saveDateBtn = document.getElementById('kpSaveVersionDateBtn');
  const disabled = kpAllMode || !kpSelectedLoco;
  if (select) {
    select.innerHTML = [
      '<option value="">Текущие данные</option>',
      ...kpVersions.map((version) => {
        const label = version.valid_to ? `До ${formatWearDate(version.valid_to)}` : `Версия ${version.id}`;
        return `<option value="${version.id}">${esc(label)}</option>`;
      }),
    ].join('');
    select.value = kpSelectedVersion ? String(kpSelectedVersion.id) : '';
    select.disabled = disabled;
  }
  if (dateInput) {
    dateInput.value = kpSelectedVersion?.valid_to || '';
    dateInput.disabled = disabled;
  }
  if (newBtn) {
    newBtn.style.display = kpSelectedVersion ? 'none' : '';
    newBtn.disabled = disabled || !CAN_EDIT;
  }
  if (saveDateBtn) {
    saveDateBtn.style.display = kpSelectedVersion ? '' : 'none';
    saveDateBtn.disabled = disabled || !CAN_EDIT;
  }
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
    renderKpVersionControls();
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
        ${[0, 1, 2, 3].map(colIndex => `
          <td data-col="${colIndex}"><input
              value="${esc(fmt(values[colIndex]))}"
              ${editable ? '' : 'readonly'}
              data-row="${rowIndex}"
              data-col="${colIndex}"
              onfocus="handleKpCellFocus(${rowIndex}, ${colIndex}, this)"
              onmousedown="return handleKpCellMouseDown(event, ${rowIndex}, ${colIndex})"
              onchange="handleKpCellChange(${rowIndex}, ${colIndex}, this.value, this)"
              onkeydown="handleKpKeydown(event, ${rowIndex}, ${colIndex})"
              onpaste="handleKpCellPaste(event, ${rowIndex}, ${colIndex})"
            >
          </td>`).join('')}
      </tr>`;
  }).join('');
  applyKpSearchFilter();
  renderKpSelectionHighlight();
  renderKpStatus(kpStatusLabel(kpSelectedStatus, allMode, kpRows.length));
  renderKpVersionControls();
}
function renderWearLocomotiveOptions(){
  const select = document.getElementById('wearLocomotive');
  if (!select) return;
  const current = String(wearSelectedLoco || state?.locomotive || kpSelectedLoco || '').trim();
  const options = (LOCOMOTIVE_CHOICES || []).map(item => {
    const number = String(item.number || '').trim();
    const label = String(item.label || number || '').trim();
    return `<option value="${esc(number)}">${esc(label)}</option>`;
  }).join('');
  select.innerHTML = options || '<option value="">Нет локомотивов</option>';
  if (current && [...select.options].some(option => option.value === current)) {
    select.value = current;
  } else if (select.options.length) {
    select.value = select.options[0].value;
  }
  wearSelectedLoco = select.value || current || '';
}
function formatWearDate(value){
  const textValue = String(value ?? '').trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(textValue)) {
    const [year, month, day] = textValue.split('-');
    return `${day}.${month}.${year}`;
  }
  return textValue;
}
function wearNumber(value){
  if (value === null || value === undefined || value === '') return '';
  const parsed = Number(String(value).replace(',', '.'));
  if (!Number.isFinite(parsed)) return String(value);
  if (Math.abs(parsed - Math.round(parsed)) < 1e-9) return String(Math.round(parsed));
  return parsed.toFixed(2).replace(/0+$/, '').replace(/\.$/, '').replace('.', ',');
}
function wearDeltaClass(metric){
  if (!metric) return 'trend-none';
  if (metric.trend === 'worse') return 'trend-worse';
  if (metric.trend === 'better') return 'trend-better';
  if (metric.trend === 'stable') return 'trend-stable';
  return 'trend-none';
}
function wearDeltaText(metric){
  if (!metric) return '';
  if (metric.latest === null || metric.latest === undefined || metric.latest === '') return 'нет данных';
  if (metric.previous === null || metric.previous === undefined || metric.previous === '') return 'нет сравнения';
  const delta = Number(metric.delta);
  if (!Number.isFinite(delta)) return 'нет сравнения';
  const sign = delta > 0 ? '+' : '';
  return `Δ ${sign}${wearNumber(delta)}`;
}
function renderWearSideMetric(metric, sideLabel){
  if (!metric) return '';
  const latest = wearNumber(metric.latest);
  const previous = wearNumber(metric.previous);
  const delta = wearDeltaText(metric);
  const cls = wearDeltaClass(metric);
  const lines = [];
  if (metric.latest !== null && metric.latest !== undefined && metric.latest !== '') {
    lines.push(`<div class="wear-side-value">${esc(sideLabel)} ${esc(latest)}</div>`);
  }
  if (metric.previous !== null && metric.previous !== undefined && metric.previous !== '') {
    lines.push(`<div class="wear-prev">нач.: ${esc(previous)}</div>`);
  }
  lines.push(`<div class="wear-delta ${cls}">${esc(delta)}</div>`);
  return `<div class="wear-side-block ${cls}">${lines.join('')}</div>`;
}
function renderWearAnalysisTable(){
  const tbody = document.getElementById('wearBody');
  const summary = document.getElementById('wearSummary');
  if (!tbody) return;
  if (!wearRows.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="padding:14px;color:var(--muted);">Нет данных для анализа</td></tr>';
    if (summary) summary.textContent = '';
    return;
  }
  if (summary) {
    const filled = wearRows.filter(row => row.session_count > 0).length;
    summary.textContent = `КП: ${wearRows.length} · с историями: ${filled}`;
  }
  tbody.innerHTML = wearRows.map(row => {
    const metricCell = (key) => {
      const metric = row.metrics?.[key] || null;
      const left = metric?.left || null;
      const right = metric?.right || null;
      const leftBlock = renderWearSideMetric(left, 'Л');
      const rightBlock = renderWearSideMetric(right, 'П');
      const cellClass = wearDeltaClass(left || right);
      return `<td class="${cellClass}">${leftBlock}${rightBlock}</td>`;
    };
    const statusClass = row.status_key === 'worse' ? 'trend-worse' : row.status_key === 'better' ? 'trend-better' : row.status_key === 'stable' ? 'trend-stable' : 'trend-none';
    const lastInfo = [formatWearDate(row.last_measurement_date), row.last_repair_type].filter(Boolean).join(' / ');
    return `
      <tr>
        <td class="wear-pair">${esc(String(row.wheel_pair || ''))}</td>
        <td class="wear-last">${esc(lastInfo || '—')}</td>
        <td class="${statusClass}"><span class="wear-badge ${statusClass}">${esc(row.status_label || '—')}</span></td>
        ${metricCell('prokat')}
        ${metricCell('greben')}
        ${metricCell('krut')}
        ${metricCell('bandage_thickness')}
        ${metricCell('diameter')}
      </tr>
    `;
  }).join('');
}
function wearChartNumber(value){
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
}
function wearChartMetricLabel(metricKey){
  const metric = wearChartMetrics.find(item => item && item.key === metricKey);
  return metric?.label || metricKey || '';
}
function wearChartSelectedPair(){
  const select = document.getElementById('wearChartPair');
  const current = String(select?.value || '').trim();
  if (current) return current;
  if (wearChartPairChoice) return String(wearChartPairChoice).trim();
  if (wearChartPairs.length) return String(wearChartPairs[0].wheel_pair || '').trim();
  return '';
}
function wearChartSelectedMetric(){
  const select = document.getElementById('wearChartMetric');
  const current = String(select?.value || '').trim();
  if (current) return current;
  if (wearChartMetricChoice) return String(wearChartMetricChoice).trim();
  if (wearChartMetrics.length) return String(wearChartMetrics[0].key || '').trim();
  return 'prokat';
}
function wearChartModeValue(){
  const select = document.getElementById('wearChartMode');
  const current = String(select?.value || '').trim();
  return current === 'all' ? 'all' : 'pair';
}
function wearChartMetricWorseWhen(metricKey){
  return metricKey === 'prokat' ? 'higher' : 'lower';
}
function wearChartRepresentativeValue(metricKey, left, right){
  const hasLeft = Number.isFinite(left);
  const hasRight = Number.isFinite(right);
  if (!hasLeft && !hasRight) return null;
  if (hasLeft && !hasRight) return left;
  if (!hasLeft && hasRight) return right;
  return wearChartMetricWorseWhen(metricKey) === 'higher' ? Math.max(left, right) : Math.min(left, right);
}
function wearChartBuildSvg(points, metricKey, titlePrefix = ''){
  const width = 900;
  const height = 240;
  const margin = { left: 64, right: 18, top: 30, bottom: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const colors = ['#2f6fed', '#e05a47'];

  const axisLabels = points.map(point => String(point?.measurement_date || '').trim()).filter(Boolean);
  const chartSeries = [
    {
      label: 'Левая',
      color: colors[0],
      values: points.map(point => wearChartNumber(point?.metrics?.[metricKey]?.left)),
    },
    {
      label: 'Правая',
      color: colors[1],
      values: points.map(point => wearChartNumber(point?.metrics?.[metricKey]?.right)),
    },
  ];
  const values = chartSeries.flatMap(series => (series.values || []).filter(value => Number.isFinite(value)));
  if (!axisLabels.length || !values.length) {
    return {
      svg: '',
      emptyText: 'Для выбранной КП и показателя пока нет достаточных данных для графика.',
      firstDate: axisLabels[0] ? formatWearDate(axisLabels[0]) : '',
      lastDate: axisLabels[axisLabels.length - 1] ? formatWearDate(axisLabels[axisLabels.length - 1]) : '',
    };
  }

  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = Math.max(0.5, (max - min) * 0.12);
  min -= pad;
  max += pad;
  const scaleX = (index) => {
    if (axisLabels.length === 1) return margin.left + plotWidth / 2;
    return margin.left + (plotWidth * index) / (axisLabels.length - 1);
  };
  const scaleY = (value) => margin.top + ((max - value) * plotHeight) / (max - min);
  const linePath = (series) => {
    const segments = [];
    let current = [];
    (series.values || []).forEach((value, index) => {
      if (!Number.isFinite(value)) {
        if (current.length) {
          segments.push(current);
          current = [];
        }
        return;
      }
      current.push({ x: scaleX(index), y: scaleY(value) });
    });
    if (current.length) segments.push(current);
    return segments.map(segment => segment.map((pt, idx) => `${idx === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' '));
  };
  const gridLines = [];
  for (let i = 0; i <= 4; i += 1) {
    const y = margin.top + (plotHeight * i) / 4;
    const value = max - ((max - min) * i) / 4;
    gridLines.push(`<line class="wear-chart-grid" x1="${margin.left}" y1="${y.toFixed(1)}" x2="${width - margin.right}" y2="${y.toFixed(1)}"></line>`);
    gridLines.push(`<text class="wear-chart-label" x="${margin.left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end">${esc(wearNumber(value))}</text>`);
  }
  const xLabelStep = Math.max(1, Math.ceil(axisLabels.length / 6));
  const xLabels = axisLabels.map((label, index) => {
    if (axisLabels.length > 1 && index % xLabelStep !== 0 && index !== axisLabels.length - 1) return '';
    const x = scaleX(index);
    const y = height - 16;
    return `<text class="wear-chart-label" x="${x.toFixed(1)}" y="${y}" text-anchor="middle">${esc(formatWearDate(label) || label)}</text>`;
  }).join('');
  const pointsSvg = (series) => (series.values || []).map((value, index) => {
    if (!Number.isFinite(value)) return '';
    const cx = scaleX(index).toFixed(1);
    const cy = scaleY(value).toFixed(1);
    return `<circle class="wear-chart-dot" cx="${cx}" cy="${cy}" r="4.4" fill="#fff" stroke="${series.color}"></circle>`;
  }).join('');
  const pathSvg = (series) => linePath(series).map(d => `<path class="wear-chart-series" stroke="${series.color}" d="${d}"></path>`).join('');
  const firstDate = axisLabels[0] ? formatWearDate(axisLabels[0]) : '';
  const lastDate = axisLabels[axisLabels.length - 1] ? formatWearDate(axisLabels[axisLabels.length - 1]) : '';
  const dateLabel = firstDate ? `${firstDate}${lastDate && lastDate !== firstDate ? ` — ${lastDate}` : ''}` : '';
  const title = [titlePrefix, wearChartMetricLabel(metricKey), dateLabel].filter(Boolean).join(' · ');
  const emptyText = axisLabels.length < 2 ? 'Показан один замер — для линии нужен хотя бы ещё один.' : '';
  return {
    svg: `
      <svg class="wear-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="${esc(title || 'График износа КП')}">
        <rect x="0" y="0" width="${width}" height="${height}" fill="white"></rect>
        <text class="wear-chart-title" x="${margin.left}" y="20">${esc(title || 'График износа КП')}</text>
        ${gridLines.join('')}
        <line class="wear-chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
        <line class="wear-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
        ${chartSeries.map(series => pathSvg(series)).join('')}
        ${chartSeries.map(series => pointsSvg(series)).join('')}
        ${xLabels}
      </svg>
    `,
    emptyText,
    firstDate,
    lastDate,
  };
}
function renderWearChartsGrid(){
  const grid = document.getElementById('wearChartsGrid');
  const empty = document.getElementById('wearChartsEmpty');
  if (!grid || !empty) return;
  const metricKey = wearChartSelectedMetric();
  const metricLabel = wearChartMetricLabel(metricKey);
  if (!wearChartPairs.length) {
    grid.innerHTML = '';
    empty.textContent = 'Нет данных для графиков.';
    return;
  }
  empty.textContent = '';
  grid.innerHTML = wearChartPairs.map(pair => {
    const pairValue = String(pair.wheel_pair || '').trim();
    const points = Array.isArray(pair.points) ? pair.points : [];
    const chart = wearChartBuildSvg(points, metricKey, `КП ${pairValue || '—'}`);
    const subtitle = chart.firstDate
      ? `${metricLabel} · ${chart.firstDate}${chart.lastDate && chart.lastDate !== chart.firstDate ? ` — ${chart.lastDate}` : ''}`
      : metricLabel;
    return `
      <article class="wear-chart-card">
        <div class="wear-chart-card-head">
          <div>
            <div class="wear-chart-card-title">КП ${esc(pairValue || '—')}</div>
            <div class="wear-chart-card-subtitle">${esc(subtitle)}</div>
          </div>
          <div class="wear-chart-card-count">${points.length ? `${points.length} зам.` : 'нет данных'}</div>
        </div>
        <div class="wear-chart-shell wear-chart-shell--card">
          ${chart.svg || ''}
          <div class="wear-chart-empty">${esc(chart.emptyText || '')}</div>
        </div>
      </article>
    `;
  }).join('');
}
function renderWearChartControls(){
  const modeSelect = document.getElementById('wearChartMode');
  const pairSelect = document.getElementById('wearChartPair');
  const metricSelect = document.getElementById('wearChartMetric');
  const pairLabel = pairSelect?.closest('label');
  if (modeSelect) {
    const previous = String(wearChartMode || modeSelect.value || 'pair').trim();
    modeSelect.value = previous === 'all' ? 'all' : 'pair';
    wearChartMode = modeSelect.value;
  }
  if (pairLabel) pairLabel.style.display = wearChartMode === 'all' ? 'none' : '';
  if (pairSelect) {
    const previous = String(pairSelect.value || wearChartPairChoice || '').trim();
    pairSelect.innerHTML = wearChartPairs.map(item => {
      const value = String(item.wheel_pair || '').trim();
      return `<option value="${esc(value)}">КП ${esc(value)}</option>`;
    }).join('');
    if (previous && [...pairSelect.options].some(option => option.value === previous)) {
      pairSelect.value = previous;
    } else if (pairSelect.options.length) {
      pairSelect.value = pairSelect.options[0].value;
    }
    wearChartPairChoice = String(pairSelect.value || previous || '').trim();
  }
  if (metricSelect) {
    const previous = String(metricSelect.value || wearChartMetricChoice || '').trim();
    metricSelect.innerHTML = wearChartMetrics.map(item => {
      const value = String(item.key || '').trim();
      return `<option value="${esc(value)}">${esc(item.label || value)}</option>`;
    }).join('');
    if (previous && [...metricSelect.options].some(option => option.value === previous)) {
      metricSelect.value = previous;
    } else if (metricSelect.options.length) {
      metricSelect.value = metricSelect.options[0].value;
    }
    wearChartMetricChoice = String(metricSelect.value || previous || '').trim();
  }
  const legend = document.querySelector('.wear-chart-legend');
  if (legend) {
    legend.innerHTML = wearChartMode === 'all'
      ? wearChartPairs.map((item, index) => {
          const value = String(item.wheel_pair || '').trim();
          const colors = ['#2f6fed','#e05a47','#2aa36b','#b26ce0','#f0a23a','#0f9a9a','#9b5cf4','#d84f7a','#4c647f','#7b8fa6','#1f7a3a','#9c4f00'];
          const color = colors[index % colors.length];
          return `<span class="wear-legend-item"><i class="wear-legend-line" style="color:${color}"></i>КП ${esc(value)}</span>`;
        }).join('')
      : `
        <span class="wear-legend-item"><i class="wear-legend-line wear-legend-left"></i>Левая сторона</span>
        <span class="wear-legend-item"><i class="wear-legend-line wear-legend-right"></i>Правая сторона</span>
      `;
  }
}
function renderWearChart(){
  const svg = document.getElementById('wearChartSvg');
  const empty = document.getElementById('wearChartEmpty');
  if (!svg || !empty) return;
  const metricKey = wearChartSelectedMetric();
  const metricLabel = wearChartMetricLabel(metricKey);
  const mode = wearChartModeValue();
  const width = 900;
  const height = 260;
  const margin = { left: 64, right: 18, top: 30, bottom: 42 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const colors = ['#2f6fed','#e05a47','#2aa36b','#b26ce0','#f0a23a','#0f9a9a','#9b5cf4','#d84f7a','#4c647f','#7b8fa6','#1f7a3a','#9c4f00'];
  let chartSeries = [];
  let axisLabels = [];
  if (mode === 'all') {
    const dateSet = new Set();
    wearChartPairs.forEach(pair => {
      (pair.points || []).forEach(point => {
        const date = String(point?.measurement_date || '').trim();
        if (date) dateSet.add(date);
      });
    });
    axisLabels = [...dateSet].sort();
    chartSeries = wearChartPairs.map((pair, index) => {
      const pointMap = new Map();
      (pair.points || []).forEach(point => {
        const date = String(point?.measurement_date || '').trim();
        if (!date) return;
        pointMap.set(date, {
          left: wearChartNumber(point?.metrics?.[metricKey]?.left),
          right: wearChartNumber(point?.metrics?.[metricKey]?.right),
        });
      });
      return {
        pair: String(pair.wheel_pair || '').trim(),
        color: colors[index % colors.length],
        values: axisLabels.map(date => {
          const current = pointMap.get(date) || {};
          return wearChartRepresentativeValue(metricKey, current.left, current.right);
        }),
      };
    });
  } else {
    const pairValue = wearChartSelectedPair();
    const pairData = wearChartPairs.find(item => String(item.wheel_pair || '').trim() === pairValue) || wearChartPairs[0] || null;
    const points = Array.isArray(pairData?.points) ? pairData.points : [];
    axisLabels = points.map(point => String(point?.measurement_date || '').trim()).filter(Boolean);
    chartSeries = [
      {
        pair: pairValue,
        color: '#2f6fed',
        values: points.map(point => wearChartNumber(point?.metrics?.[metricKey]?.left)),
        side: 'left',
      },
      {
        pair: pairValue,
        color: '#e05a47',
        values: points.map(point => wearChartNumber(point?.metrics?.[metricKey]?.right)),
        side: 'right',
      },
    ];
    if (!pairData || !axisLabels.length) {
      svg.innerHTML = '';
      empty.textContent = 'Для выбранной КП и показателя пока нет достаточных данных для графика.';
      return;
    }
  }
  const values = chartSeries.flatMap(series => (series.values || []).filter(value => Number.isFinite(value)));
  if (!axisLabels.length || !values.length) {
    svg.innerHTML = '';
    empty.textContent = mode === 'all'
      ? 'Для общего графика пока недостаточно данных.'
      : 'Для выбранной КП и показателя пока нет достаточных данных для графика.';
    return;
  }
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = Math.max(0.5, (max - min) * 0.12);
  min -= pad;
  max += pad;
  const scaleX = (index) => {
    if (axisLabels.length === 1) return margin.left + plotWidth / 2;
    return margin.left + (plotWidth * index) / (axisLabels.length - 1);
  };
  const scaleY = (value) => margin.top + ((max - value) * plotHeight) / (max - min);
  const linePath = (series) => {
    const segments = [];
    let current = [];
    (series.values || []).forEach((value, index) => {
      if (!Number.isFinite(value)) {
        if (current.length) {
          segments.push(current);
          current = [];
        }
        return;
      }
      current.push({ x: scaleX(index), y: scaleY(value) });
    });
    if (current.length) segments.push(current);
    return segments.map(segment => segment.map((pt, idx) => `${idx === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`).join(' '));
  };
  const gridLines = [];
  for (let i = 0; i <= 4; i += 1) {
    const y = margin.top + (plotHeight * i) / 4;
    const value = max - ((max - min) * i) / 4;
    gridLines.push(`<line class="wear-chart-grid" x1="${margin.left}" y1="${y.toFixed(1)}" x2="${width - margin.right}" y2="${y.toFixed(1)}"></line>`);
    gridLines.push(`<text class="wear-chart-label" x="${margin.left - 10}" y="${(y + 4).toFixed(1)}" text-anchor="end">${esc(wearNumber(value))}</text>`);
  }
  const xLabelStep = Math.max(1, Math.ceil(axisLabels.length / 6));
  const xLabels = axisLabels.map((label, index) => {
    if (axisLabels.length > 1 && index % xLabelStep !== 0 && index !== axisLabels.length - 1) return '';
    const x = scaleX(index);
    const y = height - 16;
    return `<text class="wear-chart-label" x="${x.toFixed(1)}" y="${y}" text-anchor="middle">${esc(formatWearDate(label) || label)}</text>`;
  }).join('');
  const pointsSvg = (series) => (series.values || []).map((value, index) => {
    if (!Number.isFinite(value)) return '';
    const cx = scaleX(index).toFixed(1);
    const cy = scaleY(value).toFixed(1);
    return `<circle class="wear-chart-dot" cx="${cx}" cy="${cy}" r="4.4" fill="#fff" stroke="${series.color}"></circle>`;
  }).join('');
  const pathSvg = (series) => linePath(series).map(d => `<path class="wear-chart-series" stroke="${series.color}" d="${d}"></path>`).join('');
  const firstDate = axisLabels[0] ? formatWearDate(axisLabels[0]) : '';
  const lastDate = axisLabels[axisLabels.length - 1] ? formatWearDate(axisLabels[axisLabels.length - 1]) : '';
  const modeLabel = mode === 'all' ? 'Все КП' : `КП ${esc(wearChartSelectedPair())}`;
  svg.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="white"></rect>
    <text class="wear-chart-title" x="${margin.left}" y="20">${esc(metricLabel)} · ${esc(modeLabel)} · ${esc(firstDate)}${lastDate && lastDate !== firstDate ? ` — ${esc(lastDate)}` : ''}</text>
    ${gridLines.join('')}
    <line class="wear-chart-axis" x1="${margin.left}" y1="${height - margin.bottom}" x2="${width - margin.right}" y2="${height - margin.bottom}"></line>
    <line class="wear-chart-axis" x1="${margin.left}" y1="${margin.top}" x2="${margin.left}" y2="${height - margin.bottom}"></line>
    ${chartSeries.map(series => pathSvg(series)).join('')}
    ${chartSeries.map(series => pointsSvg(series)).join('')}
    ${xLabels}
  `;
  if (mode === 'all') {
    empty.textContent = axisLabels.length < 2 ? 'Показан один замер — для линии нужен хотя бы ещё один.' : '';
  } else {
    empty.textContent = axisLabels.length < 2 ? 'Показан один замер — для линии нужен хотя бы ещё один.' : '';
  }
}
function refreshWearChart(){
  renderWearChartControls();
  if (document.getElementById('wearChartsGrid')) renderWearChartsGrid();
  if (document.getElementById('wearChartSvg')) renderWearChart();
  if (document.getElementById('wearBody')) renderWearAnalysisTable();
  applyWearPageView();
  writeWearPageState();
}
function openWearChartsPage(){
  const loco = String(document.getElementById('wearLocomotive')?.value || wearSelectedLoco || '').trim();
  const dateFrom = String(document.getElementById('wearDateFrom')?.value || wearDateFrom || '').trim();
  const dateTo = String(document.getElementById('wearDateTo')?.value || wearDateTo || '').trim();
  const mode = wearChartModeValue();
  wearSelectedLoco = loco;
  wearDateFrom = dateFrom;
  wearDateTo = dateTo;
  wearChartMode = mode;
  wearChartPairChoice = String(document.getElementById('wearChartPair')?.value || wearChartPairChoice || '').trim();
  wearChartMetricChoice = String(document.getElementById('wearChartMetric')?.value || wearChartMetricChoice || '').trim();
  writeWearPageState();
  const params = new URLSearchParams();
  if (loco) params.set('locomotive', loco);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (mode) params.set('mode', mode);
  window.location.href = `${API}/wear-charts${params.toString() ? `?${params.toString()}` : ''}`;
}
async function exportWearChartPng(){
  const svg = document.getElementById('wearChartSvg');
  if (!svg || !svg.innerHTML.trim()) return;
  const status = document.getElementById('wearStatus');
  try {
    const clone = svg.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const markup = new XMLSerializer().serializeToString(clone);
    const blob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    const viewBox = svg.getAttribute('viewBox') || '0 0 900 260';
    const parts = viewBox.split(/\s+/).map(Number);
    const width = Number.isFinite(parts[2]) ? parts[2] : 900;
    const height = Number.isFinite(parts[3]) ? parts[3] : 260;
    const scale = 2;
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        URL.revokeObjectURL(url);
        if (status) status.textContent = 'Не удалось создать PNG';
        return;
      }
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0, width, height);
      canvas.toBlob((pngBlob) => {
        URL.revokeObjectURL(url);
        if (!pngBlob) {
          if (status) status.textContent = 'Не удалось создать PNG';
          return;
        }
        const a = document.createElement('a');
        a.href = URL.createObjectURL(pngBlob);
        a.download = `wear-analysis-${wearSelectedLoco || 'chart'}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        if (status) status.textContent = 'График сохранён в PNG';
      }, 'image/png');
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      if (status) status.textContent = 'Не удалось создать PNG';
    };
    img.src = url;
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось создать PNG';
  }
}
async function loadWearAnalysis(nextLoco = ''){
  const status = document.getElementById('wearStatus');
  const select = document.getElementById('wearLocomotive');
  const dateFromInput = document.getElementById('wearDateFrom');
  const dateToInput = document.getElementById('wearDateTo');
  const refreshBtn = document.getElementById('wearRefreshBtn');
  const loco = String(nextLoco || select?.value || wearSelectedLoco || state?.locomotive || kpSelectedLoco || '').trim();
  const dateFrom = String(dateFromInput?.value || wearDateFrom || '').trim();
  const dateTo = String(dateToInput?.value || wearDateTo || '').trim();
  if (select && loco) select.value = loco;
  if (dateFromInput) dateFromInput.value = dateFrom;
  if (dateToInput) dateToInput.value = dateTo;
  wearSelectedLoco = loco;
  wearDateFrom = dateFrom;
  wearDateTo = dateTo;
  if (status) status.textContent = 'Загрузка анализа...';
  if (refreshBtn) refreshBtn.disabled = true;
  wearLoading = true;
  try {
    const params = new URLSearchParams();
    if (loco) params.set('locomotive', loco);
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const res = await fetch(`${API}/api/wear-analysis?${params.toString()}`, { cache: 'no-store' });
    if (!res.ok) {
      wearRows = [];
      renderWearAnalysisTable();
      if (status) status.textContent = 'Не удалось загрузить анализ';
      return;
    }
    const payload = await res.json();
    wearSelectedLoco = payload.locomotive || loco;
    wearDateFrom = payload.date_from || dateFrom;
    wearDateTo = payload.date_to || dateTo;
    wearRows = payload.rows || [];
    wearChartPairs = Array.isArray(payload.chart?.pairs) ? payload.chart.pairs : [];
    wearChartMetrics = Array.isArray(payload.chart?.metrics) ? payload.chart.metrics : [];
    renderWearLocomotiveOptions();
    refreshWearChart();
    renderWearAnalysisTable();
    writeWearPageState();
    if (status) {
      const countText = payload.series ? `${payload.series} ${payload.locomotive}` : payload.locomotive;
      const periodText = (wearDateFrom || wearDateTo) ? ` · период ${wearDateFrom || '...'} — ${wearDateTo || '...'}` : '';
      status.textContent = payload.rows?.length ? `Загружен анализ для ${countText}${periodText}` : 'Нет данных для анализа';
    }
  } catch (error) {
    wearRows = [];
    wearChartPairs = [];
    wearChartMetrics = [];
    renderWearAnalysisTable();
    refreshWearChart();
    if (status) status.textContent = error.message || 'Не удалось загрузить анализ';
  } finally {
    wearLoading = false;
    if (refreshBtn) refreshBtn.disabled = false;
  }
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
  return row >= 0 && row < kpRows.length && col >= 0 && col <= 3 && !kpAllMode;
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
    lines.push(rowValues.join('\t'));
  }
  await writeClipboardText(lines.join('\n'));
  renderKpStatus('Скопировано');
}
async function pasteKpClipboard(row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const text = await readClipboardText();
  if (!text) return;
  await pasteKpMatrix(text, row, col);
}
function parseKpClipboardMatrix(text){
  const lines = String(text ?? '').replace(/\r/g, '').split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines.map(line => line.split('\t'));
}
async function pasteKpMatrix(text, row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return false;
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : { row, col };
  const rows = parseKpClipboardMatrix(text);
  if (!rows.length) return false;
  let touched = false;
  for (let r = 0; r < rows.length; r += 1) {
    for (let c = 0; c < rows[r].length; c += 1) {
      const targetRow = start.row + r;
      const targetCol = start.col + c;
      if (!kpCellInBounds(targetRow, targetCol)) continue;
      touched = setKpCellValue(targetRow, targetCol, rows[r][c]) || touched;
    }
  }
  if (!touched) return false;
  focusKpCell(start.row, start.col);
  await saveKpDataChanges();
  return true;
}
async function handleKpCellPaste(event, row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const text = event.clipboardData?.getData('text/plain') || await readClipboardText();
  if (!text) return;
  event.preventDefault();
  await pasteKpMatrix(text, row, col);
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
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    clearKpSelectedCells(row, col);
    return;
  }
  if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) {
    event.preventDefault();
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 0) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 3) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < kpRows.length - 1) nextRow = row + 1;
    focusKpCell(nextRow, nextCol, event.shiftKey);
  }
}
function collectKpRowsFromView(){
  return kpRows.map((row, rowIndex) => {
    if (kpAllMode) return row.values || [];
    const values = ['', '', '', ''];
    values[0] = kpCellElement(rowIndex, 0)?.value ?? row.values?.[0] ?? `${rowIndex + 1}`;
    values[1] = kpCellElement(rowIndex, 1)?.value ?? row.values?.[1] ?? '';
    values[2] = kpCellElement(rowIndex, 2)?.value ?? row.values?.[2] ?? '';
    values[3] = kpCellElement(rowIndex, 3)?.value ?? row.values?.[3] ?? '';
    return values.map(value => String(value ?? '').trim());
  });
}
async function saveKpDataChanges(){
  if (!CAN_EDIT || kpAllMode || kpLoading || kpSelectedVersion) return false;
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
    kpVersions = payload.versions || [];
    kpSelectedVersion = payload.selected_version || null;
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
function applyKpPayload(payload, fallbackLoco){
  kpSelectedLoco = payload.selected_locomotive || fallbackLoco || kpSelectedLoco;
  kpAllMode = !!payload.all_mode;
  kpSelectedStatus = payload.status || null;
  kpRows = payload.rows || [];
  kpVersions = payload.versions || [];
  kpSelectedVersion = payload.selected_version || null;
  renderKpLocomotiveOptions();
  renderKpTable();
}
async function loadKpData(nextValue, versionId = null){
  const select = document.getElementById('kpLocomotive');
  const value = String(nextValue ?? select?.value ?? kpSelectedLoco ?? state?.locomotive ?? '').trim();
  if (select && value && select.value !== value) {
    select.value = value;
  }
  kpSelectedLoco = value || (state?.locomotive || '');
  kpSelectedVersion = versionId ? { id: Number(versionId) } : null;
  clearKpSelection();
  kpLoading = true;
  renderKpStatus('Загрузка КП данных...');
  try {
    const params = new URLSearchParams({ locomotive: kpSelectedLoco });
    if (versionId) params.set('version_id', String(versionId));
    const res = await fetch(`${API}/api/kp-data?${params.toString()}`, { cache: 'no-store' });
    if (!res.ok) {
      kpRows = [];
      kpAllMode = false;
      renderKpTable();
      renderKpStatus('Не удалось загрузить КП данные');
      return;
    }
    const payload = await res.json();
    applyKpPayload(payload, kpSelectedLoco);
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
        const cls = summaryClass(index, value);
        return `<td class="summary-merged archive-sticky-col${isLast ? ' section-last' : ''} ${cls}" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index >= 10) {
      const cls = index <= 17 ? measurementClass(index - 10, value) : '';
      return `
      <td class="measure-cell archive-raw ${cls}" data-col="${index}"><input
              value="${esc(fmt(value))}"
              data-row="${rowIndex}"
              data-col="${index}"
              data-original="${esc(value)}"
              ${CAN_EDIT ? '' : 'readonly'}
              onmousedown="return handleArchiveCellMouseDown(event, ${rowIndex}, ${index})"
              onmouseenter="handleArchiveCellMouseEnter(event, ${rowIndex}, ${index})"
              onfocus="handleArchiveCellFocus(${rowIndex}, ${index})"
              onchange="handleArchiveCellChange(${rowIndex}, ${index}, this.value, this)"
              onkeydown="handleArchiveKeydown(event, ${rowIndex}, ${index})"
              oncopy="handleArchiveCellCopy(event)"
              onpaste="handleArchiveCellPaste(event, ${rowIndex}, ${index})"
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
            onmouseenter="handleCellMouseEnter(event, ${r}, ${c})"
            onfocus="handleCellFocus(${r}, ${c})"
            oninput="handleCellInput(${r}, ${c}, this.value, this)"
            onkeydown="handleKeydown(event, ${r}, ${c})"
            oncopy="handleCellCopy(event)"
            onpaste="handleCellPaste(event, ${r}, ${c})"
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
  selectionDragging = true;
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleCellMouseEnter(event, row, col){
  if (!CAN_EDIT || !selectionDragging || !(event.buttons & 1)) return;
  selectCell(row, col, true);
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
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
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
  renderWearLocomotiveOptions();
  renderWearAnalysisTable();
  renderRepairOptions();
  renderMeta();
  renderTable();
  updateArchiveSortButton();
  await loadArchive().catch(error => {
    console.error(error);
  });
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
    renderMeta();
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
  const known = isKnownLocomotive(next);
  if (!known) {
    document.getElementById('locomotive').value = current;
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

document.getElementById('locomotive')?.addEventListener('change', onLocomotiveCommit);
document.addEventListener('mouseup', () => {
  selectionDragging = false;
  archiveSelectionDragging = false;
});
document.getElementById('normsModal')?.addEventListener('mousedown', event => {
  if (event.target.id === 'normsModal') closeNormsDialog();
});
document.getElementById('archiveExportModal')?.addEventListener('mousedown', event => {
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
document.getElementById('measurementDate')?.addEventListener('change', onDateChange);
document.getElementById('repairType')?.addEventListener('change', onRepairChange);
document.getElementById('kpLocomotive')?.addEventListener('change', e => loadKpData(e.target.value));
document.getElementById('kpSearch')?.addEventListener('input', applyKpSearchFilter);
document.getElementById('wearLocomotive')?.addEventListener('change', e => loadWearAnalysis(e.target.value));
document.getElementById('wearDateFrom')?.addEventListener('change', () => loadWearAnalysis());
document.getElementById('wearDateTo')?.addEventListener('change', () => loadWearAnalysis());
document.getElementById('wearChartMode')?.addEventListener('change', () => {
  wearChartMode = wearChartModeValue();
  writeWearPageState();
  refreshWearChart();
});
document.getElementById('wearChartPair')?.addEventListener('change', e => {
  wearChartPairChoice = String(e.target?.value || '').trim();
  writeWearPageState();
  renderWearChart();
});
document.getElementById('wearChartMetric')?.addEventListener('change', e => {
  wearChartMetricChoice = String(e.target?.value || '').trim();
  writeWearPageState();
  renderWearChart();
});
document.getElementById('archiveLocomotive')?.addEventListener('change', loadArchive);
document.getElementById('archiveSearch')?.addEventListener('input', loadArchive);
document.getElementById('archiveExcelFile')?.addEventListener('change', event => {
  const file = event.target.files?.[0];
  if (file) importArchiveExcelFile(file);
});
const saveBtn = document.getElementById('saveBtn');
if (saveBtn) saveBtn.style.display = CAN_EDIT ? '' : 'none';
if (window.WEAR_DEFAULT_MODE) {
  wearChartMode = String(window.WEAR_DEFAULT_MODE).trim() === 'all' ? 'all' : 'pair';
}
if (window.WEAR_DEFAULT_LOCOMOTIVE) {
  wearSelectedLoco = String(window.WEAR_DEFAULT_LOCOMOTIVE).trim();
}
{
  const savedWearState = readWearPageState();
  if (savedWearState) {
    if (!wearSelectedLoco && savedWearState.locomotive) wearSelectedLoco = String(savedWearState.locomotive).trim();
    if (!wearDateFrom && savedWearState.dateFrom) wearDateFrom = String(savedWearState.dateFrom).trim();
    if (!wearDateTo && savedWearState.dateTo) wearDateTo = String(savedWearState.dateTo).trim();
    if (savedWearState.mode) wearChartMode = String(savedWearState.mode).trim() === 'all' ? 'all' : wearChartMode;
    if (savedWearState.pair) wearChartPairChoice = String(savedWearState.pair).trim();
    if (savedWearState.metric) wearChartMetricChoice = String(savedWearState.metric).trim();
    if (savedWearState.view) wearPageView = String(savedWearState.view).trim() === 'table' ? 'table' : 'charts';
  }
}
function loadKpVersion(value){
  const versionId = String(value || '').trim();
  loadKpData(kpSelectedLoco, versionId || null);
}
async function createKpVersion(){
  if (!CAN_EDIT || kpAllMode || kpLoading || kpSelectedVersion) return;
  const dateInput = document.getElementById('kpValidTo');
  const validTo = String(dateInput?.value || '').trim();
  if (!validTo) {
    renderKpStatus('Укажите дату, до которой действовали старые данные');
    dateInput?.focus();
    return;
  }
  if (!confirm(`Сохранить текущие КП данные в историю до ${formatWearDate(validTo)} и начать ввод новых?`)) return;
  kpLoading = true;
  renderKpStatus('Сохранение старых КП данных...');
  try {
    const res = await fetch(`${API}/api/kp-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ action: 'new_version', locomotive: kpSelectedLoco, valid_to: validTo }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.error) {
      renderKpStatus(payload.error || 'Не удалось создать новую версию');
      return;
    }
    applyKpPayload(payload, kpSelectedLoco);
    renderKpStatus('Старые данные сохранены. Введите новые диаметры.');
  } finally {
    kpLoading = false;
  }
}
async function saveKpVersionDate(){
  if (!CAN_EDIT || !kpSelectedVersion || kpLoading) return;
  const validTo = String(document.getElementById('kpValidTo')?.value || '').trim();
  if (!validTo) {
    renderKpStatus('Укажите дату окончания действия версии');
    return;
  }
  kpLoading = true;
  renderKpStatus('Сохранение даты...');
  try {
    const res = await fetch(`${API}/api/kp-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        action: 'update_version',
        locomotive: kpSelectedLoco,
        version_id: kpSelectedVersion.id,
        valid_to: validTo,
      }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.error) {
      renderKpStatus(payload.error || 'Не удалось сохранить дату');
      return;
    }
    applyKpPayload(payload, kpSelectedLoco);
    renderKpStatus('Дата действия сохранена');
  } finally {
    kpLoading = false;
  }
}
applyWearPageView();
if (document.getElementById('kpLocomotive') || document.getElementById('wearLocomotive') || document.getElementById('archiveLocomotive')) {
  updateHistoryButtons();
}
if (document.getElementById('wearLocomotive')) {
  renderWearLocomotiveOptions();
}
if (document.getElementById('inputTable')) {
  initialLoadPromise = loadState().catch(error => {
    console.error(error);
    setStatus(error?.message || 'Не удалось загрузить данные');
    return null;
  });
  if (!CAN_EDIT && document.getElementById('tabKp')) switchTab('kp');
}
if (document.getElementById('wearChartSvg') || document.getElementById('wearChartsGrid')) {
  loadWearAnalysis().catch(() => undefined);
}

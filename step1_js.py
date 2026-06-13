import re

js_file = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(js_file, 'r', encoding='utf-8') as f:
    js_text = f.read()

# 1. Update saveState payload
payload_regex = re.compile(r'(const payload = \{\s*year: appState\.year,\s*month: appState\.month,\s*employees: cleanEmployees,\s*timesheet: objTimesheet,\s*vacations: objVac,\s*ts_norms_data: arrNorms)(\s*\};)')

if 'month_hint' not in js_text[js_text.find('const payload = {'):js_text.find('};', js_text.find('const payload = {'))]:
    js_text = payload_regex.sub(r'\1,\n      month_hint: appState.month_hint || ""\2', js_text)

# 2. Update renderTable to populate monthHint
render_table_regex = re.compile(r'(function renderTable\(\) \{.*?\n)(  const year = parseInt\(appState\.year\);)', re.DOTALL)

render_hint_logic = r'''\1  const mh = document.getElementById("monthHint");
  if (mh) {
    mh.value = appState.month_hint || "";
    if (!CAN_EDIT) mh.readOnly = true;
  }
\2'''

if 'monthHint' not in js_text[js_text.find('function renderTable() {'):js_text.find('const thead = document.getElementById("tabelHeader");')]:
    js_text = render_table_regex.sub(render_hint_logic, js_text)

with open(js_file, 'w', encoding='utf-8') as f:
    f.write(js_text)

# Bump version in app.py
app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    app_text = f.read()

app_text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.31"', app_text)
with open(app_py, 'w', encoding='utf-8') as f:
    f.write(app_text)

print("Updated script.js for monthHint")

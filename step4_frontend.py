import re

# 1. Update HTML
html_file = r'g:\Мой диск\Codex\rtps\web_tabel\templates\index.html'
with open(html_file, 'r', encoding='utf-8') as f:
    html_text = f.read()

# Add CSS for .excluded
css_style = '<style>\n    .excluded { color: #a0a0a0; background-color: #e8e8e8 !important; }\n    .excluded input { opacity: 0.5; }\n  </style>'
if '.excluded {' not in html_text:
    html_text = html_text.replace('</head>', css_style + '\n</head>')

# Update table headers
old_header = r'<th>Молоко<br>Выдача</th><th>Примечание</th>'
new_header = r'<th>Молоко<br>Выдача</th><th>Исключить</th><th>Примечание</th>'

html_text = html_text.replace(old_header, new_header)

with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_text)


# 2. Update JS
js_file = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(js_file, 'r', encoding='utf-8') as f:
    js_text = f.read()

# In renderTable (Employees tab):
old_js_emp = r"""eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk_issue', this)" ${emp.milk_issue ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'milk_note', this)">${escapeHtml(emp.milk_note)}</div></td>`;"""

new_js_emp = r"""eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'milk_issue', this)" ${emp.milk_issue ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><input type="checkbox" onchange="empEdited(${r}, 'is_excluded', this)" ${emp.is_excluded ? 'checked' : ''} ${CAN_EDIT ? '' : 'disabled'}></td>`;
    eHTML += `<td><div class="cell" style="text-align: left;" ${CAN_EDIT ? 'contenteditable="true"' : ''} oninput="empEdited(${r}, 'milk_note', this)">${escapeHtml(emp.milk_note)}</div></td>`;"""

js_text = js_text.replace(old_js_emp, new_js_emp)

# In empEdited, add is_excluded
old_empEdited = "if (field === 'milk' || field === 'milk_issue') {"
new_empEdited = "if (field === 'milk' || field === 'milk_issue' || field === 'is_excluded') {"
js_text = js_text.replace(old_empEdited, new_empEdited)

# In renderTable (Tabel Tab), add class 'excluded' if emp.is_excluded
old_tabel_row = r"""bHTML += `<tr draggable="true" ondragstart="rowDragStart(event, ${rIndex})" ondragover="rowDragOver(event, ${rIndex})" ondrop="rowDrop(event, ${rIndex})">`;"""
new_tabel_row = r"""const trClass = emp.is_excluded ? "excluded" : "";
    bHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${rIndex})" ondragover="rowDragOver(event, ${rIndex})" ondrop="rowDrop(event, ${rIndex})">`;"""
js_text = js_text.replace(old_tabel_row, new_tabel_row)

# In renderTable (Employees Tab), add class 'excluded'
old_emp_row = r"""eHTML += `<tr draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;"""
new_emp_row = r"""const trClass = emp.is_excluded ? "excluded" : "";
    eHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;"""
js_text = js_text.replace(old_emp_row, new_emp_row)

# In renderTable (Vacations Tab), add class 'excluded'
old_vac_row = r"""vHTML += `<tr draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;"""
new_vac_row = r"""const trClass = emp.is_excluded ? "excluded" : "";
    vHTML += `<tr class="${trClass}" draggable="true" ondragstart="rowDragStart(event, ${r})" ondragover="rowDragOver(event, ${r})" ondrop="rowDrop(event, ${r})">`;"""
js_text = js_text.replace(old_vac_row, new_vac_row)

with open(js_file, 'w', encoding='utf-8') as f:
    f.write(js_text)

print("Updated HTML and JS for is_excluded")

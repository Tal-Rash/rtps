import sys

path = r'g:\Мой диск\Codex\rtps\web_grafik_ppr\static\script.js'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(1760, 1775):
    if lines[i].strip().startswith('const dayFillStyle'):
        new_lines = [
            "      const inputStyle = row.excluded ? 'color:#9aa5b1 !important;' : '';\n",
            "      rowHtml.push(`<td class=\"col-day ${cls}${isKpHighlight ? ' kp-recheck-cell' : ''}\">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${colIndex}`, row.cells[colIndex] || '', `cell small center ${cls} day-cell${isKpHighlight ? ' kp-recheck-input' : ''}`, ui.monthIndex, type, rIdx, colIndex, inputStyle) }</td>`);\n"
        ]
        # Remove the previous 11 lines
        lines[i:i+12] = new_lines
        break

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

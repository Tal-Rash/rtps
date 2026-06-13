import re

filepath = r'g:\Мой диск\Codex\rtps\web_tabel\static\style.css'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# Remove the old cell day-cell coloring
text = re.sub(r'td\.transfer-col \.cell\.day-cell \{.*?\n\}', '', text, flags=re.DOTALL)
text = re.sub(r'td\.holiday-col \.cell\.day-cell \{.*?\n\}', '', text, flags=re.DOTALL)
text = re.sub(r'td\.transfer-col \.cell\.day-cell::selection,.*?\}', '', text, flags=re.DOTALL)
text = re.sub(r'td\.holiday-col \.cell\.day-cell::selection \{.*?\}', '', text, flags=re.DOTALL)

# Also remove the transfer/holiday table th/td background if they interfere.
# Wait, th and td backgrounds are fine to leave since we assign bg- classes to td now.

# Append the new ones
new_styles = """
td.bg-weekend .cell.day-cell { background: #CCFFCC !important; color: #102033 !important; }
td.bg-holiday .cell.day-cell { background: #FFCCCC !important; color: #102033 !important; }
td.bg-vacation .cell.day-cell { background: #FFFF99 !important; color: #102033 !important; }
td.bg-trip .cell.day-cell { background: #E1BEE7 !important; color: #102033 !important; }
td.bg-ill .cell.day-cell { background: #FF9999 !important; color: #102033 !important; }
td.bg-milk .cell.day-cell { background: #B3E5FC !important; color: #102033 !important; }

td.bg-weekend .cell.day-cell::selection,
td.bg-holiday .cell.day-cell::selection,
td.bg-vacation .cell.day-cell::selection,
td.bg-trip .cell.day-cell::selection,
td.bg-ill .cell.day-cell::selection,
td.bg-milk .cell.day-cell::selection {
  background: rgba(16, 32, 51, .15);
}
"""

text += new_styles

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)

# Bump version in app.py
app_filepath = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_filepath, 'r', encoding='utf-8') as f:
    app_text = f.read()
    
app_text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.25"', app_text)

with open(app_filepath, 'w', encoding='utf-8') as f:
    f.write(app_text)
    
print("Updated CSS and version")

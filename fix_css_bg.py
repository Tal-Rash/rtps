import re

filepath = r'g:\Мой диск\Codex\rtps\web_tabel\static\style.css'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacement = """
td.bg-weekend, td.bg-weekend .cell.day-cell { background: #CCFFCC !important; color: #102033 !important; }
td.bg-holiday, td.bg-holiday .cell.day-cell { background: #FFCCCC !important; color: #102033 !important; }
td.bg-vacation, td.bg-vacation .cell.day-cell { background: #FFFF99 !important; color: #102033 !important; }
td.bg-trip, td.bg-trip .cell.day-cell { background: #E1BEE7 !important; color: #102033 !important; }
td.bg-ill, td.bg-ill .cell.day-cell { background: #FF9999 !important; color: #102033 !important; }
td.bg-milk, td.bg-milk .cell.day-cell { background: #B3E5FC !important; color: #102033 !important; }

th.bg-weekend { background: #CCFFCC !important; }
th.bg-holiday { background: #FFCCCC !important; }
"""

orig_chunk = """td.bg-weekend .cell.day-cell { background: #CCFFCC !important; color: #102033 !important; }
td.bg-holiday .cell.day-cell { background: #FFCCCC !important; color: #102033 !important; }
td.bg-vacation .cell.day-cell { background: #FFFF99 !important; color: #102033 !important; }
td.bg-trip .cell.day-cell { background: #E1BEE7 !important; color: #102033 !important; }
td.bg-ill .cell.day-cell { background: #FF9999 !important; color: #102033 !important; }
td.bg-milk .cell.day-cell { background: #B3E5FC !important; color: #102033 !important; }"""

if orig_chunk in text:
    text = text.replace(orig_chunk, replacement.strip())
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Fixed CSS backgrounds!")
else:
    print("Could not find the exact chunk in style.css")
    
# Bump version in app.py
app_filepath = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_filepath, 'r', encoding='utf-8') as f:
    app_text = f.read()
    
app_text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.26"', app_text)

with open(app_filepath, 'w', encoding='utf-8') as f:
    f.write(app_text)

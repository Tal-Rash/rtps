import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Define COMMON_DB_FILE
if 'COMMON_DB_FILE = DB_FILE' not in text:
    text = text.replace('DB_LOCK = Lock()', 'DB_LOCK = Lock()\nCOMMON_DB_FILE = DB_FILE')
    
# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.40"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed COMMON_DB_FILE")

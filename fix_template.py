import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix template filename
text = text.replace('"Молоко_компенсация_шаблон.xlsx"', '"Молоко_комп_шаблон.xlsx"')

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.38"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed template filename")

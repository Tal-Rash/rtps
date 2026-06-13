import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace [ПРИМЕЧАНИЕ] with [МОЛОКО_ПРИМ] in two places in app.py
text = text.replace('"[ПРИМЕЧАНИЕ]"', '"[МОЛОКО_ПРИМ]"')

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.42"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed [МОЛОКО_ПРИМ] placeholder")

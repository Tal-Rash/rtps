import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix the sqlite3.Row AttributeError
text = text.replace('r.get("is_excluded", 0)', 'dict(r).get("is_excluded", 0)')
text = text.replace('emp.get("is_excluded", 0)', 'emp.get("is_excluded", 0)') # emp is a normal dict, so it's fine

# Let's bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.35"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed sqlite3.Row attribute error")

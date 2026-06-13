import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix the empty if block
text = text.replace('    if not db_path.exists():\n    \n    return {', '    if not db_path.exists():\n        pass\n    \n    return {')

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed indentation error")

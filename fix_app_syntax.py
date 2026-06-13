import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Clean up all injected cur.execute("CREATE TABLE IF NOT EXISTS month_hints...")
# I will use regex to remove them, being careful about indentation
text = re.sub(r'^[ \t]*cur\.execute\("CREATE TABLE IF NOT EXISTS month_hints \(y INT, m TEXT, hint TEXT, PRIMARY KEY\(y,m\)\)"\)\n?', '', text, flags=re.MULTILINE)

# Now, properly insert it ONLY inside init_db()
init_db_idx = text.find('def init_db():')
if init_db_idx != -1:
    # Find the FIRST cur = conn.cursor() after init_db()
    cursor_str = '        cur = conn.cursor()'
    insert_idx = text.find(cursor_str, init_db_idx)
    if insert_idx != -1:
        insert_pos = insert_idx + len(cursor_str)
        injection = '\n        cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")'
        text = text[:insert_pos] + injection + text[insert_pos:]
        print("Successfully injected into init_db")

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.45"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Cleaned up and fixed app.py")

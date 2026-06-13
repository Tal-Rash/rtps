import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

migration_code = """
        # Add is_excluded column if not exists
        cur.execute("PRAGMA table_info('employees')")
        emp_cols = [c["name"] for c in cur.fetchall()]
        if "is_excluded" not in emp_cols:
            cur.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")
            conn.commit()
"""

if 'ALTER TABLE employees ADD COLUMN is_excluded' not in text:
    # Find init_db
    init_db_idx = text.find('def init_db():')
    if init_db_idx != -1:
        # Find where to insert inside init_db. Right after cur = conn.cursor()
        cursor_str = '        cur = conn.cursor()'
        insert_idx = text.find(cursor_str, init_db_idx)
        if insert_idx != -1:
            insert_pos = insert_idx + len(cursor_str)
            text = text[:insert_pos] + migration_code + text[insert_pos:]
            
            # Bump version
            text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.41"', text)
            
            with open(app_py, 'w', encoding='utf-8') as f:
                f.write(text)
            print("Migration code added!")
        else:
            print("Cursor str not found")
    else:
        print("init_db not found")
else:
    print("Migration code already present")

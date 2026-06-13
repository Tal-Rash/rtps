import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Modify init_db to also migrate COMMON_DB_FILE
old_migration = '''          cur.execute("PRAGMA table_info('employees')")
          emp_cols = [c["name"] for c in cur.fetchall()]
          if "is_excluded" not in emp_cols:
              cur.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")
              conn.commit()'''

new_migration = '''          cur.execute("PRAGMA table_info('employees')")
          emp_cols = [c["name"] for c in cur.fetchall()]
          if "is_excluded" not in emp_cols:
              cur.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")
              conn.commit()

    if COMMON_DB_FILE.exists():
        with sqlite3.connect(COMMON_DB_FILE) as conn2:
            conn2.row_factory = sqlite3.Row
            cur2 = conn2.cursor()
            cur2.execute("PRAGMA table_info('employees')")
            emp_cols2 = [c["name"] for c in cur2.fetchall()]
            if "is_excluded" not in emp_cols2:
                cur2.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")
                conn2.commit()'''

if 'COMMON_DB_FILE.exists()' not in text:
    text = text.replace(old_migration, new_migration)
    # Bump version
    text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.37"', text)
    with open(app_py, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Fixed migration for COMMON_DB_FILE")
else:
    print("Already migrated")

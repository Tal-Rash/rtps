import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Add is_excluded column migration
migration = '''          if "tab_num" not in cols and "r" in cols:'''

new_migration = '''          # Add is_excluded column if not exists
          cur.execute("PRAGMA table_info('employees')")
          emp_cols = [c["name"] for c in cur.fetchall()]
          if "is_excluded" not in emp_cols:
              cur.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")
              conn.commit()
              
          if "tab_num" not in cols and "r" in cols:'''

if "ADD COLUMN is_excluded" not in text:
    text = text.replace(migration, new_migration)

# Add to load_state
load_state_old = '"milk_note": text(r["milk_note"])'
load_state_new = '"milk_note": text(r["milk_note"]),\n                    "is_excluded": int(r.get("is_excluded", 0) or 0)'

if '"is_excluded"' not in text[text.find('def load_state'):]:
    # Update SQL SELECT in load_state
    text = text.replace(
        '"SELECT pos, name, tab_num, milk, milk_issue, full_name, milk_note FROM employees WHERE y=? ORDER BY rowid"',
        '"SELECT pos, name, tab_num, milk, milk_issue, full_name, milk_note, is_excluded FROM employees WHERE y=? ORDER BY rowid"'
    )
    text = text.replace(load_state_old, load_state_new)

# Add to api_save_state
save_state_old = 'emp.get("milk_note", "")'
save_state_new = 'emp.get("milk_note", ""), emp.get("is_excluded", 0)'

if 'emp.get("is_excluded", 0)' not in text[text.find('def api_save_state'):]:
    text = text.replace(
        '"INSERT INTO employees (y, pos, name, tab_num, milk, milk_issue, full_name, milk_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",',
        '"INSERT INTO employees (y, pos, name, tab_num, milk, milk_issue, full_name, milk_note, is_excluded) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",'
    )
    text = text.replace(
        '(year, emp.get("pos", ""), emp.get("name", ""), emp.get("tab_num", ""), emp.get("milk", 0), emp.get("milk_issue", 0), emp.get("full_name", ""), emp.get("milk_note", ""))',
        '(year, emp.get("pos", ""), emp.get("name", ""), emp.get("tab_num", ""), emp.get("milk", 0), emp.get("milk_issue", 0), emp.get("full_name", ""), emp.get("milk_note", ""), emp.get("is_excluded", 0))'
    )

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.33"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Added is_excluded backend support")

import sqlite3, pathlib, sys

db_path = pathlib.Path(r'g:/Мой диск/Codex/rtps/base/common_database.db')
if not db_path.exists():
    print('DB not found', db_path)
    sys.exit(1)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
# Remove any existing admin rows with numeric id
cur.execute("DELETE FROM users WHERE role='admin'")
# Insert correct admin row with id='admin' and allowed_modules for both modules
cur.execute("INSERT INTO users (id, role, allowed_modules) VALUES (?, ?, ?)",
            ('admin', 'admin', 'zamer_kp:admin,spravochnik:admin'))
conn.commit()
print('Admin row fixed')
cur.execute('SELECT id, role, allowed_modules FROM users WHERE id="admin"')
print('Row:', cur.fetchone())
conn.close()

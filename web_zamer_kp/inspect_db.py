import sqlite3, pathlib, json, sys

db_path = pathlib.Path(r'g:/Мой диск/Codex/rtps/base/common_database.db')
if not db_path.exists():
    print('DB not found', db_path)
    sys.exit(1)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
# List tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
print('tables:', cur.fetchall())
# Users schema
cur.execute('PRAGMA table_info(users)')
print('users schema:', cur.fetchall())
# Users rows
cur.execute('SELECT * FROM users')
rows = cur.fetchall()
print('users rows count:', len(rows))
for row in rows:
    print(row)

import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT m, c, v FROM timesheet WHERE tab_num='4604571' AND y=2026 AND v='О' ORDER BY cast(m as integer), c").fetchall()
print("Count:", len(rows))
for r in rows:
    print(r)

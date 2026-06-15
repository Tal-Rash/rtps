import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT m, c, v FROM timesheet WHERE tab_num='4604571' AND y=2026 AND v='О' AND c IN (1, 9, 12, 8, 23, 4)").fetchall()
for r in rows:
    print(r[0].encode('utf-8').hex(), r[1])

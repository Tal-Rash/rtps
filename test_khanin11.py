import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT m, c FROM timesheet WHERE tab_num='4604571' AND y=2026 AND v='О'").fetchall()
from collections import defaultdict
months = defaultdict(list)
for r in rows:
    months[r[0]].append(r[1])
for m, days in months.items():
    print(m.encode('utf-8').hex(), len(days))

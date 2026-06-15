import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT e.name, t.m, t.c, t.v FROM timesheet t JOIN employees e ON t.tab_num = e.tab_num AND t.y=e.y WHERE e.name LIKE '%Ханин%' AND t.y=2026 AND t.v='О' ORDER BY cast(t.m as integer), t.c").fetchall()
print("Count:", len(rows))
for r in rows:
    print(r)

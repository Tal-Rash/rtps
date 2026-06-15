import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT DISTINCT m, c FROM timesheet WHERE tab_num='4604571' AND y=2026 AND v='О'").fetchall()
print("Unique count:", len(rows))

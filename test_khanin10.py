import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT m, c FROM timesheet WHERE tab_num='4604571' AND y=2026 AND v='О'").fetchall()
may = [r[1] for r in rows if r[0].encode('utf-8').hex() == 'd09cd0b0d0b9']
nov = [r[1] for r in rows if r[0].encode('utf-8').hex() == 'd09dd0bed18fd0b1d180d18c']
print("May:", sorted(may))
print("Nov:", sorted(nov))

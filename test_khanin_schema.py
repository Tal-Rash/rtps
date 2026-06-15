import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
print(c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='timesheet'").fetchone()[0])

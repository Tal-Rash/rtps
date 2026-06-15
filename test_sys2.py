import sqlite3
import json
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='system_dates'").fetchall()
print("system_dates exists:", len(rows) > 0)

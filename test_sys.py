import sqlite3
import json
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT c, v FROM ts_norms_data WHERE y=2026 AND c IN (6, 7)").fetchall()
print(rows)

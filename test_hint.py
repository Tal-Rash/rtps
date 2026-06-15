import sqlite3
import json
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
row = c.execute("SELECT v FROM ts_settings WHERE k='month_hint'").fetchone()
with open("hint.txt", "w", encoding="utf-8") as f:
    f.write(row[0] if row else "None")

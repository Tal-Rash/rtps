import sqlite3
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\base\common_database.db')
c = conn.cursor()
rows = c.execute("SELECT * FROM employees WHERE name LIKE '%Ханин%' AND y=2026").fetchall()
for r in rows:
    print(r)

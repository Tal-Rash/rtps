import sqlite3
conn = sqlite3.connect(r"g:\Мой диск\Codex\base\common_database.db")
print(conn.execute('SELECT last_date FROM employee_trainings LIMIT 15').fetchall())

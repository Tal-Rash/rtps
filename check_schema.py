import sqlite3
import sys
conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\data\tabel.db')
cur = conn.cursor()
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for row in cur.fetchall():
    print('---')
    print(row[0])
    print(row[1])

# -*- coding: utf-8 -*-
"""
Тестовая проверка анонимизации SQLite базы данных.
Выводит 3 образца записей из таблицы employees и timesheet.
"""

import sqlite3
from pathlib import Path

db_path = Path("base/common_database.db")

if db_path.exists():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print("=== ОБРАЗЦЫ EMPLOYEES ===")
    for r in cur.execute("SELECT tab_num, pos, name, full_name FROM employees LIMIT 5").fetchall():
        print(dict(r))
        
    print("\n=== ОБРАЗЦЫ TIMESHEET ===")
    for r in cur.execute("SELECT y, m, tab_num, c, v FROM timesheet LIMIT 5").fetchall():
        print(dict(r))

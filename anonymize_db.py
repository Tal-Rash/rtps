# -*- coding: utf-8 -*-
"""
Полный скрипт анонимизации всех связанных таблиц табеля (включая timesheet и vacations).
Привязывает табельные смены к новым анонимным кодам (ID_001, ID_002...).
"""

import sqlite3
import json
import shutil
from pathlib import Path

DB_PATH = Path("base/common_database.db")
BACKUP_PATH = Path("base/common_database.db.bak")

def main():
    if BACKUP_PATH.exists():
        print(f"Восстановление оригинала из {BACKUP_PATH}...")
        shutil.copy2(BACKUP_PATH, DB_PATH)
    elif not DB_PATH.exists():
        print(f"Ошибка: База данных {DB_PATH} не найдена.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Получаем уникальных сотрудников и формируем маппинг
    employees_list = []
    employees_map = {} # old_tab -> new_anon_id

    rows = cur.execute("SELECT DISTINCT tab_num, pos, name, full_name FROM employees WHERE tab_num IS NOT NULL AND tab_num != ''").fetchall()
    for i, r in enumerate(rows, start=1):
        real_tab = str(r["tab_num"] or "").strip()
        real_name = str(r["name"] or "").strip()
        real_full_name = str(r["full_name"] or real_name).strip()
        real_pos = str(r["pos"] or "").strip()

        anon_id = f"ID_{i:03d}"
        anon_name = f"Работник №{i}"
        anon_pos = f"Должность №{i}"

        emp_info = {
            "index": i,
            "real_tab": real_tab,
            "real_name": real_name,
            "real_full_name": real_full_name,
            "real_pos": real_pos,
            "anon_id": anon_id,
            "anon_name": anon_name,
            "anon_pos": anon_pos
        }
        employees_list.append(emp_info)
        employees_map[real_tab] = anon_id

    print(f"Обработка {len(employees_list)} сотрудников...")

    # 2. Обновление таблицы employees
    for emp in employees_list:
        cur.execute("""
            UPDATE employees
            SET name = ?,
                full_name = ?,
                pos = ?,
                tab_num = ?
            WHERE tab_num = ?
        """, (emp["anon_name"], emp["anon_name"], emp["anon_pos"], emp["anon_id"], emp["real_tab"]))

    # 3. Обновление таблицы timesheet (связывание смен с новыми ID)
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    
    if "timesheet" in tables:
        print("Обновление связей смен в таблице timesheet...")
        for old_tab, new_id in employees_map.items():
            cur.execute("UPDATE timesheet SET tab_num = ? WHERE tab_num = ?", (new_id, old_tab))

    if "vacations" in tables:
        print("Обновление связей отпусков в таблице vacations...")
        for old_tab, new_id in employees_map.items():
            cur.execute("UPDATE vacations SET tab_num = ? WHERE tab_num = ?", (new_id, old_tab))

    if "vacations_schedule" in tables:
        print("Обновление связей в vacations_schedule...")
        for emp in employees_list:
            cur.execute("UPDATE vacations_schedule SET name = ?, tab_num = ? WHERE tab_num = ?", (emp["anon_name"], emp["anon_id"], emp["real_tab"]))

    if "vacations_archive" in tables:
        print("Обновление связей в vacations_archive...")
        for emp in employees_list:
            cur.execute("UPDATE vacations_archive SET name = ?, tab_num = ? WHERE tab_num = ?", (emp["anon_name"], emp["anon_id"], emp["real_tab"]))

    if "employee_row_order" in tables:
        print("Обновление связей в employee_row_order...")
        for old_tab, new_id in employees_map.items():
            cur.execute("UPDATE employee_row_order SET tab_num = ? WHERE tab_num = ?", (new_id, old_tab))

    conn.commit()
    conn.close()
    print("Успешно! Все смены, отпуска и табели связаны с анонимными ID!")

if __name__ == "__main__":
    main()

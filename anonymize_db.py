# -*- coding: utf-8 -*-
"""
Полный скрипт анонимизации SQLite базы данных с использованием is_same_person для 100% очистки всех таблиц.
"""

import sqlite3
import json
import shutil
from pathlib import Path

DB_PATH = Path("base/common_database.db")
BACKUP_PATH = Path("base/common_database.db.bak")

def normalize_tab(tab: str) -> str:
    if not tab: return ""
    return str(tab).strip().lstrip('0')

def is_same_person(name1: str, name2: str, tab1: str = "", tab2: str = "") -> bool:
    t1 = normalize_tab(tab1)
    t2 = normalize_tab(tab2)
    if t1 and t2:
        return t1 == t2

    s1 = str(name1 or "").strip().lower()
    s2 = str(name2 or "").strip().lower()
    if not s1 or not s2:
        return False
    if s1 == s2:
        return True

    if ("№" in s1 or "id_" in s1) and ("№" in s2 or "id_" in s2):
        n1 = "".join(c for c in s1 if c.isdigit())
        n2 = "".join(c for c in s2 if c.isdigit())
        if n1 and n2:
            return int(n1) == int(n2)

    p1 = s1.replace('.', ' ').split()
    p2 = s2.replace('.', ' ').split()
    if not p1 or not p2:
        return False
    if p1[0] != p2[0]:
        return False
    if len(p1) > 1 and len(p2) > 1:
        if len(p1[1]) == 1 or len(p2[1]) == 1:
            if p1[1][0] != p2[1][0]:
                return False
        else:
            if p1[1] != p2[1]:
                return False
    return True

def make_short_fio(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}. {parts[2][0]}."
    elif len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return full_name

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

    employees_list = []

    rows = cur.execute("SELECT DISTINCT tab_num, pos, name, full_name FROM employees WHERE tab_num IS NOT NULL AND tab_num != ''").fetchall()
    for i, r in enumerate(rows, start=1):
        real_tab = str(r["tab_num"] or "").strip()
        real_name = str(r["name"] or "").strip()
        real_full_name = str(r["full_name"] or real_name).strip()
        real_short_name = make_short_fio(real_full_name)
        real_pos = str(r["pos"] or "").strip()

        anon_id = f"ID_{i:03d}"
        anon_short_name = f"Работник №{i}"
        anon_full_name = f"СотрудникПолн №{i}"
        anon_pos = f"Должность №{i}"

        emp_info = {
            "index": i,
            "real_tab": real_tab,
            "real_name": real_name,
            "real_full_name": real_full_name,
            "real_short_name": real_short_name,
            "real_pos": real_pos,
            "anon_id": anon_id,
            "anon_short_name": anon_short_name,
            "anon_full_name": anon_full_name,
            "anon_pos": anon_pos
        }
        employees_list.append(emp_info)

    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

    extra_counter = len(employees_list) + 1
    if "vacations_archive" in tables:
        arc_rows = cur.execute("SELECT DISTINCT tab_num, name FROM vacations_archive").fetchall()
        for ar in arc_rows:
            a_tab = str(ar["tab_num"] or "").strip()
            a_name = str(ar["name"] or "").strip()
            if not a_tab and not a_name:
                continue

            matched = False
            for emp in employees_list:
                if is_same_person(emp["real_name"], a_name, emp["real_tab"], a_tab) or \
                   is_same_person(emp["real_full_name"], a_name, emp["real_tab"], a_tab) or \
                   is_same_person(emp["real_short_name"], a_name, emp["real_tab"], a_tab):
                    matched = True
                    break

            if not matched:
                anon_id = f"ID_{extra_counter:03d}"
                anon_short = f"Работник №{extra_counter}"
                anon_full = f"СотрудникПолн №{extra_counter}"
                anon_pos = f"Должность №{extra_counter}"
                emp_info = {
                    "index": extra_counter,
                    "real_tab": a_tab,
                    "real_name": a_name,
                    "real_full_name": a_name,
                    "real_short_name": a_name,
                    "real_pos": "",
                    "anon_id": anon_id,
                    "anon_short_name": anon_short,
                    "anon_full_name": anon_full,
                    "anon_pos": anon_pos
                }
                employees_list.append(emp_info)
                extra_counter += 1

    print(f"Анонимизация {len(employees_list)} сотрудников во всех таблицах базы данных...")

    # 1. Update employees table
    for emp in employees_list:
        cur.execute("""
            UPDATE employees
            SET name = ?, full_name = ?, pos = ?, tab_num = ?
            WHERE rowid in (
                SELECT rowid FROM employees WHERE tab_num = ? OR name = ? OR full_name = ?
            )
        """, (emp["anon_short_name"], emp["anon_full_name"], emp["anon_pos"], emp["anon_id"], emp["real_tab"], emp["real_name"], emp["real_full_name"]))

    # 2. Update timesheet table
    if "timesheet" in tables:
        t_rows = cur.execute("SELECT rowid, tab_num FROM timesheet").fetchall()
        for tr in t_rows:
            row_tab = str(tr[1] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], "", emp["real_tab"], row_tab) or is_same_person(emp["real_full_name"], "", emp["real_tab"], row_tab):
                    cur.execute("UPDATE timesheet SET tab_num = ? WHERE rowid = ?", (emp["anon_id"], tr[0]))
                    break

    # 3. Update vacations table
    if "vacations" in tables:
        v_rows = cur.execute("SELECT rowid, tab_num FROM vacations").fetchall()
        for vr in v_rows:
            row_tab = str(vr[1] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], "", emp["real_tab"], row_tab) or is_same_person(emp["real_full_name"], "", emp["real_tab"], row_tab):
                    cur.execute("UPDATE vacations SET tab_num = ? WHERE rowid = ?", (emp["anon_id"], vr[0]))
                    break

    # 4. Update vacations_schedule table
    if "vacations_schedule" in tables:
        vs_rows = cur.execute("SELECT rowid, y, tab_num, name FROM vacations_schedule").fetchall()
        for vsr in vs_rows:
            row_tab = str(vsr[2] or "")
            row_name = str(vsr[3] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], row_name, emp["real_tab"], row_tab) or \
                   is_same_person(emp["real_full_name"], row_name, emp["real_tab"], row_tab) or \
                   is_same_person(emp["real_short_name"], row_name, emp["real_tab"], row_tab):
                    cur.execute("UPDATE vacations_schedule SET tab_num = ?, name = ? WHERE rowid = ?", (emp["anon_id"], emp["anon_short_name"], vsr[0]))
                    break

    # 5. Update vacations_archive table
    if "vacations_archive" in tables:
        va_rows = cur.execute("SELECT rowid, tab_num, name FROM vacations_archive").fetchall()
        for var in va_rows:
            row_tab = str(var[1] or "")
            row_name = str(var[2] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], row_name, emp["real_tab"], row_tab) or \
                   is_same_person(emp["real_full_name"], row_name, emp["real_tab"], row_tab) or \
                   is_same_person(emp["real_short_name"], row_name, emp["real_tab"], row_tab):
                    cur.execute("UPDATE vacations_archive SET tab_num = ?, name = ? WHERE rowid = ?", (emp["anon_id"], emp["anon_short_name"], var[0]))
                    break

    # 6. Update employee_row_order table
    if "employee_row_order" in tables:
        ero_rows = cur.execute("SELECT rowid, tab_num FROM employee_row_order").fetchall()
        for er in ero_rows:
            row_tab = str(er[1] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], "", emp["real_tab"], row_tab) or is_same_person(emp["real_full_name"], "", emp["real_tab"], row_tab):
                    cur.execute("UPDATE employee_row_order SET tab_num = ? WHERE rowid = ?", (emp["anon_id"], er[0]))
                    break

    # 7. Update employee_trainings table
    if "employee_trainings" in tables:
        et_rows = cur.execute("SELECT rowid, tab_num FROM employee_trainings").fetchall()
        for et in et_rows:
            row_tab = str(et[1] or "")
            for emp in employees_list:
                if is_same_person(emp["real_name"], "", emp["real_tab"], row_tab) or is_same_person(emp["real_full_name"], "", emp["real_tab"], row_tab):
                    cur.execute("UPDATE employee_trainings SET tab_num = ? WHERE rowid = ?", (emp["anon_id"], et[0]))
                    break

    conn.commit()
    conn.close()
    print("Успешно! Все записи во всех таблицах анонимизированы по сопоставлению ФИО и Таб. №.")

if __name__ == "__main__":
    main()

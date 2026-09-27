# -*- coding: utf-8 -*-
"""
Скрипт полной анонимизации персональных данных (ФИО, Должности, Табельные номера) в базе данных SQLite.
1. Восстанавливает чистую исходную БД из бэкапа (если есть).
2. Сохраняет маппинг в файл Excel (employees_private.xlsx) с колонками:
   - Код системы (ID)
   - Должность
   - ФИО
   - Табельный номер
3. Очищает поля в БД на сервере (заменяет ФИО на 'Работник №X', Должность на 'Должность №X', Таб. № на 'ID_00X')
"""

import sqlite3
import json
import shutil
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

DB_PATH = Path("base/common_database.db")
BACKUP_PATH = Path("base/common_database.db.bak")
EXPORT_XLSX_PATH = Path("employees_private.xlsx")

def main():
    # Если бэкап есть, восстанавливаем исходную БД перед обработкой
    if BACKUP_PATH.exists():
        print(f"Восстановление оригинала из {BACKUP_PATH}...")
        shutil.copy2(BACKUP_PATH, DB_PATH)
    elif not DB_PATH.exists():
        print(f"Ошибка: Файл базы данных {DB_PATH} не найден.")
        return
    else:
        print(f"Создание бэкапа базы данных в {BACKUP_PATH}...")
        shutil.copy2(DB_PATH, BACKUP_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Считываем сотрудников
    employees_map = {} # tab_num -> dict
    employees_list = []
    
    try:
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
            employees_map[real_tab] = emp_info
            employees_map[real_name] = emp_info
            employees_map[real_full_name] = emp_info
    except Exception as e:
        print(f"Ошибка при чтении сотрудников: {e}")
        return

    # 2. Экспорт в Excel (employees_private.xlsx)
    print(f"Сохранение полной карточки сотрудников в Excel {EXPORT_XLSX_PATH}...")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сотрудники"

    # Шапка Excel
    ws.append(["Код системы (ID)", "Должность", "ФИО", "Табельный номер"])

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for emp in employees_list:
        ws.append([
            emp["anon_id"],
            emp["real_pos"],
            emp["real_full_name"],
            emp["real_tab"]
        ])

    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 40
    ws.column_dimensions['C'].width = 40
    ws.column_dimensions['D'].width = 20

    wb.save(EXPORT_XLSX_PATH)
    print(f"Сохранено {len(employees_list)} записей в Excel.")

    # 3. Полное обезличивание БД
    print("Анонимизация таблицы employees...")
    for emp in employees_list:
        cur.execute("""
            UPDATE employees
            SET name = ?,
                full_name = ?,
                pos = ?,
                tab_num = ?
            WHERE tab_num = ? OR name = ? OR full_name = ?
        """, (emp["anon_name"], emp["anon_name"], emp["anon_pos"], emp["anon_id"],
              emp["real_tab"], emp["real_name"], emp["real_full_name"]))

    print("Анонимизация таблицы vacations_schedule...")
    try:
        for emp in employees_list:
            cur.execute("""
                UPDATE vacations_schedule
                SET name = ?,
                    tab_num = ?
                WHERE tab_num = ? OR name = ?
            """, (emp["anon_name"], emp["anon_id"], emp["real_tab"], emp["real_name"]))
    except Exception as e:
        print(f"Пропуск vacations_schedule: {e}")

    print("Анонимизация таблицы vacations_archive...")
    try:
        for emp in employees_list:
            cur.execute("""
                UPDATE vacations_archive
                SET name = ?,
                    tab_num = ?
                WHERE tab_num = ? OR name = ?
            """, (emp["anon_name"], emp["anon_id"], emp["real_tab"], emp["real_name"]))
    except Exception as e:
        print(f"Пропуск vacations_archive: {e}")

    print("Анонимизация таблицы employee_row_order...")
    try:
        for emp in employees_list:
            cur.execute("""
                UPDATE employee_row_order
                SET tab_num = ?
                WHERE tab_num = ?
            """, (emp["anon_id"], emp["real_tab"]))
    except Exception as e:
        print(f"Пропуск employee_row_order: {e}")

    print("Анонимизация таблицы vacation_versions...")
    try:
        versions = cur.execute("SELECT id, data_json FROM vacation_versions").fetchall()
        for v in versions:
            v_id = v["id"]
            raw_json = v["data_json"]
            if raw_json:
                data = json.loads(raw_json)
                for item in data:
                    old_tab = str(item.get("tab_num", "")).strip()
                    old_name = str(item.get("name", "")).strip()
                    emp_found = employees_map.get(old_tab) or employees_map.get(old_name)
                    if emp_found:
                        item["tab_num"] = emp_found["anon_id"]
                        item["name"] = emp_found["anon_name"]
                        item["full_name"] = emp_found["anon_name"]
                        if "position" in item:
                            item["position"] = emp_found["anon_pos"]
                        if "pos" in item:
                            item["pos"] = emp_found["anon_pos"]
                new_json = json.dumps(data, ensure_ascii=False)
                cur.execute("UPDATE vacation_versions SET data_json = ? WHERE id = ?", (new_json, v_id))
    except Exception as e:
        print(f"Пропуск vacation_versions: {e}")

    conn.commit()
    conn.close()
    print("Успешно! База данных полностью обезличена (ФИО, Должности и Таб. номера).")

if __name__ == "__main__":
    main()

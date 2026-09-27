# -*- coding: utf-8 -*-
"""
Скрипт анонимизации персональных данных в базе данных SQLite.
1. Создаёт резервную копию базы данных common_database.db.bak
2. Экспортирует словарь соответствий (Табельный номер -> ФИО) в локальный файл Excel (employees_private.xlsx)
3. Очищает поля name и full_name в таблицах БД (заменяет на 'Сотрудник <tab_num>')
"""

import sqlite3
import json
import shutil
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# Константы путей
DB_PATH = Path("base/common_database.db")
BACKUP_PATH = Path("base/common_database.db.bak")
EXPORT_XLSX_PATH = Path("employees_private.xlsx")

def main():

    if not DB_PATH.exists():
        print(f"Ошибка: Файл базы данных {DB_PATH} не найден.")
        return

    # 1. Создание резервной копии базы данных
    print(f"Создание резервной копии базы данных в {BACKUP_PATH}...")
    shutil.copy2(DB_PATH, BACKUP_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 2. Сбор оригинальных персональных данных из таблицы employees
    employees_dict = {} # tab_num -> {name, full_name}
    
    try:
        rows = cur.execute("SELECT tab_num, name, full_name FROM employees").fetchall()
        for r in rows:
            tab = str(r["tab_num"]).strip()
            name = str(r["name"] or "").strip()
            full_name = str(r["full_name"] or "").strip()
            if tab:
                employees_dict[tab] = {
                    "name": name,
                    "full_name": full_name if full_name else name
                }
    except Exception as e:
        print(f"Предупреждение при чтении таблицы employees: {e}")

    # 3. Сохранение словаря ПДн в локальный файл Excel
    print(f"Сохранение словаря ПДн в локальный файл Excel {EXPORT_XLSX_PATH}...")
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сотрудники"
    
    # Шапка таблицы Excel
    ws.append(["Табельный номер", "ФИО"])
    
    # Красивое оформление шапки
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Заполнение данных
    for tab, data in employees_dict.items():
        ws.append([tab, data["full_name"]])
        
    # Автоматическая ширина колонок
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 40

    wb.save(EXPORT_XLSX_PATH)
    print(f"Успешно экспортировано {len(employees_dict)} записей сотрудников в Excel.")

    # 4. Анонимизация таблицы employees
    print("Анонимизация таблицы employees...")
    cur.execute("""
        UPDATE employees 
        SET name = 'Сотрудник №' || tab_num,
            full_name = 'Сотрудник №' || tab_num
    """)

    # 5. Анонимизация таблицы vacations_schedule
    print("Анонимизация таблицы vacations_schedule...")
    try:
        cur.execute("""
            UPDATE vacations_schedule 
            SET name = 'Сотрудник №' || tab_num
        """)
    except Exception as e:
        print(f"Пропуск vacations_schedule: {e}")

    # 6. Анонимизация таблицы vacations_archive
    print("Анонимизация таблицы vacations_archive...")
    try:
        cur.execute("""
            UPDATE vacations_archive 
            SET name = 'Сотрудник №' || tab_num
        """)
    except Exception as e:
        print(f"Пропуск vacations_archive: {e}")

    # 7. Анонимизация таблицы vacation_versions (внутри JSON)
    print("Анонимизация таблицы vacation_versions...")
    try:
        versions = cur.execute("SELECT id, data_json FROM vacation_versions").fetchall()
        for v in versions:
            v_id = v["id"]
            raw_json = v["data_json"]
            if raw_json:
                data = json.loads(raw_json)
                for item in data:
                    t_num = item.get("tab_num", "")
                    item["name"] = f"Сотрудник №{t_num}"
                    item["full_name"] = f"Сотрудник №{t_num}"
                new_json = json.dumps(data, ensure_ascii=False)
                cur.execute("UPDATE vacation_versions SET data_json = ? WHERE id = ?", (new_json, v_id))
    except Exception as e:
        print(f"Пропуск vacation_versions: {e}")

    conn.commit()
    conn.close()
    print("Успешно! Все персональные данные в базе данных анонимизированы.")

if __name__ == "__main__":
    main()

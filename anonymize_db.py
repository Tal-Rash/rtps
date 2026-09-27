# -*- coding: utf-8 -*-
"""
Скрипт анонимизации персональных данных в базе данных SQLite.
1. Создаёт резервную копию базы данных common_database.db.bak
2. Экспортирует словарь соответствий (Табельный номер -> ФИО) в локальный файл employees_private.txt
3. Очищает поля name и full_name в таблицах БД (заменяет на 'Сотрудник <tab_num>')
"""

import sqlite3
import json
import shutil
from pathlib import Path

# Константы путей
DB_PATH = Path("base/common_database.db")
BACKUP_PATH = Path("base/common_database.db.bak")
EXPORT_TXT_PATH = Path("employees_private.txt")

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

    # 3. Сохранение словаря ПДн в локальный текстовый файл
    print(f"Сохранение словаря ПДн в локальный файл {EXPORT_TXT_PATH}...")
    with open(EXPORT_TXT_PATH, "w", encoding="utf-8") as f:
        f.write("# Формат: Табельный_Номер = ФИО\n")
        for tab, data in employees_dict.items():
            f.write(f"{tab}={data['full_name']}\n")

    print(f"Успешно экспортировано {len(employees_dict)} записей сотрудников.")

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

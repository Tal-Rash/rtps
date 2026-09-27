# -*- coding: utf-8 -*-
"""
Скрипт создания файла CSV (employees_private.csv) из файла Excel employees_private.xlsx.
Файл CSV легко открывается и редактируется в MS Excel.
"""

import openpyxl
import csv
from pathlib import Path

xlsx_path = Path("employees_private.xlsx")
csv_path = Path("employees_private.csv")

if xlsx_path.exists():
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        for row in ws.iter_rows(values_only=True):
            if any(row):
                writer.writerow(row)
                
    print(f"Успешно экспортирован файл {csv_path} для работы в Excel!")

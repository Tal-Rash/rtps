# -*- coding: utf-8 -*-
"""
Скрипт восстановления эталонных ФИО (полных и сокращенных), Должностей и Табельных номеров в Excel и CSV.
"""

import openpyxl
import csv
from openpyxl.styles import Font, PatternFill, Alignment
from pathlib import Path

# Функция автоматического формирования сокращенного ФИО (Иванов И. В.)
def make_short_fio(full_name: str) -> str:
    parts = full_name.strip().split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}. {parts[2][0]}."
    elif len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return full_name

def load_real_employees(root_dir: Path) -> list:
    """Загружает список сотрудников из локального файла employees_private.csv / xlsx при его наличии."""
    csv_path = root_dir / "employees_private.csv"
    if csv_path.exists():
        res = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            for row in reader:
                if not row or len(row) < 3 or str(row[0]).startswith("Код"):
                    continue
                tab = row[4].strip() if len(row) > 4 else (row[3].strip() if len(row) > 3 and row[3].strip().isdigit() else row[0].strip())
                res.append({
                    "tab": tab,
                    "fio": row[2].strip() if len(row) > 2 else "",
                    "pos": row[1].strip() if len(row) > 1 else ""
                })
        return res
    return []

REAL_EMPLOYEES = []

def main():
    root_dir = Path(__file__).resolve().parent.parent
    xlsx_path = root_dir / "employees_private.xlsx"
    csv_path = root_dir / "employees_private.csv"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сотрудники"

    headers = ["Код системы (ID)", "Должность", "ФИО полное", "ФИО сокращённое", "Табельный номер"]
    ws.append(headers)

    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    employees = load_real_employees(root_dir) or REAL_EMPLOYEES
    rows = []
    for i, emp in enumerate(employees, start=1):
        anon_id = f"ID_{i:03d}"
        short_fio = make_short_fio(emp["fio"])
        row = [anon_id, emp["pos"], emp["fio"], short_fio, emp["tab"]]
        ws.append(row)
        rows.append(row)

    ws.column_dimensions['A'].width = 18
    ws.column_dimensions['B'].width = 45
    ws.column_dimensions['C'].width = 35
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['E'].width = 20

    wb.save(xlsx_path)
    print(f"Файл {xlsx_path} обновился с сокращенными ФИО!")

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        writer.writerows(rows)

    print(f"Файл {csv_path} обновился с сокращенными ФИО!")

if __name__ == "__main__":
    main()

from __future__ import annotations

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime, date
from io import BytesIO
import re
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

try:
    from .constants import ROOT
except (ImportError, ValueError):
    from constants import ROOT

def create_archive_excel(rows_data: list, title: str = "Архив отпусков") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Архив отпусков"
    ws.views.sheetView[0].showGridLines = True

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="276EF1", end_color="276EF1", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    
    thin_border = Border(
        left=Side(style='thin', color='D0D7DE'),
        right=Side(style='thin', color='D0D7DE'),
        top=Side(style='thin', color='D0D7DE'),
        bottom=Side(style='thin', color='D0D7DE')
    )

    headers = ["Год", "Сотрудник", "Табельный номер", "Дата начала", "Дата окончания", "Дней отпуска", "Примечание"]
    ws.append(headers)

    header_row = ws[1]
    ws.row_dimensions[1].height = 28
    for cell in header_row:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    data_font = Font(name="Segoe UI", size=10)
    
    private_map = load_private_employee_mapping()

    for row_idx, r in enumerate(rows_data, 2):
        row_name = str(r.get("name") or "").strip()
        row_tab = str(r.get("tab_num") or "").strip()
        if private_map:
            priv = private_map.get(row_tab) or private_map.get(row_name)
            if priv:
                row_name = priv.get("name") or priv.get("full_name") or row_name
                row_tab = priv.get("tab_num") or row_tab

        ws.append([
            r.get("y", 2025),
            row_name,
            row_tab,
            r.get("start_date", ""),
            r.get("end_date", ""),
            r.get("days", 0),
            r.get("note", "")
        ])
        ws.row_dimensions[row_idx].height = 22
        
        row_cells = ws[row_idx]
        for c_idx, cell in enumerate(row_cells, 1):
            cell.font = data_font
            cell.border = thin_border
            if c_idx in (1, 3, 4, 5, 6):
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    col_widths = {1: 10, 2: 32, 3: 18, 4: 16, 5: 16, 6: 15, 7: 35}
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def load_private_employee_mapping() -> dict[str, dict[str, str]]:
    """Загружает локальный справочник реальных ФИО и должностей исключительно из локального файла employees_private.csv / xlsx, если он существует"""
    mapping = {}

    def register_entry(anon_id: str, pos: str, full_fio: str, short_fio: str, real_tab: str):
        # Гарантируем, что табельный номер (число) никогда не попадет в ФИО
        s_fio = short_fio.strip() if short_fio else ""
        f_fio = full_fio.strip() if full_fio else ""
        if s_fio.isdigit():
            s_fio = f_fio if (f_fio and not f_fio.isdigit()) else ""
        if f_fio.isdigit():
            f_fio = s_fio if (s_fio and not s_fio.isdigit()) else ""

        # Формируем объект сведений о сотруднике
        info = {
            "name": s_fio or f_fio,
            "full_name": f_fio or s_fio,
            "position": pos.strip() if pos else "",
            "tab_num": real_tab.strip() if real_tab else anon_id
        }

        # Регистрация по ID и табельному номеру
        if anon_id:
            mapping[anon_id] = info
            mapping[anon_id.lower()] = info
        if real_tab:
            mapping[real_tab] = info
            mapping[f"Сотрудник №{real_tab}"] = info
            mapping[f"Работник №{real_tab}"] = info
            mapping[f"СотрудникПолн №{real_tab}"] = info
            mapping[f"Сотрудник № {real_tab}"] = info
            mapping[f"Работник № {real_tab}"] = info

        # Регистрация по ФИО (только если это не чистое число)
        if s_fio and not s_fio.isdigit():
            mapping[s_fio] = info
            mapping[s_fio.lower()] = info
        if f_fio and not f_fio.isdigit():
            mapping[f_fio] = info
            mapping[f_fio.lower()] = info

        # Регистрация по порядковому номеру и шаблонам анонимизации
        num_str = "".join(ch for ch in anon_id if ch.isdigit())
        if num_str:
            num = int(num_str)
            p_num = f"{num:03d}"
            mapping[str(num)] = info
            mapping[f"ID_{p_num}"] = info
            mapping[f"ID_{num}"] = info
            mapping[f"id_{p_num}"] = info
            mapping[f"id_{num}"] = info
            mapping[f"Работник №{num}"] = info
            mapping[f"Работник №{p_num}"] = info
            mapping[f"Работник № {num}"] = info
            mapping[f"Сотрудник №{num}"] = info
            mapping[f"Сотрудник №{p_num}"] = info
            mapping[f"Сотрудник № {num}"] = info
            mapping[f"СотрудникПолн №{num}"] = info
            mapping[f"СотрудникПолн №{p_num}"] = info
            mapping[f"Должность №{num}"] = info
            mapping[f"Должность №{p_num}"] = info

    # 2. Если на сервере есть локальный файл, обновляем данные из него
    csv_file = ROOT.parent / "employees_private.csv"
    xlsx_file = ROOT.parent / "employees_private.xlsx"

    if csv_file.exists():
        try:
            import csv
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f, delimiter=";")
                for row in reader:
                    if not row or len(row) < 3 or str(row[0]).startswith("Код"):
                        continue
                    anon_id = row[0].strip()
                    pos = row[1].strip() if len(row) > 1 else ""
                    # Если файл имеет 4 колонки: ID; Должность; ФИО; Табельный
                    if len(row) == 4:
                        full_fio = row[2].strip()
                        short_fio = row[2].strip()
                        real_tab = row[3].strip()
                    else:
                        full_fio = row[2].strip() if len(row) > 2 else ""
                        c3 = row[3].strip() if len(row) > 3 else ""
                        c4 = row[4].strip() if len(row) > 4 else ""
                        if c3.isdigit() and not c4:
                            # 3-я колонка числовая — это табельный номер
                            short_fio = full_fio
                            real_tab = c3
                        else:
                            short_fio = c3 or full_fio
                            real_tab = c4 or anon_id
                    register_entry(anon_id, pos, full_fio, short_fio, real_tab)
        except Exception:
            pass
    elif xlsx_file.exists():
        try:
            wb = openpyxl.load_workbook(xlsx_file, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                if not row or not row[0] or str(row[0]).startswith("Код"):
                    continue
                anon_id = str(row[0]).strip()
                pos = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                if len(row) == 4:
                    full_fio = str(row[2]).strip() if row[2] else ""
                    short_fio = full_fio
                    real_tab = str(row[3]).strip() if row[3] else anon_id
                else:
                    full_fio = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                    c3 = str(row[3]).strip() if len(row) > 3 and row[3] else ""
                    c4 = str(row[4]).strip() if len(row) > 4 and row[4] else ""
                    if c3.isdigit() and not c4:
                        short_fio = full_fio
                        real_tab = c3
                    else:
                        short_fio = c3 or full_fio
                        real_tab = c4 or anon_id
                register_entry(anon_id, pos, full_fio, short_fio, real_tab)
        except Exception:
            pass

    return mapping

def parse_holiday_dates(dates_str: str, max_days: int) -> set[int]:
    """Парсит строку праздничных дат (например '1, 2, 3, 4, 5, 6, 7, 8' или '1-8') во множество номеров дней"""
    if not dates_str:
        return set()
    holidays = set()
    parts = re.split(r'[,;\s]+', str(dates_str).strip())
    for part in parts:
        if not part:
            continue
        if '-' in part:
            r = part.split('-')
            try:
                s, e = int(r[0]), int(r[1])
                for d in range(s, e + 1):
                    if 1 <= d <= max_days:
                        holidays.add(d)
            except Exception:
                pass
        else:
            try:
                d = int(part)
                if 1 <= d <= max_days:
                    holidays.add(d)
            except Exception:
                pass
    return holidays

def get_working_vacation_days(start_m: int, start_d: int, end_m: int, end_d: int, holidays_data: list, cal_days: list) -> int:
    """Рассчитывает количество календарных дней отпуска без учета нерабочих праздничных дней (ст. 120 ТК РФ)"""
    count = 0
    for m in range(start_m, end_m + 1):
        s = start_d if m == start_m else 1
        e = end_d if m == end_m else cal_days[m]
        dates_str = ""
        if m < len(holidays_data) and isinstance(holidays_data[m], dict):
            dates_str = holidays_data[m].get("dates", "")
        elif m == 12:
            dates_str = "1, 2, 3, 4, 5, 6, 7, 8"
        h_set = parse_holiday_dates(dates_str, cal_days[m])
        for d in range(s, e + 1):
            if d not in h_set:
                count += 1
    return count

def create_schedule_excel(year: int, items: list, holidays_data: list = None, include_carried_fact: bool = False) -> bytes:
    """Формирует профессионально оформленный файл Excel (.xlsx) с графиком отпусков."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"График {year}"
    ws.views.sheetView[0].showGridLines = True

    # Локальный справочник реальных сотрудников при наличии на сервере
    private_map = load_private_employee_mapping()

    # Определение количества дней в месяцах (с проверкой високосного года)
    is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    feb_days = 29 if is_leap else 28
    cal_days = [31, feb_days, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31, 31]
    month_names = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        f"Январь {year + 1}"
    ]

    if not holidays_data:
        holidays_data = []

    # Расчет рабочих дней по каждому месяцу (за вычетом праздников)
    days_in_months = []
    for m in range(13):
        dates_str = ""
        if m < len(holidays_data) and isinstance(holidays_data[m], dict):
            dates_str = holidays_data[m].get("dates", "")
        elif m == 12:
            dates_str = "1, 2, 3, 4, 5, 6, 7, 8"
        h_set = parse_holiday_dates(dates_str, cal_days[m])
        days_in_months.append(max(0, cal_days[m] - len(h_set)))

    total_year_working_days = sum(days_in_months[:12]) or 365

    # Стили шрифтов и заливки
    title_font = Font(name="Segoe UI", size=14, bold=True, color="1F4E78")
    meta_font = Font(name="Segoe UI", size=9, italic=True, color="555555")
    th1_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    th2_font = Font(name="Segoe UI", size=9, bold=True, color="1E293B")
    data_font = Font(name="Segoe UI", size=9)
    bold_data_font = Font(name="Segoe UI", size=9, bold=True)
    small_desc_font = Font(name="Segoe UI", size=8, color="475569")

    th1_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    th2_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    # Черная заливка для ячеек отпусков с белым шрифтом по требованию пользователя
    vacation_fill = PatternFill(start_color="000000", end_color="000000", fill_type="solid")
    vacation_font = Font(name="Segoe UI", size=9, bold=True, color="FFFFFF")
    carried_fill = PatternFill(start_color="000000", end_color="000000", fill_type="solid")
    summary1_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    summary2_fill = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
    summary3_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    thin_side = Side(style='thin', color='CBD5E1')
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    thick_bottom_side = Side(style='medium', color='1F4E78')
    header_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thick_bottom_side)

    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    def apply_range_border(start_r, start_c, end_r, end_c, border=thin_border, fill=None):
        for r in range(start_r, end_r + 1):
            for c in range(start_c, end_c + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = border
                if fill:
                    cell.fill = fill

    # 1. Заголовок таблицы (ширина 30 колонок A-AD)
    ws.merge_cells("A1:AD1")
    ws["A1"] = f"ГРАФИК ОТПУСКОВ РАБОТНИКОВ НА {year} ГОД"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:AD2")
    ws["A2"] = f"Дата выгрузки: {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  Всего работников: {len(items)}"
    ws["A2"].font = meta_font
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 18

    # 2. Шапка графической таблицы (строки 3 и 4)
    ws.row_dimensions[3].height = 28
    ws.row_dimensions[4].height = 20

    headers_fixed = [
        (1, "№\nп/п"),
        (2, "Сотрудник (ФИО)"),
        (3, "Должность"),
        (4, "Отпуск\n(дней)")
    ]

    for col_idx, title in headers_fixed:
        ws.merge_cells(start_row=3, start_column=col_idx, end_row=4, end_column=col_idx)
        cell = ws.cell(row=3, column=col_idx, value=title)
        cell.font = th1_font
        cell.alignment = center_align
        apply_range_border(3, col_idx, 4, col_idx, border=header_border, fill=th1_fill)

    # Заголовки месяцев (колонки 5 .. 30)
    for m in range(13):
        c_start = 5 + 2 * m
        c_end = 6 + 2 * m
        ws.merge_cells(start_row=3, start_column=c_start, end_row=3, end_column=c_end)
        cell = ws.cell(row=3, column=c_start, value=f"{month_names[m]}\n({days_in_months[m]} дн.)")
        cell.font = th1_font
        cell.alignment = center_align
        apply_range_border(3, c_start, 3, c_end, border=thin_border, fill=th1_fill)

        cell_c = ws.cell(row=4, column=c_start, value="с")
        cell_c.font = th2_font
        cell_c.alignment = center_align
        cell_c.fill = th2_fill
        cell_c.border = header_border

        cell_po = ws.cell(row=4, column=c_end, value="по")
        cell_po.font = th2_font
        cell_po.alignment = center_align
        cell_po.fill = th2_fill
        cell_po.border = header_border

    # 3. Данные сотрудников в графической таблице (начиная со строки 5)
    start_data_row = 5
    current_row = start_data_row
    month_fact_sums = [0] * 13
    periods_table_data = []

    for idx, emp in enumerate(items, 1):
        ws.row_dimensions[current_row].height = 20

        raw_tab = str(emp.get("tab_num") or "").strip()
        raw_name = str(emp.get("name") or "").strip()
        raw_full = str(emp.get("full_name") or "").strip()
        raw_pos = str(emp.get("position") or "").strip()
        emp_id = emp.get("id")
        allowed_val = int(emp.get("vacation_days") or emp.get("allowedDays") or 28)

        # Подстановка реальных данных сотрудника из расширенного локального справочника
        priv = None
        search_candidates = [
            raw_tab, raw_name, raw_full,
            f"ID_{idx:03d}", f"ID_{idx}",
            str(emp_id) if emp_id else "",
            f"ID_{int(emp_id):03d}" if str(emp_id).isdigit() else ""
        ]
        # Извлекаем все числовые последовательности (табельные номера или ID)
        for s in (raw_name, raw_full, raw_tab):
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                search_candidates.extend([digits, f"ID_{int(digits):03d}" if len(digits) <= 3 else digits])

        for cand in search_candidates:
            if cand and cand in private_map:
                priv = private_map[cand]
                break
            if cand and cand.lower() in private_map:
                priv = private_map[cand.lower()]
                break

        # Определение финальных значений ФИО, должности и табельного с приоритетом реальных данных
        is_raw_real = raw_name and not raw_name.isdigit() and not raw_name.startswith("Работник №") and not raw_name.startswith("Сотрудник №") and not raw_name.startswith("ID_")
        is_full_real = raw_full and not raw_full.isdigit() and not raw_full.startswith("СотрудникПолн №") and not raw_full.startswith("Работник №") and not raw_full.startswith("ID_")

        if is_raw_real:
            emp_name = raw_name
        elif is_full_real:
            emp_name = raw_full
        elif priv:
            p_name = priv.get("name") or priv.get("full_name") or ""
            if p_name and not p_name.isdigit():
                emp_name = p_name
            elif raw_full and not raw_full.isdigit() and not raw_full.startswith("СотрудникПолн №"):
                emp_name = raw_full
            else:
                emp_name = raw_name or f"Сотрудник {idx}"
        else:
            # Если прямое имя является табельным номером, но raw_full содержит ФИО
            if raw_name.isdigit() and raw_full and not raw_full.isdigit() and not raw_full.startswith("СотрудникПолн №"):
                emp_name = raw_full
            elif raw_name and not raw_name.isdigit():
                emp_name = raw_name
            elif raw_full and not raw_full.isdigit():
                emp_name = raw_full
            else:
                emp_name = raw_name or raw_full or f"Сотрудник {idx}"

        if priv:
            emp_pos = priv.get("position") or raw_pos or priv.get("pos", "")
            emp_tab = priv.get("tab_num") or raw_tab or priv.get("tab", "")
        else:
            emp_pos = raw_pos
            emp_tab = raw_tab

        # Гарантированная замена устаревшей фамилии Ханин на Бопхоев М. М.
        if "Ханин" in emp_name:
            emp_name = (
                emp_name.replace("Ханин Дмитрий Викторович", "Бопхоев М. М.")
                .replace("Ханин Д. В.", "Бопхоев М. М.")
                .replace("Ханин Д.В.", "Бопхоев М. М.")
                .replace("Ханин", "Бопхоев М. М.")
            )

        # Гарантированная защита: исключаем попадание чисел (табельного номера) или анонимных меток в ФИО
        clean_name = emp_name.strip()
        is_invalid_fio = (
            clean_name.isdigit()
            or clean_name.startswith("Сотрудник №")
            or clean_name.startswith("Работник №")
            or clean_name.startswith("ID_")
            or not clean_name
        )
        if is_invalid_fio:
            # Проверяем raw_full, если он содержит настоящее ФИО
            if raw_full and not raw_full.strip().isdigit() and not raw_full.startswith("СотрудникПолн №") and not raw_full.startswith("Работник №"):
                emp_name = raw_full.strip()
            else:
                for cand_key in search_candidates:
                    if cand_key and cand_key in private_map:
                        pm_entry = private_map[cand_key]
                        p_cand_name = pm_entry.get("name") or pm_entry.get("full_name")
                        if p_cand_name and not p_cand_name.strip().isdigit():
                            emp_name = p_cand_name.strip()
                            break

        # Если после всех проверок имя всё ещё числовое (табельный номер) или пустое,
        # устанавливаем маркер "Работник №{idx}", чтобы клиентский JSZip в браузере мог гарантированно подставить реальное ФИО
        if emp_name.strip().isdigit() or not emp_name.strip() or emp_name.strip().startswith("ID_"):
            emp_name = f"Работник №{idx}"

        # Подготовка данных по месяцам
        m_c_vals = [None] * 13
        m_po_vals = [None] * 13
        m_is_vac = [False] * 13
        m_is_cov = [False] * 13

        months_input = emp.get("months_data")
        if isinstance(months_input, list):
            for m_item in months_input:
                m_idx = m_item.get("month")
                if m_idx is not None and 0 <= m_idx < 13:
                    if m_item.get("c") is not None:
                        m_c_vals[m_idx] = int(m_item["c"])
                    if m_item.get("po") is not None:
                        m_po_vals[m_idx] = int(m_item["po"])

        vacations_list = emp.get("vacations") or []
        carried_list = emp.get("carried_over_vacations") or []
        all_vacs = vacations_list + carried_list

        emp_fact_days = 0
        vac_periods_desc = []

        # Обработка отпусков сотрудника
        for vac in all_vacs:
            s_str = str(vac.get("start") or "").strip()
            e_str = str(vac.get("end") or "").strip()
            if not s_str or not e_str:
                continue

            s_parts = s_str.split('-')
            e_parts = e_str.split('-')
            if len(s_parts) < 3 or len(e_parts) < 3:
                continue

            try:
                s_y = int(s_parts[0])
                s_m = int(s_parts[1]) - 1
                s_d = int(s_parts[2])

                e_y = int(e_parts[0])
                e_m = int(e_parts[1]) - 1
                e_d = int(e_parts[2])
            except ValueError:
                continue

            start_month_idx = 12 if (s_y == year + 1 and s_m == 0) else s_m
            end_month_idx = 12 if (e_y == year + 1 and e_m == 0) else e_m

            if start_month_idx < 0 or start_month_idx > 12 or end_month_idx < 0 or end_month_idx > 12:
                continue

            if m_c_vals[start_month_idx] is None:
                m_c_vals[start_month_idx] = s_d
            if m_po_vals[end_month_idx] is None:
                m_po_vals[end_month_idx] = e_d

            v_days = int(vac.get("days") or 0)
            if v_days <= 0:
                v_days = get_working_vacation_days(start_month_idx, s_d, end_month_idx, e_d, holidays_data, cal_days)

            is_cov = bool(vac.get("is_carried_over"))
            for m_i in range(start_month_idx, end_month_idx + 1):
                m_is_vac[m_i] = True
                if is_cov:
                    m_is_cov[m_i] = True

            # Учет в факте
            if not is_cov or include_carried_fact:
                emp_fact_days += v_days
                for m_i in range(start_month_idx, end_month_idx + 1):
                    seg_s = s_d if m_i == start_month_idx else 1
                    seg_e = e_d if m_i == end_month_idx else cal_days[m_i]
                    month_fact_sums[m_i] += get_working_vacation_days(m_i, seg_s, m_i, seg_e, holidays_data, cal_days)

            # Форматирование текстового описания периода с ведущими нулями (01..09)
            s_d_val = int(s_parts[2])
            s_m_val = int(s_parts[1])
            e_d_val = int(e_parts[2])
            e_m_val = int(e_parts[1])
            s_ru = f"{s_d_val:02d}.{s_m_val:02d}" + (f".{s_y}" if s_y != year else "")
            e_ru = f"{e_d_val:02d}.{e_m_val:02d}" + (f".{e_y}" if e_y != year else "")
            cov_mark = " (перенос с прошл. г.)" if is_cov else ""
            vac_periods_desc.append(f"{s_ru} - {e_ru} ({v_days} дн.){cov_mark}")

        # Сохранение периодов для вывода в секции под графической таблицей
        periods_table_data.append({
            "idx": idx,
            "name": emp_name,
            "pos": emp_pos,
            "periods": vac_periods_desc
        })

        # Запись базовых колонок
        # Колонка 1: № п/п
        c_num = ws.cell(row=current_row, column=1, value=idx)
        c_num.font = data_font
        c_num.alignment = center_align
        c_num.border = thin_border

        # Колонка 2: Сотрудник (ФИО)
        c_name = ws.cell(row=current_row, column=2, value=emp_name)
        c_name.font = bold_data_font
        c_name.alignment = left_align
        c_name.border = thin_border

        # Колонка 3: Должность
        c_pos = ws.cell(row=current_row, column=3, value=emp_pos)
        c_pos.font = data_font
        c_pos.alignment = left_align
        c_pos.border = thin_border

        # Колонка 4: Отпуск (дней)
        c_all = ws.cell(row=current_row, column=4, value=allowed_val)
        c_all.font = bold_data_font
        c_all.alignment = center_align
        c_all.border = thin_border

        # Запись ячеек месяцев (колонки 5 .. 30)
        for m in range(13):
            col_c = 5 + 2 * m
            col_po = 6 + 2 * m

            val_c = m_c_vals[m]
            val_po = m_po_vals[m]

            # Форматирование отображения дня с добавлением месяца (например, 22.03)
            m_code = "01" if m == 12 else f"{m + 1:02d}"
            display_c = f"{val_c:02d}.{m_code}" if val_c is not None else ""
            display_po = f"{val_po:02d}.{m_code}" if val_po is not None else ""

            cell_c = ws.cell(row=current_row, column=col_c, value=display_c)
            cell_po = ws.cell(row=current_row, column=col_po, value=display_po)

            cell_c.font = data_font
            cell_c.alignment = center_align
            cell_c.border = thin_border

            cell_po.font = data_font
            cell_po.alignment = center_align
            cell_po.border = thin_border

            # Оформление ячеек отпусков (черный фон, белый шрифт)
            is_vac = m_is_cov[m] or m_is_vac[m] or (val_c is not None) or (val_po is not None)
            if is_vac:
                cell_c.fill = vacation_fill
                cell_po.fill = vacation_fill
                cell_c.font = vacation_font
                cell_po.font = vacation_font

        current_row += 1

    last_data_row = current_row - 1

    # 4. Итоговые строки (Всего положено, Занесено факт, Отклонение %)
    if last_data_row >= start_data_row:
        total_allowed_days = sum(int(e.get("vacation_days") or e.get("allowedDays") or 28) for e in items)

        # Итоговая строка 1: Всего положено
        r_sum1 = current_row
        ws.row_dimensions[r_sum1].height = 24
        ws.merge_cells(start_row=r_sum1, start_column=1, end_row=r_sum1, end_column=3)
        ws.cell(row=r_sum1, column=1, value="Всего положено:").font = bold_data_font
        ws.cell(row=r_sum1, column=1).alignment = right_align
        apply_range_border(r_sum1, 1, r_sum1, 3, border=thin_border, fill=summary1_fill)

        c_s1_all = ws.cell(row=r_sum1, column=4, value=f"=SUM(D{start_data_row}:D{last_data_row})")
        c_s1_all.font = bold_data_font
        c_s1_all.alignment = center_align
        c_s1_all.fill = summary1_fill
        c_s1_all.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum1, start_column=c_s, end_row=r_sum1, end_column=c_e)
            m_norm = round((total_allowed_days / total_year_working_days) * days_in_months[m])
            cell_m = ws.cell(row=r_sum1, column=c_s, value=m_norm)
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum1, c_s, r_sum1, c_e, border=thin_border, fill=summary1_fill)

        # Итоговая строка 2: Занесено (факт)
        r_sum2 = current_row + 1
        ws.row_dimensions[r_sum2].height = 24
        ws.merge_cells(start_row=r_sum2, start_column=1, end_row=r_sum2, end_column=3)
        ws.cell(row=r_sum2, column=1, value="Занесено (факт):").font = bold_data_font
        ws.cell(row=r_sum2, column=1).alignment = right_align
        apply_range_border(r_sum2, 1, r_sum2, 3, border=thin_border, fill=summary2_fill)

        grand_fact_sum = sum(month_fact_sums)
        c_s2_fct = ws.cell(row=r_sum2, column=4, value=grand_fact_sum)
        c_s2_fct.font = bold_data_font
        c_s2_fct.alignment = center_align
        c_s2_fct.fill = summary2_fill
        c_s2_fct.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum2, start_column=c_s, end_row=r_sum2, end_column=c_e)
            cell_m = ws.cell(row=r_sum2, column=c_s, value=month_fact_sums[m])
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum2, c_s, r_sum2, c_e, border=thin_border, fill=summary2_fill)

        # Итоговая строка 3: Отклонение (%)
        r_sum3 = current_row + 2
        ws.row_dimensions[r_sum3].height = 24
        ws.merge_cells(start_row=r_sum3, start_column=1, end_row=r_sum3, end_column=3)
        ws.cell(row=r_sum3, column=1, value="Отклонение (%):").font = bold_data_font
        ws.cell(row=r_sum3, column=1).alignment = right_align
        apply_range_border(r_sum3, 1, r_sum3, 3, border=thin_border, fill=summary3_fill)

        grand_diff = grand_fact_sum - total_allowed_days
        grand_pct_str = "0%"
        if total_allowed_days > 0:
            pct = round((grand_diff / total_allowed_days) * 100)
            sign = "+" if pct > 0 else ""
            grand_pct_str = f"{sign}{pct}%"

        cell_s3_dif = ws.cell(row=r_sum3, column=4, value=grand_pct_str)
        cell_s3_dif.font = bold_data_font
        cell_s3_dif.alignment = center_align
        cell_s3_dif.fill = summary3_fill
        cell_s3_dif.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum3, start_column=c_s, end_row=r_sum3, end_column=c_e)
            m_norm = round((total_allowed_days / total_year_working_days) * days_in_months[m])
            m_fact = month_fact_sums[m]
            m_pct_str = "0%"
            if m_norm > 0:
                m_diff = m_fact - m_norm
                m_pct = round((m_diff / m_norm) * 100)
                sign = "+" if m_pct > 0 else ""
                m_pct_str = f"{sign}{m_pct}%"
            elif m_fact > 0:
                m_pct_str = "+100%"

            cell_m = ws.cell(row=r_sum3, column=c_s, value=m_pct_str)
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum3, c_s, r_sum3, c_e, border=thin_border, fill=summary3_fill)

    # 5. Секция подробных периодов отпусков (расположена под графической таблицей)
    current_row = (r_sum3 + 2) if last_data_row >= start_data_row else current_row + 2

    # Заголовок секции периодов отпусков
    ws.row_dimensions[current_row].height = 26
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=30)
    sec_title_cell = ws.cell(row=current_row, column=1, value="ПЕРИОДЫ ОТПУСКОВ РАБОТНИКОВ (ДАТЫ И КОЛИЧЕСТВО ДНЕЙ)")
    sec_title_cell.font = Font(name="Segoe UI", size=11, bold=True, color="1F4E78")
    sec_title_cell.alignment = Alignment(horizontal="left", vertical="center")
    apply_range_border(current_row, 1, current_row, 30, border=header_border, fill=th2_fill)
    current_row += 1

    # Шапка таблицы периодов
    ws.row_dimensions[current_row].height = 24
    c_p_num = ws.cell(row=current_row, column=1, value="№\nп/п")
    c_p_num.font = th1_font
    c_p_num.alignment = center_align
    c_p_num.fill = th1_fill
    c_p_num.border = header_border

    c_p_name = ws.cell(row=current_row, column=2, value="Сотрудник (ФИО)")
    c_p_name.font = th1_font
    c_p_name.alignment = center_align
    c_p_name.fill = th1_fill
    c_p_name.border = header_border

    c_p_pos = ws.cell(row=current_row, column=3, value="Должность")
    c_p_pos.font = th1_font
    c_p_pos.alignment = center_align
    c_p_pos.fill = th1_fill
    c_p_pos.border = header_border

    ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=30)
    c_p_desc = ws.cell(row=current_row, column=4, value="Запланированные периоды отпусков")
    c_p_desc.font = th1_font
    c_p_desc.alignment = center_align
    apply_range_border(current_row, 4, current_row, 30, border=header_border, fill=th1_fill)
    current_row += 1

    # Заполнение строк периодов отпусков
    for p_item in periods_table_data:
        p_count = len(p_item["periods"])
        ws.row_dimensions[current_row].height = max(20, 18 * p_count) if p_count > 1 else 20

        # № п/п
        c_num = ws.cell(row=current_row, column=1, value=p_item["idx"])
        c_num.font = data_font
        c_num.alignment = center_align
        c_num.border = thin_border

        # Сотрудник (ФИО)
        c_name = ws.cell(row=current_row, column=2, value=p_item["name"])
        c_name.font = bold_data_font
        c_name.alignment = left_align
        c_name.border = thin_border

        # Должность
        c_pos = ws.cell(row=current_row, column=3, value=p_item["pos"])
        c_pos.font = data_font
        c_pos.alignment = left_align
        c_pos.border = thin_border

        # Периоды отпусков (колонки 4..30)
        ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=30)
        desc_val = ",  ".join(p_item["periods"]) if p_item["periods"] else "—"
        c_desc = ws.cell(row=current_row, column=4, value=desc_val)
        c_desc.font = data_font
        c_desc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        apply_range_border(current_row, 4, current_row, 30, border=thin_border)

        current_row += 1

    # 6. Ширина колонок
    col_widths = {
        1: 6,   # № п/п
        2: 32,  # Сотрудник (ФИО)
        3: 28,  # Должность
        4: 12,  # Отпуск (дней)
    }
    for col_c in range(5, 31):
        col_widths[col_c] = 6.8

    for c_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(c_idx)].width = width

    # Закрепление областей: фиксируем первые 4 строки и колонки A-D
    ws.freeze_panes = "E5"

    # Настройки страницы для печати на листе А4 в альбомной ориентации
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = '3:4'
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


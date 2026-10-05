from __future__ import annotations

import base64
import datetime as dt
import re
from pathlib import Path

# Константы и методы хранилища
from constants import DB_LOCK, ROOT
from storage import connect, load_archive_rows

# Реэкспорт функций работы с Excel для обратной совместимости
from excel import (
    archive_excel_export_bytes,
    archive_excel_template_bytes,
    build_archive_export_rows,
    build_archive_workbook,
    excel_cell_text,
    excel_num_text,
    format_excel_export_date,
    import_archive_excel_bytes,
    normalize_excel_header,
    parse_excel_date,
    require_openpyxl,
)

# Реэкспорт функций мобильной синхронизации для обратной совместимости
from mobile_sync import (
    import_phone_measurement_payload,
    import_phone_payload,
    import_phone_reference_payload,
    parse_phone_json_payload,
    phone_archive_export_payload,
    phone_export_payload,
    phone_reference_export_payload,
)


def build_schedule_eml_bytes(filter_choice: str = "all") -> bytes:
    """Генерация файла черновика письма .eml с графиком замеров колесных пар."""
    year = dt.date.today().year
    archive_rows = load_archive_rows()

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()

        inv_rows = cur.execute(
            "SELECT ser, num FROM inventory WHERE TRIM(COALESCE(num, '')) <> '' AND COALESCE(deleted_at, 0) = 0"
        ).fetchall()
        inventory_map = {}
        for r in inv_rows:
            num = str(r["num"]).strip()
            ser = str(r["ser"]).strip().upper()
            inventory_map[num] = ser

        def normalize_series(s):
            return re.sub(r'[^a-zA-Z0-9а-яА-Я]', '', s).strip().upper()

        def unit_key_from_cells(s, n):
            series = normalize_series(s)
            if not series:
                series = 'ТЭМ2УМ'
            num = str(n or '').strip()
            if not num:
                return ''
            return f"{series} №{num}"

        repairs_data = cur.execute(
            "SELECT m, r, c, v FROM repairs WHERE y=? AND t='plan' ORDER BY m, r, c",
            (year,)
        ).fetchall()

        month_rows = {}
        for row in repairs_data:
            m = str(row["m"])
            r = int(row["r"])
            c = int(row["c"])
            v = str(row["v"])
            if m not in month_rows:
                month_rows[m] = {}
            if r not in month_rows[m]:
                month_rows[m][r] = {"cells": [""] * 35, "excluded": False}
            if c == -1:
                month_rows[m][r]["excluded"] = True
            elif 0 <= c <= 2:
                month_rows[m][r]["cells"][c] = v
            elif 3 <= c <= 33:
                month_rows[m][r]["cells"][c + 1] = v

        MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
        month_num_map = {m: i + 1 for i, m in enumerate(MONTHS_RU)}

        units = {}
        excluded_units = set()
        for m_name, rows_dict in month_rows.items():
            m_num = month_num_map.get(m_name, 1)
            for r_idx, row_info in rows_dict.items():
                cells = row_info["cells"]
                s_val = cells[1]
                n_val = cells[2]
                unit_key = unit_key_from_cells(s_val, n_val)
                if not unit_key:
                    continue
                if row_info["excluded"]:
                    excluded_units.add(unit_key)
                if unit_key not in units:
                    units[unit_key] = {"series": s_val or "ТЭМ-2УМ", "number": n_val, "repairs": []}
                
                for col in range(4, 35):
                    cell_val = cells[col]
                    if cell_val:
                        repair_type = cell_val.strip().upper()
                        if repair_type in ('ТО2', 'ТО3', 'ТР1', 'ТР', 'ТР2', 'ТР3', 'СР', 'КР', 'TO2', 'TO3'):
                            day = col - 3
                            try:
                                candidate_date = dt.date(year, m_num, day)
                                units[unit_key]["repairs"].append({
                                    "date": candidate_date,
                                    "type": repair_type
                                })
                            except ValueError:
                                pass

        for ex in excluded_units:
            if ex in units:
                del units[ex]

        # Последние замеры КП
        latest_by_unit = {}
        for row in archive_rows:
            m_date = row.get("measurement_date")
            if not m_date:
                continue
            loco = str(row.get("locomotive") or "").strip()
            if not loco:
                continue
            ser = inventory_map.get(loco, "ТЭМ-2УМ")
            u_key = unit_key_from_cells(ser, loco)
            if not u_key:
                continue
            try:
                t = dt.date.fromisoformat(m_date)
                if u_key not in latest_by_unit or t > latest_by_unit[u_key]["date"]:
                    latest_by_unit[u_key] = {"date": t, "date_str": m_date}
            except Exception:
                pass

        KP_RECHECK_DAYS = 30
        today = dt.date.today()
        best_by_unit = {}

        for u_key, u_data in units.items():
            last_meas = latest_by_unit.get(u_key)
            last_date_str = last_meas["date_str"] if last_meas else "Нет данных"
            limit_date = (last_meas["date"] + dt.timedelta(days=KP_RECHECK_DAYS)) if last_meas else None
            
            best_repair = None
            for r in u_data["repairs"]:
                r_date = r["date"]
                if last_meas:
                    if last_meas["date"] < r_date <= limit_date:
                        if not best_repair or r_date > best_repair["date"]:
                            best_repair = r
                else:
                    if r_date >= today:
                        if not best_repair or r_date < best_repair["date"]:
                            best_repair = r
            
            best_by_unit[u_key] = {
                "series": u_data["series"],
                "number": u_data["number"],
                "last_date_str": last_date_str,
                "limit_date": limit_date,
                "best_repair": best_repair
            }

        choices_order = [str(r["num"]).strip() for r in inv_rows]
        loco_order_map = {num: idx for idx, num in enumerate(choices_order)}

        table_rows = list(best_by_unit.values())

        if filter_choice == "tem":
            table_rows = [r for r in table_rows if "ТЭМ" in r["series"].upper() or "TEM" in r["series"].upper()]
        elif filter_choice == "pe2m":
            table_rows = [r for r in table_rows if "ПЭ" in r["series"].upper() or "PE" in r["series"].upper()]

        table_rows.sort(key=lambda r: loco_order_map.get(r["number"], 9999))

        rows_html = []
        for r in table_rows:
            limit_str = r["limit_date"].strftime("%d.%m.%Y") if r["limit_date"] else "-"
            last_str = r["last_date_str"]
            if last_str != "Нет данных" and "-" in last_str:
                parts = last_str.split("-")
                if len(parts) == 3:
                    last_str = f"{parts[2]}.{parts[1]}.{parts[0]}"
            
            is_overdue = r["limit_date"] < today if r["limit_date"] else False
            
            if r["best_repair"]:
                best_str = f"{r['best_repair']['date'].strftime('%d.%m.%Y')} ({r['best_repair']['type']})"
            else:
                best_str = "<span style='color:red;'>Нет подходящего ремонта</span>"

            tr_style = "background-color:#ffebee;" if is_overdue else ""
            limit_style = "color:red; font-weight:bold;" if is_overdue else ""

            rows_html.append(f"""
            <tr style='{tr_style}'>
                <td style='border:1px solid #ccc; padding:6px 10px; text-align:center;'>{r['series']}</td>
                <td style='border:1px solid #ccc; padding:6px 10px; text-align:center; font-weight:bold;'>{r['number']}</td>
                <td style='border:1px solid #ccc; padding:6px 10px; text-align:center;'>{last_str}</td>
                <td style='border:1px solid #ccc; padding:6px 10px; text-align:center; {limit_style}'>{limit_str}</td>
                <td style='border:1px solid #ccc; padding:6px 10px; text-align:center;'>{best_str}</td>
            </tr>
            """)

    html_body = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 800px; margin-top: 12px; }}
        th {{ background-color: #276ef1; color: white; border: 1px solid #ccc; padding: 8px 10px; text-align: center; }}
        td {{ border: 1px solid #ccc; padding: 6px 10px; }}
    </style>
    </head>
    <body>
        <h2>График проведения замеров колесных пар локомотивов</h2>
        <p>Сформировано автоматически на основании актуального графика ППР и базы замеров КП.</p>
        <table>
            <thead>
                <tr>
                    <th>Серия</th>
                    <th>Номер</th>
                    <th>Последний замер</th>
                    <th>Крайний срок</th>
                    <th>Следующий по плану</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows_html)}
            </tbody>
        </table>
        <br>
        <p>Убедительная просьба придерживаться данного графика и ставить локомотивы в депо для проведения замеров.</p>
    </body>
    </html>
    """

    encoded_subject = base64.b64encode("График замеров колесных пар локомотивов".encode('utf-8')).decode('utf-8')
    mime_subject = f"=?utf-8?B?{encoded_subject}?="
    
    eml_headers = [
        "MIME-Version: 1.0",
        "To: TerentevPS@kolagmk.ru; TeterinEYu@kolagmk.ru; StankevichMM@kolagmk.ru; GundorovAO@kolagmk.ru",
        f"Subject: {mime_subject}",
        "X-Unsent: 1",
        "Content-Type: text/html; charset=utf-8",
        "",
        html_body,
    ]
    eml_data = "\r\n".join(eml_headers)
    return eml_data.encode('utf-8')

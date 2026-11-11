"""
Модуль контроля и отслеживания просрочек по модулям РТПС.
Включает отслеживание:
 1. Просрочки замеров колесных пар (КП) тепловозов (30-дневный межзамерный интервал).
 2. Просрочки периодической поверки приборов безопасности АЛСН (раздел «Список ПБ»).
Подготовлен для дальнейшего расширения новыми категориями контроля.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import re
from pathlib import Path
from rtps_common import connect_sqlite

ROOT = Path(__file__).resolve().parent
DEFAULT_COMMON_DB = ROOT.parent / "base" / "common_database.db"
DEFAULT_ALSN_DB = ROOT.parent / "web_alsn" / "data" / "alsn.db"
DEFAULT_EQUIPMENT_DB = ROOT.parent / "web_equipment" / "data" / "equipment.db"

# Количество дней межзамерного интервала КП для тепловозов
KP_RECHECK_DAYS = 30


def is_diesel_locomotive(ser: str) -> bool:
    """
    Проверяет, относится ли локомотив к тепловозам (маневровые тепловозы ТЭМ и др.).
    Тяговые агрегаты (серии ПЭ-2М / PE-2M) тепловозами не являются и не учитываются при контроле замеров КП.
    """
    s = str(ser or "").strip().upper()
    if "ПЭ" in s or "PE" in s:
        return False
    return True


def parse_alsn_date(date_str: str) -> dt.date | None:
    """Безопасный разбор даты поверки АЛСН из форматов DD.MM.YYYY, YYYY-MM-DD и др."""
    s = str(date_str or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def add_months_to_date(sourcedate: dt.date, months: int) -> dt.date:
    """Прибавление заданного числа месяцев к дате с корректным учетом конца месяца."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def get_end_of_next_month(sourcedate: dt.date) -> dt.date:
    """
    Возвращает последний день следующего календарного месяца.
    Например, для любой даты в ноябре 2026 года вернет 31 декабря 2026 года.
    Это позволяет включить в категорию 'Внимание' как остаток текущего месяца, так и весь следующий месяц.
    """
    if sourcedate.month == 12:
        next_month = 1
        next_year = sourcedate.year + 1
    else:
        next_month = sourcedate.month + 1
        next_year = sourcedate.year
    last_day = calendar.monthrange(next_year, next_month)[1]
    return dt.date(next_year, next_month, last_day)


def get_overdue_summary(
    common_db_path: Path | None = None,
    alsn_db_path: Path | None = None,
    equipment_db_path: Path | None = None,
) -> dict:
    """
    Формирует сводку по всем видам просрочек системы РТПС.
    Возвращает словарь с общим количеством просрочек и детализацией по категориям:
      - Замеры колесных пар (КП)
      - Приборы безопасности АЛСН
      - Оборудование и инструмент (домкраты, электроинструмент, стропы и др.)
    """
    today = dt.date.today()
    categories = []

    c_db = common_db_path or DEFAULT_COMMON_DB
    a_db = alsn_db_path or DEFAULT_ALSN_DB
    e_db = equipment_db_path or DEFAULT_EQUIPMENT_DB

    # 1. Просрочки замеров колесных пар (КП) тепловозов
    kp_category = _check_kp_overdues(c_db, today)
    categories.append(kp_category)

    # 2. Просрочки поверки приборов безопасности АЛСН
    alsn_category = _check_alsn_overdues(a_db, today)
    categories.append(alsn_category)

    # 3. Просрочки проверок и испытаний оборудования и инструмента
    equipment_category = _check_equipment_overdues(e_db, today)
    categories.append(equipment_category)

    # Подсчет общего числа просрочек по всем категориям
    total_overdue = sum(cat.get("count", 0) for cat in categories)
    total_upcoming = sum(cat.get("upcoming_count", 0) for cat in categories)

    return {
        "today": today.isoformat(),
        "today_str": today.strftime("%d.%m.%Y"),
        "total_overdue": total_overdue,
        "has_overdue": total_overdue > 0,
        "total_upcoming": total_upcoming,
        "has_upcoming": total_upcoming > 0,
        "categories": categories,
    }


def _check_kp_overdues(db_path: Path, today: dt.date) -> dict:
    """
    Проверяет просрочки и приближающиеся сроки замеров колесных пар по всем активным локомотивам.
    Крайний срок = дата последнего замера + 30 дней.
    Если крайний срок меньше сегодняшнего числа — замер считается просроченным.
    Если крайний срок наступает в текущем или следующем календарном месяце — замер считается приближающимся.
    """
    overdue_items = []
    upcoming_items = []
    no_data_items = []
    up_to_date_items = []

    if not db_path.exists():
        return {
            "id": "kp",
            "title": "Замеры колесных пар тепловозов",
            "count": 0,
            "upcoming_count": 0,
            "unit_label": "тепловозов",
            "items": [],
            "upcoming_items": [],
            "no_data_items": [],
            "up_to_date_items": [],
        }

    try:
        with connect_sqlite(db_path) as conn:
            conn.row_factory = None
            cur = conn.cursor()

            # Убедимся в наличии индекса для быстродействия запросов к архиву
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_archive_loco_date ON archive_data (locomotive, measurement_date)"
            )

            # Получаем список активных локомотивов из инвентарной таблицы
            inv_rows = cur.execute(
                """
                SELECT ser, num, COALESCE(sort_order, 0) as s_ord
                FROM inventory
                WHERE TRIM(COALESCE(num, '')) <> '' AND COALESCE(deleted_at, 0) = 0
                ORDER BY COALESCE(sort_order, 0) ASC, rowid ASC
                """
            ).fetchall()

            # Получаем даты последних замеров из архива и текущих несохраненных замеров
            cur.execute(
                """
                SELECT locomotive, MAX(measurement_date) as last_date
                FROM (
                    SELECT locomotive, measurement_date 
                    FROM archive_data 
                    WHERE measurement_date IS NOT NULL AND measurement_date <> ''
                    UNION ALL
                    SELECT locomotive, measurement_date 
                    FROM input_meta 
                    WHERE measurement_date IS NOT NULL AND measurement_date <> ''
                )
                GROUP BY locomotive
                """
            )
            dates_dict = dict(cur.fetchall())

            for row in inv_rows:
                ser = str(row[0] or "").strip()
                num = str(row[1] or "").strip()
                if not num:
                    continue

                # В контроль просрочки замеров КП попадают только тепловозы (ПЭ-2М исключаются)
                if not is_diesel_locomotive(ser):
                    continue

                full_title = f"{ser} №{num}" if ser else f"Тепловоз №{num}"
                last_date_str = dates_dict.get(num)

                if last_date_str:
                    try:
                        last_date = dt.date.fromisoformat(str(last_date_str).strip()[:10])
                        limit_date = last_date + dt.timedelta(days=KP_RECHECK_DAYS)
                        is_overdue = limit_date < today
                        days_diff = (today - limit_date).days
                        days_remaining = (limit_date - today).days if not is_overdue else 0
                        end_of_next_month = get_end_of_next_month(today)
                        is_upcoming = not is_overdue and limit_date <= end_of_next_month

                        item = {
                            "series": ser,
                            "number": num,
                            "full_title": full_title,
                            "last_date": last_date.isoformat(),
                            "last_date_str": last_date.strftime("%d.%m.%Y"),
                            "limit_date": limit_date.isoformat(),
                            "limit_date_str": limit_date.strftime("%d.%m.%Y"),
                            "days_overdue": days_diff if is_overdue else 0,
                            "days_remaining": days_remaining,
                            "is_overdue": is_overdue,
                            "is_upcoming": is_upcoming,
                            "url": f"/zamer-kp?locomotive={num}",
                        }

                        if is_overdue:
                            overdue_items.append(item)
                        else:
                            if is_upcoming:
                                upcoming_items.append(item)
                            up_to_date_items.append(item)
                    except Exception:
                        # В случае ошибки парсинга даты добавляем в список без данных
                        no_data_items.append({
                            "series": ser,
                            "number": num,
                            "full_title": full_title,
                            "url": f"/zamer-kp?locomotive={num}",
                        })
                else:
                    no_data_items.append({
                        "series": ser,
                        "number": num,
                        "full_title": full_title,
                        "url": f"/zamer-kp?locomotive={num}",
                    })

        # Сортируем просроченные локомотивы по убыванию дней просрочки (наиболее критичные вверху)
        overdue_items.sort(key=lambda x: x["days_overdue"], reverse=True)
        # Сортируем приближающиеся сроки по возрастанию оставшихся дней (скоро наступающие вверху)
        upcoming_items.sort(key=lambda x: x["days_remaining"])

    except Exception as exc:
        print(f"[overdue] Ошибка при проверке замеров КП: {exc}")

    return {
        "id": "kp",
        "title": "Замеры колесных пар тепловозов",
        "count": len(overdue_items),
        "upcoming_count": len(upcoming_items),
        "unit_label": "тепловозов",
        "items": overdue_items,
        "upcoming_items": upcoming_items,
        "no_data_items": no_data_items,
        "up_to_date_items": up_to_date_items,
    }


def _check_alsn_overdues(db_path: Path, today: dt.date) -> dict:
    """
    Проверяет просрочки и приближающиеся сроки поверки приборов безопасности АЛСН из базы данных alsn.db.
    Прибор считается просроченным, если следующая дата поверки меньше сегодняшней даты.
    Прибор считается приближающимся к просрочке, если срок поверки наступает в текущем или следующем календарном месяце.
    """
    overdue_items = []
    upcoming_items = []
    no_data_items = []
    up_to_date_items = []
    repair_items = []

    if not db_path.exists():
        return {
            "id": "alsn",
            "title": "Приборы безопасности АЛСН",
            "count": 0,
            "upcoming_count": 0,
            "unit_label": "приборов",
            "items": [],
            "upcoming_items": [],
            "no_data_items": [],
            "up_to_date_items": [],
            "repair_items": [],
        }

    try:
        with connect_sqlite(db_path) as conn:
            conn.row_factory = None
            cur = conn.cursor()

            # Индекс принадлежности приборов локомотивам для определения местонахождения
            loco_map = {}
            try:
                for row in cur.execute("SELECT series, number, devices_json FROM locomotives").fetchall():
                    ser = str(row[0] or "").strip()
                    num = str(row[1] or "").strip()
                    loco_label = f"{ser} №{num}".strip() if ser and num else (num or ser)
                    try:
                        devs = json.loads(row[2] or "[]")
                        for d in devs:
                            if isinstance(d, dict):
                                dt_type = str(d.get("type") or "").strip().lower()
                                dt_num = str(d.get("number") or "").strip().lower()
                                if dt_num:
                                    c_num = dt_num.lstrip("0") or "0"
                                    if dt_type:
                                        loco_map[(dt_type, dt_num)] = loco_label
                                        loco_map[(dt_type, c_num)] = loco_label
                                    loco_map[("*", dt_num)] = loco_label
                                    loco_map[("*", c_num)] = loco_label
                    except Exception:
                        pass
            except Exception:
                pass

            # Проверяем структуру таблицы warehouse и наличие столбца in_repair
            cur = conn.cursor()
            wh_cols = [r[1] for r in cur.execute("PRAGMA table_info(warehouse)").fetchall()]
            has_in_repair = "in_repair" in wh_cols
            cols_query = "type, number, verification_date, periodicity, next_verification_date, location"
            if has_in_repair:
                cols_query += ", in_repair"

            # Выбираем приборы безопасности со склада
            wh_rows = cur.execute(
                f"""
                SELECT {cols_query}
                FROM warehouse
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()

            repair_items = []

            for row in wh_rows:
                dev_type = str(row[0] or "").strip()
                dev_num = str(row[1] or "").strip()
                # Пропускаем пустые строки
                if not dev_type and not dev_num:
                    continue

                # Определение текущего местонахождения (на локомотиве или в депо)
                dt_l = dev_type.lower()
                dn_l = dev_num.lower()
                cn_l = dn_l.lstrip("0") or "0"
                loc = (
                    loco_map.get((dt_l, dn_l))
                    or loco_map.get((dt_l, cn_l))
                    or loco_map.get(("*", dn_l))
                    or loco_map.get(("*", cn_l))
                    or str(row[5] or "").strip()
                    or "Депо"
                )

                # Проверка признака нахождения в ремонте
                raw_repair = row[6] if (has_in_repair and len(row) > 6) else 0
                in_repair = raw_repair in (1, "1", True, "true", "True")

                full_title = f"{dev_type} №{dev_num}".strip() if dev_type and dev_num else (dev_num or dev_type)

                # Приборы, находящиеся в ремонте, не учитываются в просрочках
                if in_repair:
                    repair_items.append({
                        "type": dev_type,
                        "number": dev_num,
                        "full_title": full_title,
                        "location": loc,
                        "in_repair": True,
                        "url": "/alsn",
                    })
                    continue

                ver_date_str = str(row[2] or "").strip()
                periodicity_str = str(row[3] or "").strip()
                next_date_str = str(row[4] or "").strip()

                ver_date = parse_alsn_date(ver_date_str)
                next_date = parse_alsn_date(next_date_str)

                # Если следующая дата поверки не указана, но есть дата поверки и периодичность — вычисляем
                if not next_date and ver_date and periodicity_str:
                    try:
                        p_months = int(periodicity_str)
                        if p_months > 0:
                            next_date = add_months_to_date(ver_date, p_months)
                    except Exception:
                        pass

                full_title = f"{dev_type} №{dev_num}".strip() if dev_type and dev_num else (dev_num or dev_type)

                if next_date:
                    is_overdue = next_date < today
                    days_diff = (today - next_date).days
                    days_remaining = (next_date - today).days if not is_overdue else 0
                    end_of_next_month = get_end_of_next_month(today)
                    is_upcoming = not is_overdue and next_date <= end_of_next_month

                    item = {
                        "type": dev_type,
                        "number": dev_num,
                        "full_title": full_title,
                        "location": loc,
                        "verification_date": ver_date.isoformat() if ver_date else "",
                        "verification_date_str": ver_date.strftime("%d.%m.%Y") if ver_date else ver_date_str,
                        "limit_date": next_date.isoformat(),
                        "limit_date_str": next_date.strftime("%d.%m.%Y"),
                        "days_overdue": days_diff if is_overdue else 0,
                        "days_remaining": days_remaining,
                        "is_overdue": is_overdue,
                        "is_upcoming": is_upcoming,
                        "url": "/alsn",
                    }

                    if is_overdue:
                        overdue_items.append(item)
                    else:
                        if is_upcoming:
                            upcoming_items.append(item)
                        up_to_date_items.append(item)
                else:
                    no_data_items.append({
                        "type": dev_type,
                        "number": dev_num,
                        "full_title": full_title,
                        "location": loc,
                        "url": "/alsn",
                    })

        # Сортируем просроченные приборы по убыванию дней просрочки (наиболее критичные вверху)
        overdue_items.sort(key=lambda x: x["days_overdue"], reverse=True)
        # Сортируем приближающиеся сроки по возрастанию оставшихся дней (скоро наступающие вверху)
        upcoming_items.sort(key=lambda x: x["days_remaining"])

    except Exception as exc:
        print(f"[overdue] Ошибка при проверке приборов АЛСН: {exc}")

    return {
        "id": "alsn",
        "title": "Приборы безопасности АЛСН",
        "count": len(overdue_items),
        "upcoming_count": len(upcoming_items),
        "unit_label": "приборов",
        "items": overdue_items,
        "upcoming_items": upcoming_items,
        "no_data_items": no_data_items,
        "up_to_date_items": up_to_date_items,
        "repair_items": repair_items,
    }


def _check_equipment_overdues(db_path: Path, today: dt.date) -> dict:
    """
    Проверяет просрочки и приближающиеся сроки проверок и испытаний оборудования и инструмента из equipment.db.
    Оборудование считается просроченным, если следующая дата проверки меньше сегодняшней даты.
    Оборудование считается приближающимся к просрочке, если срок проверки наступает в текущем или следующем календарном месяце.
    Оборудование с отметкой 'В ремонте' исключается из подсчета просрочек.
    """
    overdue_items = []
    upcoming_items = []
    no_data_items = []
    up_to_date_items = []
    repair_items = []

    if not db_path.exists():
        return {
            "id": "equipment",
            "title": "Оборудование и инструмент",
            "count": 0,
            "upcoming_count": 0,
            "unit_label": "единиц",
            "items": [],
            "upcoming_items": [],
            "no_data_items": [],
            "up_to_date_items": [],
            "repair_items": [],
        }

    try:
        with connect_sqlite(db_path) as conn:
            conn.row_factory = None
            cur = conn.cursor()

            # Получаем все единицы оборудования из базы
            rows = cur.execute(
                """
                SELECT category, name, inv_number, location, responsible,
                       test_type, periodicity, last_test_date, next_test_date,
                       in_repair, protocol_num, notes
                FROM equipment
                ORDER BY sort_order ASC, id ASC
                """
            ).fetchall()

            for row in rows:
                cat = str(row[0] or "Прочее").strip()
                name = str(row[1] or "").strip()
                inv_num = str(row[2] or "").strip()
                location = str(row[3] or "").strip() or "Участок РТПС"
                responsible = str(row[4] or "").strip()
                test_type = str(row[5] or "").strip()
                periodicity_str = str(row[6] or "").strip()
                last_date_str = str(row[7] or "").strip()
                next_date_str = str(row[8] or "").strip()
                raw_repair = row[9]
                in_repair = raw_repair in (1, "1", True, "true", "True")
                protocol_num = str(row[10] or "").strip()
                notes = str(row[11] or "").strip()

                if not name and not inv_num:
                    continue

                full_title = f"{name} (инв. №{inv_num})" if inv_num else name

                # Оборудование в ремонте не учитывается в просрочках
                if in_repair:
                    repair_items.append({
                        "category": cat,
                        "name": name,
                        "number": inv_num,
                        "full_title": full_title,
                        "location": location,
                        "responsible": responsible,
                        "in_repair": True,
                        "url": "/equipment",
                    })
                    continue

                last_date = parse_alsn_date(last_date_str)
                next_date = parse_alsn_date(next_date_str)

                # Если следующая дата проверки не указана явно, но есть последняя дата и периодичность
                if not next_date and last_date and periodicity_str:
                    try:
                        p_months = int(periodicity_str)
                        if p_months > 0:
                            next_date = add_months_to_date(last_date, p_months)
                    except Exception:
                        pass

                if next_date:
                    is_overdue = next_date < today
                    days_diff = (today - next_date).days
                    days_remaining = (next_date - today).days if not is_overdue else 0
                    end_of_next_month = get_end_of_next_month(today)
                    is_upcoming = not is_overdue and next_date <= end_of_next_month

                    item = {
                        "category": cat,
                        "name": name,
                        "number": inv_num,
                        "full_title": full_title,
                        "location": location,
                        "responsible": responsible,
                        "test_type": test_type,
                        "verification_date": last_date.isoformat() if last_date else "",
                        "verification_date_str": last_date.strftime("%d.%m.%Y") if last_date else last_date_str,
                        "limit_date": next_date.isoformat(),
                        "limit_date_str": next_date.strftime("%d.%m.%Y"),
                        "days_overdue": days_diff if is_overdue else 0,
                        "days_remaining": days_remaining,
                        "is_overdue": is_overdue,
                        "is_upcoming": is_upcoming,
                        "protocol_num": protocol_num,
                        "notes": notes,
                        "url": "/equipment",
                    }

                    if is_overdue:
                        overdue_items.append(item)
                    else:
                        if is_upcoming:
                            upcoming_items.append(item)
                        up_to_date_items.append(item)
                else:
                    no_data_items.append({
                        "category": cat,
                        "name": name,
                        "number": inv_num,
                        "full_title": full_title,
                        "location": location,
                        "url": "/equipment",
                    })

        # Сортируем просроченное оборудование по убыванию дней просрочки
        overdue_items.sort(key=lambda x: x["days_overdue"], reverse=True)
        # Сортируем приближающиеся сроки по возрастанию оставшихся дней
        upcoming_items.sort(key=lambda x: x["days_remaining"])

    except Exception as exc:
        print(f"[overdue] Ошибка при проверке оборудования: {exc}")

    return {
        "id": "equipment",
        "title": "Оборудование и инструмент",
        "count": len(overdue_items),
        "upcoming_count": len(upcoming_items),
        "unit_label": "единиц",
        "items": overdue_items,
        "upcoming_items": upcoming_items,
        "no_data_items": no_data_items,
        "up_to_date_items": up_to_date_items,
        "repair_items": repair_items,
    }



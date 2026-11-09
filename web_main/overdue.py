"""
Модуль контроля и отслеживания просрочек по модулям РТПС.
Включает отслеживание просрочки замеров колесных пар (КП) и подготовлен для
дальнейшего расширения другими видами контроля (обучение, АЛСН, ТО и т.д.).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from rtps_common import connect_sqlite

# Количество дней межзамерного интервала КП
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


def get_overdue_summary(common_db_path: Path) -> dict:
    """
    Формирует сводку по всем видам просрочек системы РТПС.
    Возвращает словарь с общим количеством просрочек и детализацией по категориям.
    """
    today = dt.date.today()
    categories = []

    # 1. Просрочки замеров колесных пар (КП)
    kp_category = _check_kp_overdues(common_db_path, today)
    categories.append(kp_category)

    # Подсчет общего числа просрочек по всем категориям
    total_overdue = sum(cat.get("count", 0) for cat in categories)

    return {
        "today": today.isoformat(),
        "today_str": today.strftime("%d.%m.%Y"),
        "total_overdue": total_overdue,
        "has_overdue": total_overdue > 0,
        "categories": categories,
    }


def _check_kp_overdues(db_path: Path, today: dt.date) -> dict:
    """
    Проверяет просрочки замеров колесных пар по всем активным локомотивам.
    Крайний срок = дата последнего замера + 30 дней.
    Если крайний срок меньше сегодняшнего числа — замер считается просроченным.
    """
    overdue_items = []
    no_data_items = []
    up_to_date_items = []

    if not db_path.exists():
        return {
            "id": "kp",
            "title": "Замеры колесных пар тепловозов",
            "count": 0,
            "unit_label": "тепловозов",
            "items": [],
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

                        item = {
                            "series": ser,
                            "number": num,
                            "full_title": full_title,
                            "last_date": last_date.isoformat(),
                            "last_date_str": last_date.strftime("%d.%m.%Y"),
                            "limit_date": limit_date.isoformat(),
                            "limit_date_str": limit_date.strftime("%d.%m.%Y"),
                            "days_overdue": days_diff if is_overdue else 0,
                            "days_remaining": (limit_date - today).days if not is_overdue else 0,
                            "is_overdue": is_overdue,
                            "url": f"/zamer-kp?locomotive={num}",
                        }

                        if is_overdue:
                            overdue_items.append(item)
                        else:
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

    except Exception as exc:
        print(f"[overdue] Ошибка при проверке замеров КП: {exc}")

    return {
        "id": "kp",
        "title": "Замеры колесных пар тепловозов",
        "count": len(overdue_items),
        "unit_label": "тепловозов",
        "items": overdue_items,
        "no_data_items": no_data_items,
        "up_to_date_items": up_to_date_items,
    }


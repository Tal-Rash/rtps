from __future__ import annotations

import datetime as dt
from constants import (
    DEFAULT_REPAIR_OPTIONS,
    INPUT_ROWS,
    WEAR_TREND_METRICS,
)


def text(value: object | None) -> str:
    # Безопасное приведение значения к строке
    return "" if value is None else str(value)


def normalize_repair_type(value: object | None) -> str:
    # Нормализация наименования вида ремонта
    return text(value).strip().upper().replace(" ", "").replace("-", "")


def normalize_text(value: str) -> str:
    # Приведение текста к нижнему регистру и замена буквы 'ё'
    text_value = text(value).strip().lower()
    text_value = text_value.replace("ё", "е")
    return text_value


def parse_excel_int(value: object | None) -> int | None:
    # Парсинг целочисленного значения из ячейки Excel
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raw = text(value).strip().replace(",", ".")
    if not raw:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def parse_float_value(value: object | None) -> float | None:
    # Парсинг вещественного числа с поддержкой запятой
    raw = text(value).strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def locomotive_axis_count(series: str, locomotive: str = "") -> int:
    # Определение количества осей (колесных пар) по серии и номеру локомотива
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return 12
    if "тэм" in normalized or "tem" in normalized:
        return 6
    return 12


def default_section_count(axis_count: int) -> int:
    # Определение количества секций локомотива по количеству осей
    return 1 if int(axis_count or 0) <= 6 else 3


def allowed_repairs(series: str, locomotive: str = "") -> list[str]:
    # Список допустимых видов ремонта для типа тягового подвижного состава
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return DEFAULT_REPAIR_OPTIONS["pe"]
    return DEFAULT_REPAIR_OPTIONS["tem"]


def empty_measurements(axis_count: int, section_count: int) -> list[dict]:
    # Создание пустого бланка измерений для колесных пар
    items: list[dict] = []
    pairs_per_section = max(1, axis_count // max(1, section_count))
    for r in range(1, INPUT_ROWS + 1):
        if r <= axis_count:
            sec = str(min(section_count, (r - 1) // pairs_per_section + 1))
            pair = str(r)
        else:
            sec = ""
            pair = ""
        items.append({
            "section": sec,
            "pair": pair,
            "values": [""] * 10,
        })
    return items


def row_to_index(r: int) -> int:
    # Преобразование индекса строки в номер колесной пары
    return max(0, r - 2)


def format_trend_number(value: float | int | None) -> str:
    # Форматирование числового значения тренда для отображения в интерфейсе
    if value is None:
        return ""
    try:
        number = float(value)
    except Exception:
        return text(value).strip()
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return str(round(number, 2)).rstrip("0").rstrip(".").replace(".", ",")


def format_trend_date(value: str) -> str:
    # Преобразование даты из формата YYYY-MM-DD в DD.MM.YYYY
    value = text(value).strip()
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        parts = value.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return value


def _wear_trend_compare(metric_key: str, latest: float | None, previous: float | None) -> tuple[str, float | None]:
    # Сравнение текущего и предыдущего значения износа с определением направленности тренда
    if latest is None or previous is None:
        return "none", None
    delta = latest - previous
    if abs(delta) < 1e-9:
        return "stable", delta
    metric = next((item for item in WEAR_TREND_METRICS if item["key"] == metric_key), None)
    worse_when = text(metric.get("worse_when") if metric else "").strip().lower()
    is_worse = (delta > 0 and worse_when == "higher") or (delta < 0 and worse_when == "lower")
    is_better = (delta < 0 and worse_when == "higher") or (delta > 0 and worse_when == "lower")
    if is_worse:
        return "worse", delta
    if is_better:
        return "better", delta
    return "stable", delta


def _wear_pair_number_from_row(values: list[str], source_row: int) -> int:
    # Извлечение порядкового номера колесной пары из строки данных
    raw = text(values[1] if len(values) > 1 else "").strip()
    try:
        pair_number = int(raw)
        if pair_number > 0:
            return pair_number
    except Exception:
        pass
    if source_row >= 2:
        return max(1, source_row - 1)
    return 1


def _wear_session_metrics(values: list[str]) -> dict[str, dict[str, float | None]]:
    # Выделение парных значений метрик из строки замера
    def value_at(col: int) -> float | None:
        if col >= len(values):
            return None
        return parse_float_value(values[col])

    return {
        "prokat": {"left": value_at(2), "right": value_at(3)},
        "greben": {"left": value_at(4), "right": value_at(5)},
        "krut": {"left": value_at(6), "right": value_at(7)},
        "bandage_thickness": {"left": value_at(8), "right": value_at(9)},
        "diameter": {"left": value_at(10), "right": value_at(11)},
    }


def compute_wear_analysis(
    selected_locomotive: str,
    series: str,
    wheel_pair_count: int,
    archive_rows: list[dict | tuple | object],
    date_from: str = "",
    date_to: str = "",
) -> dict:
    # Построение расчетных показателей и точек графиков трендов износа колесных пар
    sessions: dict[tuple[str, str, int], dict[str, object]] = {}
    for row in archive_rows:
        measurement_date = text(row["measurement_date"]).strip()
        repair_type = normalize_repair_type(row["repair_type"])
        source_row = int(row["r"] or 0)
        key = (measurement_date, repair_type, source_row)
        session = sessions.setdefault(
            key,
            {
                "year": int(row["y"] or 0),
                "measurement_date": measurement_date,
                "repair_type": repair_type,
                "source_row": source_row,
                "values": [""] * 12,
            },
        )
        values = session["values"]
        if isinstance(values, list):
            col = int(row["c"] or 0)
            if 0 <= col < len(values):
                values[col] = text(row["v"]).strip()

    sessions_by_pair: dict[int, list[dict[str, object]]] = {pair: [] for pair in range(1, wheel_pair_count + 1)}
    for session in sessions.values():
        values = session.get("values")
        if not isinstance(values, list):
            continue
        pair_number = _wear_pair_number_from_row(values, int(session.get("source_row") or 0))
        pair_number = max(1, min(wheel_pair_count, pair_number))
        metrics = _wear_session_metrics(values)
        sessions_by_pair.setdefault(pair_number, []).append(
            {
                "year": int(session.get("year") or 0),
                "measurement_date": text(session.get("measurement_date")).strip(),
                "repair_type": text(session.get("repair_type")).strip(),
                "metrics": metrics,
            }
        )

    chart_pairs: list[dict[str, object]] = []
    for pair_number in range(1, wheel_pair_count + 1):
        points = sessions_by_pair.get(pair_number, [])
        points.sort(
            key=lambda item: (
                text(item.get("measurement_date")).strip(),
                int(item.get("year") or 0),
                text(item.get("repair_type")).strip(),
            )
        )
        chart_pairs.append({
            "wheel_pair": pair_number,
            "points": points,
        })

    result_rows: list[dict] = []
    for pair_number in range(1, wheel_pair_count + 1):
        pair_sessions = sessions_by_pair.get(pair_number, [])
        pair_sessions.sort(
            key=lambda item: (
                text(item.get("measurement_date")).strip(),
                int(item.get("year") or 0),
                text(item.get("repair_type")).strip(),
            )
        )
        metric_payload: dict[str, dict[str, object]] = {}
        worse_count = 0
        better_count = 0
        stable_count = 0
        total_compared = 0

        for metric in WEAR_TREND_METRICS:
            key = metric["key"]
            side_payload: dict[str, dict[str, object]] = {}
            for side in ("left", "right"):
                history: list[float] = []
                for session in pair_sessions:
                    metrics = session.get("metrics")
                    if isinstance(metrics, dict):
                        metric_value = metrics.get(key)
                        if isinstance(metric_value, dict):
                            val = metric_value.get(side)
                            if val is not None:
                                history.append(val)
                if len(history) >= 2:
                    first_value = history[0]
                    latest = history[-1]
                    trend, delta = _wear_trend_compare(key, latest, first_value)
                    total_compared += 1
                    if trend == "worse":
                        worse_count += 1
                    elif trend == "better":
                        better_count += 1
                    elif trend == "stable":
                        stable_count += 1
                else:
                    first_value = history[0] if history else None
                    latest = first_value
                    trend, delta = "none", None
                side_payload[side] = {
                    "latest": latest,
                    "previous": first_value,
                    "delta": delta,
                    "trend": trend,
                }
            metric_payload[key] = {
                "label": metric["label"],
                "left": side_payload["left"],
                "right": side_payload["right"],
            }

        if total_compared <= 0:
            status_key = "none"
            status_label = "Недостаточно данных"
        elif worse_count > better_count:
            status_key = "worse"
            status_label = "Износ растет"
        elif better_count > worse_count:
            status_key = "better"
            status_label = "Износ снижается"
        elif stable_count > 0 and worse_count == 0 and better_count == 0:
            status_key = "stable"
            status_label = "Стабильно"
        else:
            status_key = "mixed"
            status_label = "Смешанный тренд"

        last_session = pair_sessions[-1] if pair_sessions else None
        result_rows.append({
            "wheel_pair": pair_number,
            "session_count": len(pair_sessions),
            "last_measurement_date": text(last_session.get("measurement_date") if last_session else "").strip(),
            "last_repair_type": text(last_session.get("repair_type") if last_session else "").strip(),
            "status_key": status_key,
            "status_label": status_label,
            "metrics": metric_payload,
        })

    return {
        "locomotive": selected_locomotive,
        "series": series,
        "wheel_pair_count": wheel_pair_count,
        "date_from": date_from,
        "date_to": date_to,
        "rows": result_rows,
        "chart": {
            "metrics": [
                {
                    "key": metric["key"],
                    "label": metric["label"],
                }
                for metric in WEAR_TREND_METRICS
            ],
            "pairs": chart_pairs,
        },
    }

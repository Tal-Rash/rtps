from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
import zlib
from http import HTTPStatus

# Импорт констант и функций хранилища
from constants import DB_LOCK
from excel import excel_num_text
from storage import (
    connect,
    default_section_count,
    ensure_import_locomotive,
    load_archive_rows,
    load_effective_kp_values_for_date,
    load_inventory_records,
    locomotive_axis_count,
    normalize_repair_type,
    normalize_text,
    parse_excel_int,
    parse_float_value,
    resolve_archive_diameter_pair,
    series_for_locomotive,
    text,
    upsert_inventory_locomotive,
)


def phone_reference_export_payload() -> dict:
    """Формирование справочника локомотивов и колесных пар для отправки на мобильное устройство."""
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_inventory_records(cur, include_deleted=True)
        kp_rows = cur.execute(
            "SELECT locomotive, r, c, v FROM kp_data WHERE TRIM(COALESCE(locomotive, '')) <> '' ORDER BY locomotive, r, c"
        ).fetchall()

    kp_map: dict[str, dict[int, dict[int, str]]] = {}
    for row in kp_rows:
        locomotive = text(row["locomotive"]).strip()
        kp_map.setdefault(locomotive, {}).setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

    payload_locomotives: list[dict[str, object]] = []
    for locomotive in locomotives:
        number = text(locomotive.get("number")).strip()
        series = text(locomotive.get("series")).strip()
        wheel_pair_count = max(1, locomotive_axis_count(series, number))
        row_map = kp_map.get(number, {})
        wheel_pairs: list[dict[str, object]] = []
        for pair_index in range(wheel_pair_count):
            row = row_map.get(pair_index, {})
            wheel_pairs.append(
                {
                    "number": pair_index + 1,
                    "axisNumber": parse_excel_int(row.get(1, "")) or (pair_index + 1),
                    "diameterLeft": parse_float_value(row.get(2, "")),
                    "diameterRight": parse_float_value(row.get(3, "")),
                }
            )
        payload_locomotives.append(
            {
                "series": series,
                "number": number,
                "wheelPairCount": wheel_pair_count,
                "inventoryNumber": text(locomotive.get("inventoryNumber") or locomotive.get("inv") or ""),
                "invNumber": text(locomotive.get("inventoryNumber") or locomotive.get("inv") or ""),
                "eightDigitNumber": text(locomotive.get("eightDigitNumber") or ""),
                "manufactureYear": text(locomotive.get("manufactureYear") or locomotive.get("manufacture_year") or ""),
                "sortOrder": int(locomotive.get("sortOrder") or 0),
                "updatedAt": int(locomotive.get("updatedAt") or 0),
                "deletedAt": int(locomotive.get("deletedAt") or 0),
                "wheelPairs": wheel_pairs,
            }
        )

    return {
        "formatVersion": 2,
        "exportType": "referenceData",
        "exportedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "locomotives": payload_locomotives,
    }


def phone_archive_export_payload(selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> dict:
    """Формирование архива замеров для выгрузки на мобильное устройство."""
    locomotives_filter = {text(item).strip() for item in selected_locomotives or [] if text(item).strip()}
    date_from = text(date_from).strip()
    date_to = text(date_to).strip()
    query = """
        SELECT y, measurement_date, locomotive, repair_type, r, c, v
        FROM archive_data
        WHERE TRIM(COALESCE(measurement_date, '')) <> ''
    """
    params: list[str] = []
    if locomotives_filter:
        query += f" AND locomotive IN ({','.join('?' for _ in locomotives_filter)})"
        params.extend(sorted(locomotives_filter))
    if date_from:
        query += " AND measurement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND measurement_date <= ?"
        params.append(date_to)
    query += " ORDER BY y, measurement_date, locomotive, repair_type, r, c"

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        rows = cur.execute(query, params).fetchall()
        grouped: dict[tuple[int, str, str, str], dict[int, list[str]]] = {}
        series_cache: dict[str, str] = {}
        kp_cache: dict[tuple[str, str], dict[tuple[int, int], str]] = {}
        for row in rows:
            key = (
                int(row["y"] or 0),
                text(row["measurement_date"]).strip(),
                text(row["locomotive"]).strip(),
                normalize_repair_type(row["repair_type"]),
            )
            grouped.setdefault(key, {})[int(row["r"])] = grouped.setdefault(key, {}).get(int(row["r"]), [""] * 12)
            grouped[key][int(row["r"])][int(row["c"])] = text(row["v"])

        archive_items: list[dict[str, object]] = []
        for (year, measurement_date, locomotive, repair_type), rows_by_r in sorted(grouped.items()):
            series = series_cache.get(locomotive)
            if series is None:
                series = series_for_locomotive(cur, locomotive)
                series_cache[locomotive] = series
            wheel_pair_count = max(1, locomotive_axis_count(series, locomotive))
            wheel_pairs: list[dict[str, object]] = []
            for row_index in sorted(rows_by_r):
                row = rows_by_r[row_index]
                pair_number = parse_excel_int(row[1]) or max(1, row_index - 1)
                left_band, right_band, diameter_left, diameter_right = resolve_archive_diameter_pair(
                    cur,
                    locomotive,
                    measurement_date,
                    pair_number - 1,
                    row,
                    kp_cache,
                )

                wheel_pairs.append(
                    {
                        "number": pair_number,
                        "left": {
                            "flangeThickness": parse_float_value(row[4]),
                            "flangeWear": parse_float_value(row[2]),
                            "flangeSteepness": parse_float_value(row[6]),
                            "bandageThickness": parse_float_value(left_band),
                            "bandageDiameter": parse_float_value(diameter_left),
                        },
                        "right": {
                            "flangeThickness": parse_float_value(row[5]),
                            "flangeWear": parse_float_value(row[3]),
                            "flangeSteepness": parse_float_value(row[7]),
                            "bandageThickness": parse_float_value(right_band),
                            "bandageDiameter": parse_float_value(diameter_right),
                        },
                    }
                )

            archive_items.append(
                {
                    "formatVersion": 1,
                    "createdAt": dt.datetime.now().isoformat(timespec="seconds"),
                    "measurementId": f"{year}:{measurement_date}:{locomotive}:{repair_type}",
                    "locomotive": {
                        "series": series,
                        "number": locomotive,
                        "wheelPairCount": wheel_pair_count,
                        "comment": "",
                        "isNew": False,
                    },
                    "repairType": repair_type,
                    "measurementDate": measurement_date,
                    "wheelPairs": wheel_pairs,
                }
            )

    return {
        "formatVersion": 1,
        "exportType": "archiveData",
        "exportedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "archive": archive_items,
    }


def phone_export_payload(kind: str, selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> dict:
    """Маршрутизация экспорта данных для мобильного устройства (справочник или архив)."""
    kind = text(kind).strip().lower()
    if kind == "reference":
        return phone_reference_export_payload()
    if kind == "archive":
        return phone_archive_export_payload(selected_locomotives, date_from, date_to)
    raise ValueError("Неизвестный тип экспорта.")


def parse_phone_json_payload(raw: bytes) -> object:
    """Декодирование полезной нагрузки от мобильного устройства (поддержка base64, zlib и обычного JSON)."""
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and "payload" in data:
        payload = data.get("payload")
        if isinstance(payload, str):
            return json.loads(payload)
        return payload
    if isinstance(data, str):
        text_data = data.strip()
        if text_data.startswith("{") or text_data.startswith("["):
            try:
                return json.loads(text_data)
            except Exception:
                pass
        try:
            decoded = base64.b64decode(text_data)
            try:
                return json.loads(zlib.decompress(decoded).decode("utf-8"))
            except Exception:
                return json.loads(decoded.decode("utf-8"))
        except Exception:
            return data
    return data


def import_phone_reference_payload(payload: dict) -> dict:
    """Импорт и сохранение справочника локомотивов, полученного с телефона."""
    reference = payload.get("referenceData") if isinstance(payload.get("referenceData"), dict) else payload
    locomotives = reference.get("locomotives") if isinstance(reference, dict) else None
    if not isinstance(locomotives, list):
        return {"error": "Некорректный справочник локомотивов."}, HTTPStatus.BAD_REQUEST

    grouped: dict[str, dict[str, object]] = {}
    for item in locomotives:
        if not isinstance(item, dict):
            continue
        series = text(item.get("series")).strip().upper()
        number = text(item.get("number")).strip()
        if not number:
            continue
        key = f"{series}|{number}"
        candidate = {
            "series": series,
            "number": number,
            "wheelPairCount": parse_excel_int(item.get("wheelPairCount")) or len(item.get("wheelPairs") or []) or locomotive_axis_count(series, number),
            "sortOrder": parse_excel_int(item.get("sortOrder")) or 0,
            "updatedAt": parse_excel_int(item.get("updatedAt")) or 0,
            "deletedAt": parse_excel_int(item.get("deletedAt")) or 0,
            "eightDigitNumber": text(item.get("eightDigitNumber")).strip(),
            "manufactureYear": text(item.get("manufactureYear") or item.get("manufacture_year")).strip(),
            "serviceLife": text(item.get("serviceLife") or item.get("service_life")).strip(),
            "wheelPairs": item.get("wheelPairs") if isinstance(item.get("wheelPairs"), list) else [],
        }
        current = grouped.get(key)
        if current is None or (
            candidate["updatedAt"],
            candidate["deletedAt"],
            candidate["sortOrder"],
        ) > (
            current["updatedAt"],
            current["deletedAt"],
            current["sortOrder"],
        ):
            grouped[key] = candidate

    imported_locomotives = 0
    imported_wheel_pairs = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for item in grouped.values():
            series = text(item["series"]).strip().upper()
            number = text(item["number"]).strip()
            wheel_pair_count = int(item["wheelPairCount"] or 0)
            sort_order = int(item["sortOrder"] or 0)
            updated_at = int(item["updatedAt"] or 0)
            deleted_at = int(item["deletedAt"] or 0)
            eight_digit_number = text(item["eightDigitNumber"]).strip()
            manufacture_year = text(item["manufactureYear"]).strip()
            service_life = text(item["serviceLife"]).strip()
            upsert_inventory_locomotive(
                cur,
                series,
                number,
                "",
                wheel_pair_count=wheel_pair_count,
                eight_digit_number=eight_digit_number,
                manufacture_year=manufacture_year,
                service_life=service_life,
                sort_order=sort_order,
                updated_at=updated_at or None,
                deleted_at=deleted_at,
            )
            if deleted_at <= 0:
                cur.execute("DELETE FROM kp_data WHERE locomotive=?", (number,))
            wheel_pairs = item.get("wheelPairs")
            if not isinstance(wheel_pairs, list) or not wheel_pairs:
                wheel_pairs = [{"number": index + 1, "axisNumber": index + 1} for index in range(max(1, wheel_pair_count))]
            for pair in wheel_pairs:
                if not isinstance(pair, dict):
                    continue
                pair_number = parse_excel_int(pair.get("number")) or 0
                if pair_number <= 0:
                    continue
                axis_number = parse_excel_int(pair.get("axisNumber")) or pair_number
                cur.execute(
                    "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                    (number, pair_number - 1, 1, str(axis_number)),
                )
                diameter_left = parse_float_value(pair.get("diameterLeft"))
                diameter_right = parse_float_value(pair.get("diameterRight"))
                if diameter_left is not None:
                    cur.execute(
                        "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                        (number, pair_number - 1, 2, str(diameter_left)),
                    )
                if diameter_right is not None:
                    cur.execute(
                        "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                        (number, pair_number - 1, 3, str(diameter_right)),
                    )
            imported_locomotives += 1
            imported_wheel_pairs += len(wheel_pairs)
        conn.commit()

    return {"ok": True, "imported_locomotives": imported_locomotives, "imported_wheel_pairs": imported_wheel_pairs}


def import_phone_measurement_payload(payload: dict) -> dict:
    """Импорт одиночного замера локомотива, переданного с телефона."""
    measurement = payload.get("measurement") if isinstance(payload.get("measurement"), dict) else payload
    if not isinstance(measurement, dict):
        return {"error": "Некорректный замер."}, HTTPStatus.BAD_REQUEST

    locomotive = measurement.get("locomotive")
    if not isinstance(locomotive, dict):
        return {"error": "Не найден локомотив в замере."}, HTTPStatus.BAD_REQUEST

    series = text(locomotive.get("series")).strip()
    number = text(locomotive.get("number")).strip()
    measurement_date = text(measurement.get("measurementDate")).strip() or dt.date.today().isoformat()
    repair_type = normalize_repair_type(measurement.get("repairType"))
    measurement_id = text(measurement.get("measurementId")).strip() or f"{measurement_date}:{number}:{repair_type}"
    wheel_pairs = measurement.get("wheelPairs")
    if not isinstance(wheel_pairs, list) or not wheel_pairs:
        return {"error": "В замере нет колесных пар."}, HTTPStatus.BAD_REQUEST

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    wheel_pair_count = parse_excel_int(locomotive.get("wheelPairCount")) or len(wheel_pairs) or locomotive_axis_count(series, number)
    section_count = default_section_count(wheel_pair_count)
    section_sizes: list[int] = []
    base = max(1, wheel_pair_count) // max(1, section_count)
    remainder = max(1, wheel_pair_count) % max(1, section_count)
    for index in range(max(1, section_count)):
        section_sizes.append(base + (1 if index < remainder else 0))

    archive_rows: list[tuple[int, str, str, str, int, int, str]] = []
    imported_cells = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        upsert_inventory_locomotive(cur, series, number)
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, number, repair_type),
        )
        for pair in wheel_pairs:
            if not isinstance(pair, dict):
                continue
            pair_number = parse_excel_int(pair.get("number")) or 0
            if pair_number <= 0:
                continue
            row_index = pair_number - 1
            running = 0
            section_value = "1"
            for section_index, span in enumerate(section_sizes, start=1):
                running += span
                if row_index < running:
                    section_value = str(section_index)
                    break
            left = pair.get("left") if isinstance(pair.get("left"), dict) else {}
            right = pair.get("right") if isinstance(pair.get("right"), dict) else {}
            values = {
                0: section_value,
                1: str(pair_number),
                2: excel_num_text(left.get("flangeWear")),
                3: excel_num_text(right.get("flangeWear")),
                4: excel_num_text(left.get("flangeThickness")),
                5: excel_num_text(right.get("flangeThickness")),
                6: excel_num_text(left.get("flangeSteepness")),
                7: excel_num_text(right.get("flangeSteepness")),
                8: excel_num_text(left.get("bandageThickness")),
                9: excel_num_text(right.get("bandageThickness")),
                10: excel_num_text(left.get("bandageDiameter")),
                11: excel_num_text(right.get("bandageDiameter")),
            }
            for col, value in values.items():
                value = text(value).strip()
                if value:
                    archive_rows.append((year, measurement_date, number, repair_type, row_index + 2, col, value))
                    imported_cells += 1
        cur.executemany(
            "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            archive_rows,
        )
        conn.commit()

    return {
        "ok": True,
        "imported_measurements": 1,
        "imported_cells": imported_cells,
        "measurement_id": measurement_id,
    }


def import_phone_payload(payload: object) -> dict:
    """Универсальная точка входа для импорта пакетов данных от мобильного приложения."""
    if isinstance(payload, dict):
        export_type = text(payload.get("exportType")).strip()
        if payload.get("archiveData") is not None or export_type == "archiveData":
            archive = payload.get("archiveData") if isinstance(payload.get("archiveData"), dict) else payload
            archive_items = archive.get("archive") if isinstance(archive, dict) else None
            if isinstance(archive_items, list):
                imported_measurements = 0
                imported_cells = 0
                for item in archive_items:
                    result = import_phone_measurement_payload(item)
                    if isinstance(result, tuple):
                        return result[0], result[1]
                    imported_measurements += int(result.get("imported_measurements", 0))
                    imported_cells += int(result.get("imported_cells", 0))
                return {"ok": True, "imported_measurements": imported_measurements, "imported_cells": imported_cells}
            return import_phone_measurement_payload(archive if isinstance(archive, dict) else payload)
        if payload.get("referenceData") is not None or export_type == "referenceData":
            reference = payload.get("referenceData") if isinstance(payload.get("referenceData"), dict) else payload
            return import_phone_reference_payload(reference)
        if payload.get("measurement") is not None:
            measurement = payload.get("measurement")
            if isinstance(measurement, dict):
                return import_phone_measurement_payload(measurement)
        if "locomotives" in payload:
            return import_phone_reference_payload(payload)
        if "wheelPairs" in payload and "measurementDate" in payload:
            return import_phone_measurement_payload(payload)
    return {"error": "Не удалось распознать телефонные данные."}, HTTPStatus.BAD_REQUEST

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from http import HTTPStatus
from pathlib import Path
from rtps_common import connect_sqlite

from constants import (
    ROOT,
    DB_FILE,
    DB_LOCK,
    DEFAULT_NORMS,
    DEFAULT_REPAIR_OPTIONS,
    INPUT_ROWS,
    INPUT_DATA_COLS,
    WEAR_TREND_METRICS,
)

def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    return connect_sqlite(DB_FILE)


def ensure_db() -> None:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()

        cur.execute(
            "CREATE TABLE IF NOT EXISTS input_meta (y INT, locomotive TEXT, measurement_date TEXT, wheel_pair_count INT, section_count INT, PRIMARY KEY(y, locomotive))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS input_data (y INT, locomotive TEXT, r INT, c INT, v TEXT, PRIMARY KEY(y, locomotive, r, c))"
        )
        cur.execute("CREATE TABLE IF NOT EXISTS inventory (y INT, ser TEXT, num TEXT, inv TEXT, PRIMARY KEY(y, ser, num))")
        _ensure_inventory_sync_columns(conn)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_data (
                locomotive TEXT, r INT, c INT, v TEXT,
                PRIMARY KEY(locomotive, r, c)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_data_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                locomotive TEXT NOT NULL,
                valid_to TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_data_version_cells (
                version_id INT NOT NULL,
                r INT NOT NULL,
                c INT NOT NULL,
                v TEXT,
                PRIMARY KEY(version_id, r, c)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_data (
                y INT,
                measurement_date TEXT,
                locomotive TEXT,
                repair_type TEXT,
                r INT,
                c INT,
                v TEXT,
                PRIMARY KEY(y, measurement_date, locomotive, repair_type, r, c)
            )
            """
        )
        _migrate_archive_repair_types(conn)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_norms_data (
                metric_key TEXT PRIMARY KEY,
                label TEXT,
                condition TEXT,
                yellow_value TEXT,
                red_value TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """
        )
        existing_input_meta_cols = {row[1] for row in cur.execute("PRAGMA table_info(input_meta)").fetchall()}
        if "wheel_pair_count" not in existing_input_meta_cols:
            cur.execute("ALTER TABLE input_meta ADD COLUMN wheel_pair_count INT")
        if "section_count" not in existing_input_meta_cols:
            cur.execute("ALTER TABLE input_meta ADD COLUMN section_count INT")
        existing_inventory_cols = {row[1] for row in cur.execute("PRAGMA table_info(inventory)").fetchall()}
        if "sort_order" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN sort_order INT")
        if "updated_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN updated_at INT")
            cur.execute("UPDATE inventory SET updated_at = 0 WHERE updated_at IS NULL")
        if "deleted_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN deleted_at INT")
            cur.execute("UPDATE inventory SET deleted_at = 0 WHERE deleted_at IS NULL")
        if "wheel_pair_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN wheel_pair_count INT")
        if "section_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN section_count INT")
        if "eight_digit_number" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN eight_digit_number TEXT")
        if "manufacture_year" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN manufacture_year TEXT")
        if "service_life" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN service_life TEXT")

        cur.execute("UPDATE inventory SET sort_order = rowid WHERE sort_order IS NULL OR sort_order <= 0")
        cur.executemany(
            "INSERT OR IGNORE INTO kp_norms_data(metric_key, label, condition, yellow_value, red_value) VALUES(?,?,?,?,?)",
            DEFAULT_NORMS,
        )
        conn.commit()


def _migrate_archive_repair_types(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT y, measurement_date, locomotive, repair_type, r, c FROM archive_data WHERE repair_type LIKE '%-%' OR repair_type LIKE '% %'"
    ).fetchall()
    for row in rows:
        year = int(row["y"] or 0)
        measurement_date = text(row["measurement_date"]).strip()
        locomotive = text(row["locomotive"]).strip()
        repair_type = text(row["repair_type"]).strip()
        normalized = normalize_repair_type(repair_type)
        if not normalized or normalized == repair_type:
            continue
        r = int(row["r"] or 0)
        c = int(row["c"] or 0)
        exists = cur.execute(
            "SELECT 1 FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=? AND r=? AND c=?",
            (year, measurement_date, locomotive, normalized, r, c),
        ).fetchone()
        if exists:
            cur.execute(
                "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=? AND r=? AND c=?",
                (year, measurement_date, locomotive, repair_type, r, c),
            )
        else:
            cur.execute(
                "UPDATE archive_data SET repair_type=? WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=? AND r=? AND c=?",
                (normalized, year, measurement_date, locomotive, repair_type, r, c),
            )
    conn.commit()


def _ensure_inventory_sync_columns(conn: sqlite3.Connection) -> None:
    columns = {text(row[1]).strip().lower() for row in conn.execute("PRAGMA table_info(inventory)").fetchall()}
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE inventory ADD COLUMN updated_at INT NOT NULL DEFAULT 0")
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE inventory ADD COLUMN deleted_at INT NOT NULL DEFAULT 0")


def text(value) -> str:
    return "" if value is None else str(value)


def normalize_repair_type(value) -> str:
    return text(value).strip().upper().replace(" ", "").replace("-", "")


def normalize_text(value: str) -> str:
    text_value = text(value).strip().lower()
    text_value = text_value.replace("ё", "е")
    return text_value


def parse_excel_int(value) -> int | None:
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


def parse_float_value(value) -> float | None:
    raw = text(value).strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def series_for_locomotive(cur: sqlite3.Cursor, locomotive: str) -> str:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return ""
    row = cur.execute(
        "SELECT ser FROM inventory WHERE TRIM(COALESCE(num, ''))=? ORDER BY COALESCE(deleted_at, 0) ASC, COALESCE(updated_at, 0) DESC, y DESC, rowid DESC LIMIT 1",
        (locomotive,),
    ).fetchone()
    if row:
        return text(row["ser"]).strip()
    return ""


def locomotive_axis_count(series: str, locomotive: str) -> int:
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return 12
    if "тэм" in normalized or "tem" in normalized:
        return 6
    return 12


def default_section_count(axis_count: int) -> int:
    return 1 if int(axis_count or 0) <= 6 else 3


def allowed_repairs(series: str, locomotive: str) -> list[str]:
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return DEFAULT_REPAIR_OPTIONS["pe"]
    return DEFAULT_REPAIR_OPTIONS["tem"]


def load_locomotives(cur: sqlite3.Cursor) -> list[dict[str, str]]:
    return load_inventory_records(cur, include_deleted=False)


def load_inventory_records(cur: sqlite3.Cursor, include_deleted: bool = False) -> list[dict[str, str]]:
    query = """
        SELECT y, ser, num, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(updated_at, 0) AS updated_at, COALESCE(deleted_at, 0) AS deleted_at, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number, COALESCE(manufacture_year, '') AS manufacture_year, COALESCE(service_life, '') AS service_life
        FROM inventory
        WHERE TRIM(COALESCE(num, '')) <> ''
    """
    if not include_deleted:
        query += " AND COALESCE(deleted_at, 0) = 0"
    query += " ORDER BY COALESCE(sort_order, 0) ASC, COALESCE(updated_at, 0) DESC, rowid DESC"
    rows = cur.execute(query).fetchall()

    best_rows: dict[str, sqlite3.Row] = {}
    for row in rows:
        number = text(row["num"]).strip()
        if not number:
            continue
        series = normalize_text(row["ser"]).strip().upper()
        key = f"{series}|{number}"
        current = best_rows.get(key)
        if current is None:
            best_rows[key] = row
            continue
        current_rank = (
            int(current["updated_at"] or 0),
            int(current["deleted_at"] or 0),
            int(current["sort_order"] or 0),
            int(current["rowid"] or 0),
        )
        row_rank = (
            int(row["updated_at"] or 0),
            int(row["deleted_at"] or 0),
            int(row["sort_order"] or 0),
            int(row["rowid"] or 0),
        )
        if row_rank > current_rank:
            best_rows[key] = row

    result: list[dict[str, str]] = []
    for row in sorted(
        best_rows.values(),
        key=lambda item: (
            int(item["sort_order"] or 0),
            -int(item["updated_at"] or 0),
            -int(item["deleted_at"] or 0),
            normalize_text(item["ser"]).strip().upper(),
            text(item["num"]).strip(),
        ),
    ):
        number = text(row["num"]).strip()
        if not number:
            continue
        deleted_at = int(row["deleted_at"] or 0)
        if deleted_at > 0 and not include_deleted:
            continue
        series = normalize_text(row["ser"]).strip().upper()
        inv = text(row["inv"]).strip()
        sort_order = int(row["sort_order"] or 0)
        updated_at = int(row["updated_at"] or 0)
        wheel_pair_count = int(row["wheel_pair_count"] or 0)
        section_count = int(row["section_count"] or 0)
        eight_digit_number = text(row["eight_digit_number"]).strip()
        manufacture_year = text(row["manufacture_year"]).strip()
        service_life = text(row["service_life"]).strip()
        label = f"{series} {number}".strip()
        result.append(
            {
                "series": series,
                "number": number,
                "label": label,
                "inventoryNumber": inv,
                "sortOrder": sort_order,
                "updatedAt": updated_at,
                "deletedAt": deleted_at,
                "wheelPairCount": wheel_pair_count,
                "sectionCount": section_count,
                "eightDigitNumber": eight_digit_number,
                "manufactureYear": manufacture_year,
                "serviceLife": service_life,
            }
        )
    return result


def empty_measurements() -> list[list[str]]:
    return [["" for _ in range(INPUT_DATA_COLS)] for _ in range(INPUT_ROWS)]


def row_to_index(row_value: int) -> int | None:
    idx = int(row_value) - 2
    return idx if 0 <= idx < INPUT_ROWS else None


def load_state(locomotive: str | None = None, wheel_pair_count: int | None = None, section_count: int | None = None) -> dict:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_locomotives(cur)
        if not locomotive:
            locomotive = locomotives[0]["number"] if locomotives else ""
        locomotive = text(locomotive).strip()

        series = series_for_locomotive(cur, locomotive)
        axis_count = locomotive_axis_count(series, locomotive)
        repair_options = allowed_repairs(series, locomotive)
        locomotive_record = next((item for item in locomotives if text(item.get("number")).strip() == locomotive), None)

        meta = None
        if locomotive:
            meta = cur.execute(
                "SELECT y, measurement_date, wheel_pair_count, section_count FROM input_meta WHERE locomotive=? ORDER BY y DESC LIMIT 1",
                (locomotive,),
            ).fetchone()

        measurement_date = dt.date.today().isoformat()
        year = dt.date.today().year
        if wheel_pair_count is None:
            wheel_pair_count = int(locomotive_record.get("wheelPairCount") or 0) if locomotive_record else 0
            if wheel_pair_count <= 0:
                wheel_pair_count = axis_count
        if section_count is None:
            section_count = int(locomotive_record.get("sectionCount") or 0) if locomotive_record else 0
            if section_count <= 0:
                section_count = default_section_count(axis_count)
        has_manual_meta = False
        if meta:
            year = int(meta["y"] or year)
            measurement_date = text(meta["measurement_date"]).strip() or measurement_date
            try:
                year = int(measurement_date[:4])
            except Exception:
                pass
            try:
                meta_wheel_pairs = int(meta["wheel_pair_count"] or 0)
            except Exception:
                meta_wheel_pairs = 0
            try:
                meta_sections = int(meta["section_count"] or 0)
            except Exception:
                meta_sections = 0
            if meta_wheel_pairs > 0:
                wheel_pair_count = meta_wheel_pairs
            if meta_sections > 0:
                section_count = meta_sections
            has_manual_meta = meta_wheel_pairs > 0 or meta_sections > 0
        elif measurement_date:
            try:
                year = int(measurement_date[:4])
            except Exception:
                year = dt.date.today().year

        rows = empty_measurements()
        if locomotive:
            db_rows = cur.execute(
                "SELECT r, c, v FROM input_data WHERE y=? AND locomotive=? ORDER BY r, c",
                (year, locomotive),
            ).fetchall()
            for row in db_rows:
                idx = row_to_index(int(row["r"]))
                col = int(row["c"]) - 2
                if idx is None or not (0 <= col < INPUT_DATA_COLS):
                    continue
                rows[idx][col] = text(row["v"])

        kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c", (locomotive,)).fetchall()
        if not kp_rows:
            kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c").fetchall()

        kp_map: dict[int, dict[int, str]] = {}
        for row in kp_rows:
            kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

        norms = {
            row["metric_key"]: {
                "label": text(row["label"]),
                "condition": text(row["condition"]),
                "yellow_value": text(row["yellow_value"]),
                "red_value": text(row["red_value"]),
            }
            for row in cur.execute(
                "SELECT metric_key, label, condition, yellow_value, red_value FROM kp_norms_data ORDER BY rowid"
            ).fetchall()
        }

    return {
        "locomotive": locomotive,
        "series": series,
        "axis_count": axis_count,
        "measurement_date": measurement_date,
        "repair_type": "",
        "repair_options": repair_options,
        "locomotives": locomotives,
        "measurements": rows,
        "kp": kp_map,
        "norms": norms,
        "year": year,
        "wheel_pair_count": int(wheel_pair_count or axis_count),
        "section_count": int(section_count or default_section_count(axis_count)),
        "has_manual_meta": has_manual_meta,
    }


def kp_completion_state(cur: sqlite3.Cursor, locomotive: str) -> str | None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return None

    series = series_for_locomotive(cur, locomotive)
    expected_rows = locomotive_axis_count(series, locomotive)
    rows = cur.execute(
        "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3)",
        (locomotive,),
    ).fetchall()
    if not rows:
        return None

    values: dict[tuple[int, int], str] = {}
    for row in rows:
        values[(int(row["r"]), int(row["c"]))] = text(row["v"]).strip()

    for row_index in range(expected_rows):
        if not values.get((row_index, 2), "") or not values.get((row_index, 3), ""):
            return "yellow"
    return "green"


def load_kp_versions(cur: sqlite3.Cursor, locomotive: str) -> list[dict]:
    rows = cur.execute(
        """
        SELECT id, valid_to, created_at
        FROM kp_data_versions
        WHERE locomotive=?
        ORDER BY COALESCE(valid_to, '') DESC, id DESC
        """,
        (locomotive,),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "valid_to": text(row["valid_to"]).strip(),
            "created_at": text(row["created_at"]).strip(),
        }
        for row in rows
    ]


def load_kp_view(selected_locomotive: str = "", version_id: int | None = None) -> dict:
    selected_locomotive = text(selected_locomotive).strip()
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_locomotives(cur)
        if not selected_locomotive and locomotives:
            selected_locomotive = locomotives[0]["number"]

        all_mode = selected_locomotive == "Все локомотивы"
        kp_map: dict[int, dict[int, str]] = {}
        rows: list[dict[str, object]] = []
        axis_count = 0
        status = None
        selected_version = None

        if all_mode:
            all_values = cur.execute(
                "SELECT locomotive, r, c, v FROM kp_data WHERE TRIM(COALESCE(locomotive, '')) <> '' ORDER BY locomotive, r, c"
            ).fetchall()
            kp_values: dict[tuple[str, int, int], str] = {}
            for row in all_values:
                kp_values[(text(row["locomotive"]).strip(), int(row["r"]), int(row["c"]))] = text(row["v"])

            for loco in locomotives:
                number = loco["number"]
                series = loco["series"]
                count = locomotive_axis_count(series, number)
                for row_index in range(count):
                    values = [
                        number,
                        kp_values.get((number, row_index, 0), str(row_index + 1)),
                        kp_values.get((number, row_index, 1), ""),
                        kp_values.get((number, row_index, 2), ""),
                        kp_values.get((number, row_index, 3), ""),
                    ]
                    rows.append(
                        {
                            "locomotive": number,
                            "row": row_index,
                            "values": values,
                            "search": " ".join(text(v).strip().lower() for v in values),
                            "editable": False,
                        }
                    )
            status = "all"
        else:
            series = series_for_locomotive(cur, selected_locomotive)
            axis_count = locomotive_axis_count(series, selected_locomotive)
            if version_id:
                version_row = cur.execute(
                    """
                    SELECT id, valid_to, created_at
                    FROM kp_data_versions
                    WHERE id=? AND locomotive=?
                    """,
                    (version_id, selected_locomotive),
                ).fetchone()
                if version_row:
                    selected_version = {
                        "id": int(version_row["id"]),
                        "valid_to": text(version_row["valid_to"]).strip(),
                        "created_at": text(version_row["created_at"]).strip(),
                    }
                    kp_rows = cur.execute(
                        "SELECT r, c, v FROM kp_data_version_cells WHERE version_id=? ORDER BY r, c",
                        (version_id,),
                    ).fetchall()
                else:
                    kp_rows = []
            else:
                kp_rows = cur.execute(
                    "SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c",
                    (selected_locomotive,),
                ).fetchall()
                if not kp_rows:
                    kp_rows = cur.execute(
                        "SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c"
                    ).fetchall()
            for row in kp_rows:
                kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

            for row_index in range(axis_count):
                values = [
                    kp_map.get(row_index, {}).get(0, str(row_index + 1)),
                    kp_map.get(row_index, {}).get(1, ""),
                    kp_map.get(row_index, {}).get(2, ""),
                    kp_map.get(row_index, {}).get(3, ""),
                ]
                rows.append(
                    {
                        "locomotive": selected_locomotive,
                        "row": row_index,
                        "values": values,
                        "search": " ".join(text(v).strip().lower() for v in values),
                        "editable": selected_version is None,
                    }
                )
            status = kp_completion_state(cur, selected_locomotive) if selected_version is None else None

        return {
            "selected_locomotive": selected_locomotive,
            "all_mode": all_mode,
            "axis_count": axis_count,
            "locomotives": locomotives,
            "rows": rows,
            "kp_map": kp_map,
            "status": status,
            "versions": load_kp_versions(cur, selected_locomotive) if selected_locomotive and not all_mode else [],
            "selected_version": selected_version,
        }


def save_kp_data(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    if not locomotive or locomotive == "Все локомотивы":
        return {"error": "Выберите конкретный локомотив."}, 400

    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return {"error": "Некорректные данные КП."}, 400

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM kp_data WHERE locomotive=?", (locomotive,))

        insert_rows: list[tuple[str, int, int, str]] = []
        for r, row in enumerate(rows):
            values = list(row or []) + [""] * 4
            for c, value in enumerate(values[:4]):
                value = text(value).strip()
                if value:
                    insert_rows.append((locomotive, r, c, value))
        cur.executemany("INSERT INTO kp_data (locomotive, r, c, v) VALUES (?, ?, ?, ?)", insert_rows)
        conn.commit()

    return load_kp_view(locomotive)


def create_kp_data_version(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    valid_to = text(payload.get("valid_to")).strip()
    if not locomotive or locomotive == "Все локомотивы":
        return {"error": "Выберите конкретный локомотив."}, 400
    try:
        dt.date.fromisoformat(valid_to)
    except Exception:
        return {"error": "Укажите дату, до которой действовали старые данные."}, 400

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        current_rows = cur.execute(
            "SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c",
            (locomotive,),
        ).fetchall()
        if not current_rows:
            return {"error": "Нет текущих данных для сохранения в историю."}, 400

        cur.execute(
            "INSERT INTO kp_data_versions(locomotive, valid_to, created_at) VALUES(?,?,?)",
            (locomotive, valid_to, dt.datetime.now().isoformat(timespec="seconds")),
        )
        version_id = int(cur.lastrowid)
        cur.executemany(
            "INSERT INTO kp_data_version_cells(version_id, r, c, v) VALUES(?,?,?,?)",
            [
                (version_id, int(row["r"]), int(row["c"]), text(row["v"]))
                for row in current_rows
            ],
        )
        cur.execute("DELETE FROM kp_data WHERE locomotive=?", (locomotive,))
        new_rows = [
            (locomotive, int(row["r"]), int(row["c"]), text(row["v"]))
            for row in current_rows
            if int(row["c"]) in (0, 1) and text(row["v"]).strip()
        ]
        cur.executemany(
            "INSERT INTO kp_data(locomotive, r, c, v) VALUES(?,?,?,?)",
            new_rows,
        )
        conn.commit()
    return load_kp_view(locomotive)


def update_kp_version(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    valid_to = text(payload.get("valid_to")).strip()
    try:
        version_id = int(payload.get("version_id"))
        dt.date.fromisoformat(valid_to)
    except Exception:
        return {"error": "Некорректная дата версии КП."}, 400
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE kp_data_versions SET valid_to=? WHERE id=? AND locomotive=?",
            (valid_to, version_id, locomotive),
        )
        if cur.rowcount <= 0:
            return {"error": "Версия КП не найдена."}, 404
        conn.commit()
    return load_kp_view(locomotive, version_id)


def save_state(payload: dict, full_name: str = "") -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    measurement_date = text(payload.get("measurement_date")).strip() or dt.date.today().isoformat()
    rows = payload.get("measurements") or []
    try:
        wheel_pair_count = int(payload.get("wheel_pair_count") or 0)
    except Exception:
        wheel_pair_count = 0
    try:
        section_count = int(payload.get("section_count") or 0)
    except Exception:
        section_count = 0

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM input_data WHERE y=? AND locomotive=?", (year, locomotive))
        insert_rows: list[tuple[int, str, int, int, str]] = []
        for r, row in enumerate(rows):
            row = list(row or []) + [""] * INPUT_DATA_COLS
            for c, value in enumerate(row[:INPUT_DATA_COLS]):
                value = text(value).strip()
                if value:
                    insert_rows.append((year, locomotive, r + 2, c + 2, value))
        cur.executemany("INSERT INTO input_data(y, locomotive, r, c, v) VALUES(?,?,?,?,?)", insert_rows)
        cur.execute(
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date, wheel_pair_count, section_count) VALUES(?,?,?,?,?)",
            (
                year,
                locomotive,
                measurement_date,
                wheel_pair_count or None,
                section_count or None,
            ),
        )
        conn.commit()
    return load_state(locomotive)


def load_effective_kp_values_for_date(
    cur: sqlite3.Cursor,
    locomotive: str,
    measurement_date: str,
    cache: dict[tuple[str, str], dict[tuple[int, int], str]] | None = None,
) -> dict[tuple[int, int], str]:
    loco = text(locomotive).strip()
    date_key = text(measurement_date).strip()
    cache_key = (loco, date_key)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    kp_values: dict[tuple[int, int], str] = {}
    if loco:
        version_row = None
        if date_key:
            version_row = cur.execute(
                """
                SELECT id
                FROM kp_data_versions
                WHERE locomotive=? AND TRIM(COALESCE(valid_to, '')) <> '' AND valid_to >= ?
                ORDER BY valid_to ASC, id ASC
                LIMIT 1
                """,
                (loco, date_key),
            ).fetchone()

        if version_row:
            version_rows = cur.execute(
                "SELECT r, c, v FROM kp_data_version_cells WHERE version_id=? AND c IN (2, 3) ORDER BY r, c",
                (int(version_row["id"]),),
            ).fetchall()
            for row in version_rows:
                kp_values[(int(row["r"]), int(row["c"]))] = text(row["v"]).strip()

        current_rows = cur.execute(
            "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3) ORDER BY r, c",
            (loco,),
        ).fetchall()
        for row in current_rows:
            kp_values.setdefault((int(row["r"]), int(row["c"])), text(row["v"]).strip())

    if cache is not None:
        cache[cache_key] = kp_values
    return kp_values


def resolve_archive_diameter_pair(
    cur: sqlite3.Cursor,
    locomotive: str,
    measurement_date: str,
    pair_row_index: int,
    values: list[str],
    kp_cache: dict[tuple[str, str], dict[tuple[int, int], str]] | None = None,
) -> tuple[str, str, str, str]:
    bandage_left = values[8] or ""
    bandage_right = values[9] or ""
    fallback_left = values[10] or ""
    fallback_right = values[11] or ""
    kp_values = load_effective_kp_values_for_date(cur, locomotive, measurement_date, kp_cache)

    resolved_left = fallback_left
    left_bandage_value = parse_float_value(bandage_left)
    if left_bandage_value is not None:
        kp_left = parse_float_value(kp_values.get((pair_row_index, 2), ""))
        if kp_left is not None:
            resolved_left = str(int(round(kp_left + left_bandage_value * 2)))

    resolved_right = fallback_right
    right_bandage_value = parse_float_value(bandage_right)
    if right_bandage_value is not None:
        kp_right = parse_float_value(kp_values.get((pair_row_index, 3), ""))
        if kp_right is not None:
            resolved_right = str(int(round(kp_right + right_bandage_value * 2)))

    return bandage_left, bandage_right, resolved_left, resolved_right


def build_archive_rows(payload: dict) -> tuple[dict, list[tuple[int, str, str, str, int, int, str]], list[str]]:
    locomotive = text(payload.get("locomotive")).strip()
    measurement_date = text(payload.get("measurement_date")).strip() or dt.date.today().isoformat()
    repair_type = normalize_repair_type(payload.get("repair_type"))
    rows = payload.get("measurements") or []

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        series = series_for_locomotive(cur, locomotive)
        series_text = normalize_text(series + " " + locomotive)
        axis_count = locomotive_axis_count(series, locomotive)
        try:
            wheel_pair_count = int(payload.get("wheel_pair_count") or axis_count)
        except Exception:
            wheel_pair_count = axis_count
        try:
            section_count = int(payload.get("section_count") or default_section_count(axis_count))
        except Exception:
            section_count = default_section_count(axis_count)
        visible_rows = max(1, min(wheel_pair_count, INPUT_ROWS))
        if "пэ-2м" in series_text or "пэ2м" in series_text or "пэ 2м" in series_text or "pe-2m" in series_text or "pe2m" in series_text:
            required_columns = [0, 1, 2, 3, 6, 7]
        else:
            required_columns = [0, 1, 2, 3, 4, 5, 6, 7]

        kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c", (locomotive,)).fetchall()
        if not kp_rows:
            kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c").fetchall()
        kp_map: dict[int, dict[int, str]] = {}
        for row in kp_rows:
            kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

        def parse_float(v):
            try:
                return float(text(v).replace(",", "."))
            except Exception:
                return None

        missing_cells: list[str] = []
        normalized_rows: list[list[str]] = []
        section_sizes: list[int] = []
        base = visible_rows // max(1, section_count)
        remainder = visible_rows % max(1, section_count)
        for i in range(max(1, section_count)):
            section_sizes.append(base + (1 if i < remainder else 0))
        for row_index in range(visible_rows):
            row = list(rows[row_index] if row_index < len(rows) else []) + [""] * INPUT_DATA_COLS
            normalized_rows.append(row[:INPUT_DATA_COLS])
            for col in required_columns:
                value = text(row[col]).strip()
                if not value:
                    axis_number = row_index + 1
                    missing_cells.append(f"ось {axis_number}, колонка {col + 1}")

        if missing_cells:
            return {"error": "missing", "measurement_date": measurement_date, "locomotive": locomotive, "repair_type": repair_type}, [], missing_cells

        if not repair_type:
            return {"error": "repair", "measurement_date": measurement_date, "locomotive": locomotive, "repair_type": repair_type}, [], []

        archive_rows: list[tuple[int, str, str, str, int, int, str]] = []
        for row_index in range(visible_rows):
            row = normalized_rows[row_index]
            table_row = row_index + 2
            running = 0
            section_value = "1"
            for section_index, span in enumerate(section_sizes, start=1):
                running += span
                if row_index < running:
                    section_value = str(section_index)
                    break
            kp_row = kp_map.get(row_index, {})

            left_band = parse_float(row[6])
            right_band = parse_float(row[7])
            left_kp = parse_float(kp_row.get(2, ""))
            right_kp = parse_float(kp_row.get(3, ""))
            left_diam = "" if left_kp is None or left_band is None else str(int(round(left_kp + left_band * 2)))
            right_diam = "" if right_kp is None or right_band is None else str(int(round(right_kp + right_band * 2)))

            values = {
                0: section_value,
                1: str(row_index + 1),
                2: row[0],
                3: row[1],
                4: row[2],
                5: row[3],
                6: row[4],
                7: row[5],
                8: row[6],
                9: row[7],
                10: left_diam,
                11: right_diam,
            }
            for col, value in values.items():
                value = text(value).strip()
                if value:
                    archive_rows.append((year, measurement_date, locomotive, repair_type, table_row, col, value))

        return {
            "year": year,
            "measurement_date": measurement_date,
            "locomotive": locomotive,
            "repair_type": repair_type,
            "axis_count": axis_count,
        }, archive_rows, []


def save_archive(payload: dict) -> dict:
    meta, archive_rows, missing_cells = build_archive_rows(payload)
    if meta.get("error") == "missing":
        return {"error": "Не все обязательные ячейки заполнены.", "missing_cells": missing_cells}, 400
    if meta.get("error") == "repair":
        return {"error": "Выберите вид ремонта."}, 400

    year = int(meta["year"])
    measurement_date = meta["measurement_date"]
    locomotive = meta["locomotive"]
    repair_type = meta["repair_type"]
    overwrite = bool(payload.get("overwrite"))
    try:
        wheel_pair_count = int(payload.get("wheel_pair_count") or 0)
    except Exception:
        wheel_pair_count = 0
    try:
        section_count = int(payload.get("section_count") or 0)
    except Exception:
        section_count = 0

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT COUNT(*) FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        ).fetchone()[0]
        if existing and not overwrite:
            return {
                "error": "duplicate",
                "message": "Запись с таким локомотивом, датой и видом ремонта уже есть в архиве.",
            }, 409

        cur.execute("BEGIN")
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        )
        cur.executemany(
            "INSERT INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            archive_rows,
        )
        cur.execute("DELETE FROM input_data WHERE y=? AND locomotive=?", (year, locomotive))
        cur.execute(
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date, wheel_pair_count, section_count) VALUES(?,?,?,?,?)",
            (
                year,
                locomotive,
                measurement_date,
                wheel_pair_count or None,
                section_count or None,
            ),
        )
        conn.commit()

    return load_state(locomotive)


def update_archive_cells(payload: dict) -> dict:
    changes = payload.get("changes") or []
    if not isinstance(changes, list) or not changes:
        return {"error": "Нет изменений для сохранения."}, 400

    normalized: list[tuple[int, str, str, str, int, int, str]] = []
    for change in changes:
        if not isinstance(change, dict):
            return {"error": "Некорректный формат изменений."}, 400
        try:
            year = int(change.get("year"))
            measurement_date = text(change.get("measurement_date")).strip()
            locomotive = text(change.get("locomotive")).strip()
            repair_type = normalize_repair_type(change.get("repair_type"))
            source_r = int(change.get("source_r"))
            display_col = int(change.get("display_col"))
            if display_col < 10 or display_col > 19:
                return {"error": "Можно редактировать только правую часть таблицы архива."}, 400
            source_c = display_col - 8
            value = text(change.get("value"))
        except Exception:
            return {"error": "Некорректные данные изменения архива."}, 400

        if not measurement_date or not locomotive or not repair_type:
            return {"error": "Не удалось определить строку архива для изменения."}, 400

        normalized.append((year, measurement_date, locomotive, repair_type, source_r, source_c, value))

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for year, measurement_date, locomotive, repair_type, source_r, source_c, value in normalized:
            cur.execute(
                "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (year, measurement_date, locomotive, repair_type, source_r, source_c, value),
            )
        conn.commit()

    return {"ok": True}


def delete_archive_measurement(payload: dict) -> dict:
    try:
        year = int(payload.get("year"))
        measurement_date = text(payload.get("measurement_date")).strip()
        locomotive = text(payload.get("locomotive")).strip()
        repair_type = normalize_repair_type(payload.get("repair_type"))
    except Exception:
        return {"error": "Некорректные данные для удаления архива."}, 400

    if not measurement_date or not locomotive or not repair_type:
        return {"error": "Не удалось определить замер для удаления."}, 400

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        )
        deleted = cur.rowcount
        conn.commit()

    return {"ok": True, "deleted": deleted}


def load_norms_rows() -> list[dict[str, str | bool]]:
    default_keys = [item[0] for item in DEFAULT_NORMS]
    with DB_LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT metric_key, label, condition, yellow_value, red_value FROM kp_norms_data ORDER BY rowid"
        ).fetchall()

    db_norms = {text(row["metric_key"]): row for row in rows}
    result: list[dict[str, str | bool]] = []
    for metric_key, label, condition, yellow, red in DEFAULT_NORMS:
        row = db_norms.get(metric_key)
        result.append(
            {
                "metric_key": metric_key,
                "label": label,
                "condition": text(row["condition"] if row else condition),
                "yellow_value": text(row["yellow_value"] if row else yellow),
                "red_value": text(row["red_value"] if row else red),
                "is_default": True,
            }
        )

    for row in rows:
        metric_key = text(row["metric_key"])
        if metric_key in default_keys:
            continue
        result.append(
            {
                "metric_key": metric_key,
                "label": text(row["label"]),
                "condition": text(row["condition"]),
                "yellow_value": text(row["yellow_value"]),
                "red_value": text(row["red_value"]),
                "is_default": False,
            }
        )
    return result


def save_norms_rows(payload: dict) -> dict:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {"error": "rows"}, HTTPStatus.BAD_REQUEST

    normalized: list[tuple[str, str, str, str, str]] = []
    seen: set[str] = set()
    default_keys = {item[0] for item in DEFAULT_NORMS}
    conditions = {"меньше или равно", "больше или равно"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        metric_key = text(row.get("metric_key")).strip()
        label = text(row.get("label")).strip()
        condition = text(row.get("condition")).strip()
        yellow = text(row.get("yellow_value")).strip()
        red = text(row.get("red_value")).strip()
        if not label:
            continue
        if not metric_key:
            metric_key = f"custom_{index + 1}"
        if metric_key in seen:
            suffix = 2
            base_key = metric_key
            while f"{base_key}_{suffix}" in seen:
                suffix += 1
            metric_key = f"{base_key}_{suffix}"
        if condition not in conditions:
            condition = "меньше или равно"
        if metric_key in default_keys:
            default_label = next((item[1] for item in DEFAULT_NORMS if item[0] == metric_key), label)
            label = default_label
        seen.add(metric_key)
        normalized.append((metric_key, label, condition, yellow, red))

    with DB_LOCK, connect() as conn:
        conn.execute("DELETE FROM kp_norms_data")
        conn.executemany(
            """
            INSERT INTO kp_norms_data(metric_key, label, condition, yellow_value, red_value)
            VALUES(?,?,?,?,?)
            """,
            normalized,
        )
        conn.commit()

    return {"ok": True, "rows": load_norms_rows()}


def upsert_inventory_locomotive(
    cur: sqlite3.Cursor,
    series: str,
    locomotive: str,
    inv: str = "",
    wheel_pair_count: int = 0,
    section_count: int = 0,
    eight_digit_number: str = "",
    manufacture_year: str = "",
    service_life: str = "",
    sort_order: int = 0,
    updated_at: int | None = None,
    deleted_at: int | None = None,
) -> None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return
    series = text(series).strip().upper()
    inv = text(inv).strip()
    eight_digit_number = text(eight_digit_number).strip()
    manufacture_year = text(manufacture_year).strip()
    service_life = text(service_life).strip()
    year = dt.date.today().year
    sort_order_value = int(sort_order or 0)
    updated_at = int(updated_at or int(dt.datetime.now().timestamp() * 1000))
    if sort_order_value <= 0:
        existing = cur.execute(
            "SELECT COALESCE(sort_order, 0) AS sort_order FROM inventory WHERE UPPER(TRIM(COALESCE(num, ''))) = UPPER(TRIM(?)) ORDER BY COALESCE(updated_at, 0) DESC, COALESCE(deleted_at, 0) DESC, COALESCE(sort_order, 0) ASC, rowid DESC LIMIT 1",
            (locomotive,),
        ).fetchone()
        if existing:
            sort_order_value = int(existing["sort_order"] or 0)
    if sort_order_value <= 0:
        max_row = cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order FROM inventory"
        ).fetchone()
        sort_order_value = int(max_row["max_sort_order"] or 0) + 1
    exact = cur.execute(
        "SELECT rowid, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number, COALESCE(manufacture_year, '') AS manufacture_year, COALESCE(service_life, '') AS service_life, COALESCE(deleted_at, 0) AS deleted_at "
        "FROM inventory WHERE UPPER(TRIM(COALESCE(ser, ''))) = UPPER(TRIM(?)) AND TRIM(COALESCE(num, ''))=? "
        "ORDER BY COALESCE(updated_at, 0) DESC, COALESCE(deleted_at, 0) DESC, y DESC, rowid DESC LIMIT 1",
        (series, locomotive),
    ).fetchone()
    if exact:
        if sort_order_value <= 0:
            sort_order_value = int(exact["sort_order"] or 0)
        if not inv:
            inv = text(exact["inv"]).strip()
        if not wheel_pair_count:
            wheel_pair_count = int(exact["wheel_pair_count"] or 0)
        if not section_count:
            section_count = int(exact["section_count"] or 0)
        if not eight_digit_number:
            eight_digit_number = text(exact["eight_digit_number"]).strip()
        if not manufacture_year:
            manufacture_year = text(exact["manufacture_year"]).strip()
        if not service_life:
            service_life = text(exact["service_life"]).strip()
        if deleted_at is None:
            deleted_at = int(exact["deleted_at"] or 0)
        cur.execute(
            """
            UPDATE inventory
            SET ser=?, num=?, inv=?, wheel_pair_count=?, section_count=?, eight_digit_number=?, manufacture_year=?, service_life=?, sort_order=?, updated_at=?, deleted_at=?
            WHERE rowid=?
            """,
            (series, locomotive, inv, wheel_pair_count or None, section_count or None, eight_digit_number, manufacture_year, service_life, sort_order_value, updated_at, int(deleted_at or 0), int(exact["rowid"])),
        )
        cur.execute(
            "DELETE FROM inventory WHERE UPPER(TRIM(COALESCE(ser, ''))) = UPPER(TRIM(?)) AND TRIM(COALESCE(num, ''))=? AND rowid<>?",
            (series, locomotive, int(exact["rowid"])),
        )
        return
    if deleted_at is None:
        deleted_at = 0
    cur.execute(
        """
        INSERT INTO inventory (y, ser, num, inv, wheel_pair_count, section_count, eight_digit_number, manufacture_year, service_life, sort_order, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (year, series, locomotive, inv, wheel_pair_count or None, section_count or None, eight_digit_number, manufacture_year, service_life, sort_order_value, updated_at, int(deleted_at or 0)),
    )

    if int(deleted_at or 0) <= 0:
        for index in range(max(1, int(wheel_pair_count or 1))):
            cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 0, ?)", (locomotive, index, str(index + 1)))
            cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 1, ?)", (locomotive, index, str(index + 1)))


def ensure_import_locomotive(cur: sqlite3.Cursor, series: str, locomotive: str, wheel_pair_count: int) -> None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return
    series = text(series).strip().upper()
    upsert_inventory_locomotive(cur, series, locomotive)
    for index in range(max(1, int(wheel_pair_count or 1))):
        cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 0, ?)", (locomotive, index, str(index + 1)))
        cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 1, ?)", (locomotive, index, str(index + 1)))


def load_archive_rows(locomotive: str = "", search_text: str = "", sort_desc: bool = True) -> list[dict]:
    locomotive = text(locomotive).strip()
    search_text = text(search_text).strip().lower()
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        order_direction = "DESC" if sort_desc else "ASC"
        params: list[str] = []
        query = """
            SELECT y, measurement_date, locomotive, repair_type, r, c, v
            FROM archive_data
        """
        where: list[str] = []
        if locomotive and locomotive != "Все локомотивы":
            where.append("locomotive = ?")
            params.append(locomotive)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += f" ORDER BY y {order_direction}, measurement_date {order_direction}, locomotive ASC, repair_type ASC, r ASC, c ASC"
        rows = cur.execute(query, params).fetchall()

        grouped: dict[tuple[int, str, str, str, int], list[str]] = {}
        for row in rows:
            r = int(row["r"])
            if r < 2:
                continue
            key = (
                int(row["y"] or 0),
                text(row["measurement_date"]).strip(),
                text(row["locomotive"]).strip(),
                text(row["repair_type"]).strip(),
                r,
            )
            grouped.setdefault(key, [""] * 12)
            c = int(row["c"])
            if 0 <= c < 12:
                grouped[key][c] = text(row["v"])

        kp_cache: dict[tuple[str, str], dict[tuple[int, int], str]] = {}

        def to_float(v):
            try:
                return float(text(v).replace(",", "."))
            except Exception:
                return None

        def fmt_num(v, is_prokat=False):
            if v is None:
                return ""
            try:
                value = float(v)
            except Exception:
                return text(v).strip()
            if value.is_integer():
                if is_prokat:
                    return f"{int(value)},0"
                return str(int(value))
            return str(value).rstrip("0").rstrip(".").replace(".", ",")

        def fmt_raw(v, is_prokat=False):
            if v is None or text(v).strip() == "":
                return ""
            try:
                value = float(text(v).replace(",", "."))
            except Exception:
                return text(v).strip()
            if value.is_integer():
                if is_prokat:
                    return f"{int(value)},0"
                return str(int(value))
            return text(v).strip().replace(".", ",")

        stats_by_section: dict[tuple[int, str, str, str, str], dict[str, str]] = {}
        for (year, measurement_date, loco, repair_type, row_index), values in grouped.items():
            section_value = values[0] or "1"
            key = (year, measurement_date, loco, repair_type, section_value)
            stats = stats_by_section.setdefault(
                key,
                {
                    "max_prokat": "",
                    "min_greben": "",
                    "min_krut": "",
                    "min_bandage_thickness": "",
                    "min_diameter": "",
                    "max_diameter": "",
                    "max_diameter_diff": "",
                    "prokat_6_count": "0",
                    "bandage_limit_count": "0",
                },
            )
            prokat_pair = [v for v in [to_float(values[2]), to_float(values[3])] if v is not None]
            greben_pair = [v for v in [to_float(values[4]), to_float(values[5])] if v is not None]
            krut_pair = [v for v in [to_float(values[6]), to_float(values[7])] if v is not None]
            bandage_pair = [v for v in [to_float(values[8]), to_float(values[9])] if v is not None]
            _, _, resolved_left, resolved_right = resolve_archive_diameter_pair(
                cur,
                loco,
                measurement_date,
                row_index - 2,
                values,
                kp_cache,
            )
            diameter_pair = [v for v in [to_float(resolved_left), to_float(resolved_right)] if v is not None]

            if prokat_pair:
                current = to_float(stats["max_prokat"])
                stats["max_prokat"] = fmt_num(max(prokat_pair), True) if current is None else fmt_num(max([current, *prokat_pair]), True)
                if max(prokat_pair) >= 6:
                    stats["prokat_6_count"] = fmt_num((to_float(stats["prokat_6_count"]) or 0) + 1)
            if greben_pair:
                current = to_float(stats["min_greben"])
                stats["min_greben"] = fmt_num(min(greben_pair)) if current is None else fmt_num(min([current, *greben_pair]))
            if krut_pair:
                current = to_float(stats["min_krut"])
                stats["min_krut"] = fmt_num(min(krut_pair)) if current is None else fmt_num(min([current, *krut_pair]))
            if bandage_pair:
                current = to_float(stats["min_bandage_thickness"])
                stats["min_bandage_thickness"] = fmt_num(min(bandage_pair)) if current is None else fmt_num(min([current, *bandage_pair]))
            if diameter_pair:
                current_min = to_float(stats["min_diameter"])
                current_max = to_float(stats["max_diameter"])
                pair_min = min(diameter_pair)
                pair_max = max(diameter_pair)
                stats["min_diameter"] = fmt_num(pair_min) if current_min is None else fmt_num(min([current_min, *diameter_pair]))
                stats["max_diameter"] = fmt_num(pair_max) if current_max is None else fmt_num(max([current_max, *diameter_pair]))
                min_diameter = to_float(stats["min_diameter"])
                max_diameter = to_float(stats["max_diameter"])
                if min_diameter is not None and max_diameter is not None:
                    stats["max_diameter_diff"] = fmt_num(max_diameter - min_diameter)
            if bandage_pair:
                check_text = normalize_text(loco)
                is_limit = False
                if any(x in check_text for x in ["пэ-2м", "пэ2м", "пэ 2м", "pe-2m", "pe2m"]):
                    is_limit = any(v < 51 for v in bandage_pair)
                elif "тэм" in check_text or "tem" in check_text:
                    is_limit = any(v < 41 for v in bandage_pair)
                if is_limit:
                    stats["bandage_limit_count"] = fmt_num((to_float(stats["bandage_limit_count"]) or 0) + 1)

        def sort_key(item):
            (year, measurement_date, loco, repair_type, row_index), _ = item
            try:
                year_key = int(year)
            except Exception:
                year_key = 0
            try:
                date_key = int((measurement_date or "").replace("-", ""))
            except Exception:
                date_key = 0
            if sort_desc:
                return (-year_key, -date_key, loco, repair_type, row_index)
            return (year_key, date_key, loco, repair_type, row_index)

        archive_rows: list[dict] = []
        for (year, measurement_date, loco, repair_type, row_index), values in sorted(grouped.items(), key=sort_key):
            if search_text:
                probe = " ".join(
                    [
                        text(year),
                        measurement_date,
                        loco,
                        repair_type,
                        *[text(v) for v in values],
                    ]
                ).lower()
                if search_text not in probe:
                    continue

            formatted_date = measurement_date
            if measurement_date and len(measurement_date) >= 10:
                parts = measurement_date.split("-")
                if len(parts) == 3:
                    formatted_date = f"{parts[2]}.{parts[1]}.{parts[0][-2:]}"

            date_and_repair = f"{loco}\n{formatted_date}"
            if repair_type:
                date_and_repair += f"\n{normalize_repair_type(repair_type)}"

            section_value = values[0] or "1"
            stats = stats_by_section.get((year, measurement_date, loco, normalize_repair_type(repair_type), section_value), {})
            _, _, resolved_left, resolved_right = resolve_archive_diameter_pair(
                cur,
                loco,
                measurement_date,
                row_index - 2,
                values,
                kp_cache,
            )
            row_values = [
                date_and_repair,
                section_value,
                stats.get("max_prokat", ""),
                stats.get("min_greben", ""),
                stats.get("min_krut", ""),
                stats.get("min_bandage_thickness", ""),
                stats.get("max_diameter_diff", ""),
                stats.get("bandage_limit_count", "0"),
                stats.get("prokat_6_count", "0"),
                values[1],
                fmt_raw(values[2], is_prokat=True),
                fmt_raw(values[3], is_prokat=True),
                fmt_raw(values[4]),
                fmt_raw(values[5]),
                fmt_raw(values[6]),
                fmt_raw(values[7]),
                fmt_raw(values[8]),
                fmt_raw(values[9]),
                fmt_raw(resolved_left),
                fmt_raw(resolved_right),
            ]
            archive_rows.append({
                "values": row_values,
                "year": year,
                "measurement_date": measurement_date,
                "locomotive": loco,
                "repair_type": normalize_repair_type(repair_type),
                "source_r": row_index,
                "section": section_value,
                "stats": stats,
            })

        return archive_rows


def format_trend_number(value: float | int | None) -> str:
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
    value = text(value).strip()
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        parts = value.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return value


def _wear_trend_compare(metric_key: str, latest: float | None, previous: float | None) -> tuple[str, float | None]:
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


def _wear_session_metrics(values: list[str]) -> dict[str, dict[str, float | None] | float | None]:
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


def load_wear_analysis_rows(locomotive: str = "", date_from: str = "", date_to: str = "") -> dict:
    date_from = text(date_from).strip()
    date_to = text(date_to).strip()
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_locomotives(cur)
        selected = text(locomotive).strip()
        if not selected and locomotives:
            selected = text(locomotives[0].get("number")).strip()

        locomotive_record = next((item for item in locomotives if text(item.get("number")).strip() == selected), None)
        series = series_for_locomotive(cur, selected)
        axis_count = locomotive_axis_count(series, selected)
        wheel_pair_count = int(locomotive_record.get("wheelPairCount") or 0) if locomotive_record else 0
        if wheel_pair_count <= 0:
            wheel_pair_count = axis_count or 12
        wheel_pair_count = max(1, wheel_pair_count)

        query = [
            "SELECT y, measurement_date, locomotive, repair_type, r, c, v",
            "FROM archive_data",
            "WHERE locomotive=? AND TRIM(COALESCE(measurement_date, '')) <> ''",
        ]
        params: list[str] = [selected]
        if date_from:
            query.append("AND measurement_date >= ?")
            params.append(date_from)
        if date_to:
            query.append("AND measurement_date <= ?")
            params.append(date_to)
        query.append("ORDER BY measurement_date ASC, y ASC, repair_type ASC, r ASC, c ASC")
        rows = cur.execute("\n".join(query), params).fetchall()

        sessions: dict[tuple[str, str, int], dict[str, object]] = {}
        for row in rows:
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
            chart_pairs.append(
                {
                    "wheel_pair": pair_number,
                    "points": points,
                }
            )

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
                                value = metric_value.get(side)
                                if value is not None:
                                    history.append(value)
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
            result_rows.append(
                {
                    "wheel_pair": pair_number,
                    "session_count": len(pair_sessions),
                    "last_measurement_date": text(last_session.get("measurement_date") if last_session else "").strip(),
                    "last_repair_type": text(last_session.get("repair_type") if last_session else "").strip(),
                    "status_key": status_key,
                    "status_label": status_label,
                    "metrics": metric_payload,
                }
            )

        return {
            "locomotive": selected,
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


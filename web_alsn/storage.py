from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Обеспечиваем доступность корня проекта для системных импортов
_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import connect_sqlite

try:
    from .constants import DATA_DIR, DB_FILE, DB_LOCK
except (ImportError, ValueError):
    from constants import DATA_DIR, DB_FILE, DB_LOCK


@contextmanager
def conn_ctx() -> Generator[sqlite3.Connection, None, None]:
    """Безопасный контекстный менеджер SQLite соединения с оптимизированными настройками."""
    connection = connect_sqlite(DB_FILE)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
    finally:
        connection.close()


def blank_device_rows(count: int = 5) -> list[dict[str, str]]:
    """Создание пустых строк для приборов локомотива."""
    return [{"type": "", "number": ""} for _ in range(max(1, count))]


def parse_devices_json(value) -> list[dict[str, str]]:
    """Безопасный разбор JSON со списком приборов локомотива с сохранением ведущих нулей."""
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    normalized = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        t_val = row.get("type")
        n_val = row.get("number")
        normalized.append({
            "type": str("" if t_val is None else t_val).strip(),
            "number": str("" if n_val is None else n_val).strip(),
        })
    return normalized or blank_device_rows()


def normalize_warehouse_rows(rows: list | None) -> list[dict[str, str]]:
    """Нормализация строк склада приборов с сохранением ведущих нулей в номерах."""
    normalized = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            t_val = row.get("type")
            n_val = row.get("number")
            vd_val = row.get("verification_date")
            p_val = row.get("periodicity")
            nvd_val = row.get("next_verification_date")
            loc_val = row.get("location")
            rep_val = row.get("in_repair")
            u_val = row.get("updated_at")
            normalized.append({
                "type": str("" if t_val is None else t_val).strip(),
                "number": str("" if n_val is None else n_val).strip(),
                "verification_date": str("" if vd_val is None else vd_val).strip(),
                "periodicity": str("" if p_val is None else p_val).strip(),
                "next_verification_date": str("" if nvd_val is None else nvd_val).strip(),
                "location": str("" if loc_val is None else loc_val).strip(),
                "in_repair": 1 if rep_val in (1, "1", True, "true", "True", "Да", "да", "В ремонте") else 0,
                "updated_at": str("" if u_val is None else u_val).strip(),
            })
    if not normalized:
        normalized.append({
            "type": "",
            "number": "",
            "verification_date": "",
            "periodicity": "",
            "next_verification_date": "",
            "location": "",
            "in_repair": 0,
            "updated_at": "",
        })
    return normalized


def normalize_locomotives(rows: list | None) -> list[dict]:
    """Нормализация строк локомотивов и их приборов с сохранением ведущих нулей."""
    normalized = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            devices = row.get("devices")
            if not isinstance(devices, list):
                devices = []
            s_val = row.get("series")
            n_val = row.get("number")
            inv_val = row.get("inventory_num")
            note_val = row.get("note")
            normalized.append({
                "series": str("" if s_val is None else s_val).strip(),
                "number": str("" if n_val is None else n_val).strip(),
                "inventory_num": str("" if inv_val is None else inv_val).strip(),
                "note": str("" if note_val is None else note_val).strip(),
                "devices": [
                    {
                        "type": str("" if d.get("type") is None else d.get("type")).strip(),
                        "number": str("" if d.get("number") is None else d.get("number")).strip(),
                    }
                    for d in devices
                    if isinstance(d, dict)
                ] or blank_device_rows(),
            })
    if not normalized:
        normalized.append({
            "series": "",
            "number": "",
            "inventory_num": "",
            "note": "",
            "devices": blank_device_rows(),
        })
    return normalized


def init_db() -> None:
    """Инициализация таблиц базы данных и создание индексов для быстродействия."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, conn_ctx() as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS locomotives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL,
                    series TEXT NOT NULL DEFAULT '',
                    number TEXT NOT NULL DEFAULT '',
                    inventory_num TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    devices_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS warehouse (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL,
                    type TEXT NOT NULL DEFAULT '',
                    number TEXT NOT NULL DEFAULT '',
                    verification_date TEXT NOT NULL DEFAULT '',
                    periodicity TEXT NOT NULL DEFAULT '',
                    next_verification_date TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    in_repair INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # Индексы для быстрой выборки с сортировкой
            conn.execute("CREATE INDEX IF NOT EXISTS idx_locomotives_sort ON locomotives(sort_order, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_sort ON warehouse(sort_order, id)")

            cur = conn.cursor()
            wh_cols = [r[1] for r in cur.execute("PRAGMA table_info(warehouse)").fetchall()]
            if "in_repair" not in wh_cols:
                conn.execute("ALTER TABLE warehouse ADD COLUMN in_repair INTEGER NOT NULL DEFAULT 0")
            if "updated_at" not in wh_cols:
                conn.execute("ALTER TABLE warehouse ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

            cur.execute("SELECT COUNT(*) FROM locomotives")
            if int(cur.fetchone()[0] or 0) == 0:
                conn.execute(
                    "INSERT INTO locomotives(sort_order, series, number, inventory_num, note, devices_json) VALUES(?,?,?,?,?,?)",
                    (1, "", "", "", "", "[]"),
                )

            cur.execute("SELECT COUNT(*) FROM warehouse")
            if int(cur.fetchone()[0] or 0) == 0:
                conn.execute(
                    "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location, in_repair, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (1, "", "", "", "", "", "", 0, ""),
                )


def load_state_from_db() -> dict:
    """Загрузка полного актуального состояния локомотивов и склада из базы данных."""
    with DB_LOCK, conn_ctx() as conn:
        cur = conn.cursor()
        locomotives = [
            {
                "series": row["series"],
                "number": row["number"],
                "inventory_num": row["inventory_num"],
                "note": row["note"],
                "devices": parse_devices_json(row["devices_json"]),
            }
            for row in cur.execute(
                "SELECT series, number, inventory_num, note, devices_json FROM locomotives ORDER BY sort_order, id"
            ).fetchall()
        ]
        wh_cols = [r[1] for r in cur.execute("PRAGMA table_info(warehouse)").fetchall()]
        has_in_repair = "in_repair" in wh_cols
        has_updated_at = "updated_at" in wh_cols
        cols_query = "type, number, verification_date, periodicity, next_verification_date, location"
        if has_in_repair:
            cols_query += ", in_repair"
        if has_updated_at:
            cols_query += ", updated_at"
        warehouse = [
            {
                "type": row["type"],
                "number": row["number"],
                "verification_date": row["verification_date"],
                "periodicity": row["periodicity"],
                "next_verification_date": row["next_verification_date"],
                "location": row["location"],
                "in_repair": int(row["in_repair"]) if has_in_repair and row["in_repair"] else 0,
                "updated_at": row["updated_at"] if has_updated_at else "",
            }
            for row in cur.execute(
                f"SELECT {cols_query} FROM warehouse ORDER BY sort_order, id"
            ).fetchall()
        ]
    return {"locomotives": locomotives, "warehouse": warehouse}


def save_state_to_db(locomotives: list[dict], warehouse: list[dict]) -> None:
    """Строго атомарное сохранение локомотивов и склада в БД с автоматическим откатом при ошибках."""
    with DB_LOCK, conn_ctx() as conn:
        with conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM locomotives")
            cur.execute("DELETE FROM warehouse")
            cur.executemany(
                "INSERT INTO locomotives(sort_order, series, number, inventory_num, note, devices_json) VALUES(?,?,?,?,?,?)",
                [
                    (
                        idx + 1,
                        row["series"],
                        row["number"],
                        row["inventory_num"],
                        row["note"],
                        json.dumps(row["devices"], ensure_ascii=False),
                    )
                    for idx, row in enumerate(locomotives)
                ],
            )
            cur.executemany(
                "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location, in_repair, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (
                        idx + 1,
                        row["type"],
                        row["number"],
                        row["verification_date"],
                        row["periodicity"],
                        row["next_verification_date"],
                        row["location"],
                        int(row.get("in_repair") or 0),
                        row.get("updated_at", ""),
                    )
                    for idx, row in enumerate(warehouse)
                ],
            )

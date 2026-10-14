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
    """Безопасный разбор JSON со списком приборов локомотива."""
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
        normalized.append({
            "type": str(row.get("type", "") or "").strip(),
            "number": str(row.get("number", "") or "").strip(),
        })
    return normalized or blank_device_rows()


def normalize_warehouse_rows(rows: list | None) -> list[dict[str, str]]:
    """Нормализация строк склада приборов."""
    normalized = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized.append({
                "type": str(row.get("type", "") or "").strip(),
                "number": str(row.get("number", "") or "").strip(),
                "verification_date": str(row.get("verification_date", "") or "").strip(),
                "periodicity": str(row.get("periodicity", "") or "").strip(),
                "next_verification_date": str(row.get("next_verification_date", "") or "").strip(),
                "location": str(row.get("location", "") or "").strip(),
            })
    if not normalized:
        normalized.append({
            "type": "",
            "number": "",
            "verification_date": "",
            "periodicity": "",
            "next_verification_date": "",
            "location": "",
        })
    return normalized


def normalize_locomotives(rows: list | None) -> list[dict]:
    """Нормализация строк локомотивов и их приборов."""
    normalized = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            devices = row.get("devices")
            if not isinstance(devices, list):
                devices = []
            normalized.append({
                "series": str(row.get("series", "") or "").strip(),
                "number": str(row.get("number", "") or "").strip(),
                "inventory_num": str(row.get("inventory_num", "") or "").strip(),
                "note": str(row.get("note", "") or "").strip(),
                "devices": [
                    {
                        "type": str(d.get("type", "") or "").strip(),
                        "number": str(d.get("number", "") or "").strip(),
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
                    location TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # Индексы для быстрой выборки с сортировкой
            conn.execute("CREATE INDEX IF NOT EXISTS idx_locomotives_sort ON locomotives(sort_order, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_sort ON warehouse(sort_order, id)")

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM locomotives")
            if int(cur.fetchone()[0] or 0) == 0:
                conn.execute(
                    "INSERT INTO locomotives(sort_order, series, number, inventory_num, note, devices_json) VALUES(?,?,?,?,?,?)",
                    (1, "", "", "", "", "[]"),
                )

            cur.execute("SELECT COUNT(*) FROM warehouse")
            if int(cur.fetchone()[0] or 0) == 0:
                conn.execute(
                    "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location) VALUES(?,?,?,?,?,?,?)",
                    (1, "", "", "", "", "", ""),
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
        warehouse = [
            {
                "type": row["type"],
                "number": row["number"],
                "verification_date": row["verification_date"],
                "periodicity": row["periodicity"],
                "next_verification_date": row["next_verification_date"],
                "location": row["location"],
            }
            for row in cur.execute(
                "SELECT type, number, verification_date, periodicity, next_verification_date, location FROM warehouse ORDER BY sort_order, id"
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
                "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location) VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        idx + 1,
                        row["type"],
                        row["number"],
                        row["verification_date"],
                        row["periodicity"],
                        row["next_verification_date"],
                        row["location"],
                    )
                    for idx, row in enumerate(warehouse)
                ],
            )

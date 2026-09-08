import json
import sqlite3
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="График Отпусков")
ROOT = Path(__file__).resolve().parent
COMMON_DB_FILE = ROOT.parent / "base" / "common_database.db"
DB_LOCK = Lock()

APP_PREFIX = "/otpusk"

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=ROOT / "static"), name="otpusk_static")

DEFAULT_HOLIDAYS = [
    {"month": 0, "name": "Январь", "totalDays": 31, "dates": "1, 2, 3, 4, 5, 6, 7, 8"},
    {"month": 1, "name": "Февраль", "totalDays": 28, "dates": ""},
    {"month": 2, "name": "Март", "totalDays": 31, "dates": "8"},
    {"month": 3, "name": "Апрель", "totalDays": 30, "dates": ""},
    {"month": 4, "name": "Май", "totalDays": 31, "dates": "1, 9"},
    {"month": 5, "name": "Июнь", "totalDays": 30, "dates": "12"},
    {"month": 6, "name": "Июль", "totalDays": 31, "dates": ""},
    {"month": 7, "name": "Август", "totalDays": 31, "dates": ""},
    {"month": 8, "name": "Сентябрь", "totalDays": 30, "dates": ""},
    {"month": 9, "name": "Октябрь", "totalDays": 31, "dates": ""},
    {"month": 10, "name": "Ноябрь", "totalDays": 30, "dates": "4"},
    {"month": 11, "name": "Декабрь", "totalDays": 31, "dates": ""}
]

def init_db():
    COMMON_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacations_schedule (
                y INTEGER NOT NULL,
                tab_num TEXT NOT NULL,
                name TEXT NOT NULL,
                vacations_json TEXT NOT NULL,
                PRIMARY KEY (y, tab_num)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacation_holidays (
                y INTEGER PRIMARY KEY,
                holidays_json TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacations_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                y INTEGER NOT NULL,
                tab_num TEXT DEFAULT '',
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                days INTEGER DEFAULT 0,
                note TEXT DEFAULT ''
            )
        """)
        conn.commit()

        # Migrate existing JSON files into SQLite if DB table is empty
        cur.execute("SELECT COUNT(*) FROM vacations_schedule WHERE y=2026")
        if cur.fetchone()[0] == 0:
            saved_file = ROOT / "data" / "vacations.json"
            if not saved_file.exists():
                saved_file = ROOT / "data" / "mock_data.json"
            if saved_file.exists():
                try:
                    with open(saved_file, "r", encoding="utf-8") as f:
                        items = json.load(f)
                        for item in items:
                            t_num = str(item.get("tab_num") or item.get("name") or "")
                            e_name = str(item.get("name") or "")
                            v_json = json.dumps(item.get("vacations", []), ensure_ascii=False)
                            if t_num:
                                cur.execute(
                                    "INSERT OR REPLACE INTO vacations_schedule (y, tab_num, name, vacations_json) VALUES (?, ?, ?, ?)",
                                    (2026, t_num, e_name, v_json)
                                )
                    conn.commit()
                except Exception as e:
                    print("Migration error for vacations:", e)

        cur.execute("SELECT COUNT(*) FROM vacation_holidays WHERE y=2026")
        if cur.fetchone()[0] == 0:
            holidays_file = ROOT / "data" / "holidays.json"
            h_data = DEFAULT_HOLIDAYS
            if holidays_file.exists():
                try:
                    with open(holidays_file, "r", encoding="utf-8") as f:
                        h_data = json.load(f)
                except Exception:
                    pass
            cur.execute(
                "INSERT OR REPLACE INTO vacation_holidays (y, holidays_json) VALUES (?, ?)",
                (2026, json.dumps(h_data, ensure_ascii=False))
            )
            conn.commit()

init_db()

@app.get("/", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse)
async def read_root():
    index_file = ROOT / "templates" / "index.html"
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/vacations")
@app.get(f"{APP_PREFIX}/api/vacations")
async def get_vacations(year: int = 2026):
    employees = []
    saved_vacations = {}
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        emp_rows = cur.execute(
            "SELECT rowid, pos, name, full_name, tab_num, vacation_days FROM employees WHERE y=? ORDER BY rowid",
            (year,)
        ).fetchall()
        if not emp_rows:
            emp_rows = cur.execute(
                "SELECT rowid, pos, name, full_name, tab_num, vacation_days FROM employees ORDER BY rowid"
            ).fetchall()
        employees = [dict(r) for r in emp_rows]

        vac_rows = cur.execute(
            "SELECT tab_num, name, vacations_json FROM vacations_schedule WHERE y=?",
            (year,)
        ).fetchall()
        for v_row in vac_rows:
            try:
                v_list = json.loads(v_row["vacations_json"] or "[]")
            except Exception:
                v_list = []
            if v_row["tab_num"]:
                saved_vacations[str(v_row["tab_num"])] = v_list
            if v_row["name"]:
                saved_vacations[str(v_row["name"])] = v_list

    result = []
    for idx, emp in enumerate(employees, 1):
        emp_name = emp.get("name") or emp.get("full_name") or ""
        tab_num = str(emp.get("tab_num") or "")
        vacations = saved_vacations.get(tab_num) or saved_vacations.get(emp_name) or []
        v_days = int(emp.get("vacation_days")) if emp.get("vacation_days") is not None else 28
        result.append({
            "id": idx,
            "tab_num": tab_num,
            "name": emp_name,
            "full_name": emp.get("full_name") or emp_name,
            "position": emp.get("pos") or "",
            "vacation_days": v_days,
            "vacations": vacations
        })

    if not result:
        mock_file = ROOT / "data" / "mock_data.json"
        if mock_file.exists():
            try:
                with open(mock_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

    return result

@app.post("/api/vacations")
@app.post(f"{APP_PREFIX}/api/vacations")
async def save_vacations(request: Request):
    items = await request.json()
    year = 2026
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        for item in items:
            t_num = str(item.get("tab_num") or item.get("name") or "")
            e_name = str(item.get("name") or "")
            v_json = json.dumps(item.get("vacations", []), ensure_ascii=False)
            if t_num:
                cur.execute(
                    "INSERT OR REPLACE INTO vacations_schedule (y, tab_num, name, vacations_json) VALUES (?, ?, ?, ?)",
                    (year, t_num, e_name, v_json)
                )
        conn.commit()
    return {"status": "success"}

@app.get("/api/holidays")
@app.get(f"{APP_PREFIX}/api/holidays")
async def get_holidays(year: int = 2026):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute("SELECT holidays_json FROM vacation_holidays WHERE y=?", (year,)).fetchone()
        if row and row["holidays_json"]:
            try:
                return json.loads(row["holidays_json"])
            except Exception:
                pass
    return DEFAULT_HOLIDAYS

@app.post("/api/holidays")
@app.post(f"{APP_PREFIX}/api/holidays")
async def save_holidays(request: Request):
    data = await request.json()
    year = 2026
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO vacation_holidays (y, holidays_json) VALUES (?, ?)",
            (year, json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
    return {"status": "success"}

@app.get("/api/vacations/archive")
@app.get(f"{APP_PREFIX}/api/vacations/archive")
async def get_archive():
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, y, tab_num, name, start_date, end_date, days, note FROM vacations_archive ORDER BY y DESC, name ASC"
        ).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/vacations/archive")
@app.post(f"{APP_PREFIX}/api/vacations/archive")
async def save_archive(request: Request):
    items = await request.json()
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vacations_archive")
        for item in items:
            cur.execute(
                """
                INSERT INTO vacations_archive (y, tab_num, name, start_date, end_date, days, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(item.get("y") or 2025),
                    str(item.get("tab_num") or ""),
                    str(item.get("name") or ""),
                    str(item.get("start_date") or ""),
                    str(item.get("end_date") or ""),
                    int(item.get("days") or 0),
                    str(item.get("note") or "")
                )
            )
        conn.commit()
    return {"status": "success"}

if __name__ == "__main__":
    import os
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8085"))
    uvicorn.run("app:app", host=host, port=port, reload=False)

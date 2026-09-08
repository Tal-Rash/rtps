import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, Request, HTTPException
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS vacation_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                y INTEGER NOT NULL,
                version_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                data_json TEXT NOT NULL
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

def is_employee_excluded_for_year(emp: dict, target_year: int) -> bool:
    is_exc = int(emp.get("is_excluded") or 0)
    exc_date_str = str(emp.get("exclude_date") or "").strip()
    exc_year = None
    if exc_date_str:
        parts = exc_date_str.replace("/", ".").replace("-", ".").split(".")
        for part in parts:
            part = part.strip()
            if len(part) == 4 and part.isdigit():
                exc_year = int(part)
                break

    if exc_year is not None:
        if exc_year < target_year:
            return True
    elif is_exc == 1:
        return True

    return False

@app.get("/api/vacations")
@app.get(f"{APP_PREFIX}/api/vacations")
async def get_vacations(year: int = 2026):
    employees = []
    saved_vacations = {}
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            emp_rows = cur.execute(
                "SELECT rowid, pos, name, full_name, tab_num, vacation_days, is_excluded, exclude_date, hire_date FROM employees WHERE y=? ORDER BY rowid",
                (year,)
            ).fetchall()
        except Exception:
            emp_rows = cur.execute(
                "SELECT rowid, * FROM employees WHERE y=? ORDER BY rowid",
                (year,)
            ).fetchall()

        if not emp_rows:
            try:
                emp_rows = cur.execute(
                    "SELECT rowid, pos, name, full_name, tab_num, vacation_days, is_excluded, exclude_date, hire_date FROM employees ORDER BY rowid"
                ).fetchall()
            except Exception:
                emp_rows = cur.execute(
                    "SELECT rowid, * FROM employees ORDER BY rowid"
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

        prev_vac_rows = cur.execute(
            "SELECT tab_num, name, vacations_json FROM vacations_schedule WHERE y=?",
            (year - 1,)
        ).fetchall()
        prev_saved_vacations = {}
        for p_row in prev_vac_rows:
            try:
                p_list = json.loads(p_row["vacations_json"] or "[]")
            except Exception:
                p_list = []
            if p_row["tab_num"]:
                prev_saved_vacations[str(p_row["tab_num"])] = p_list
            if p_row["name"]:
                prev_saved_vacations[str(p_row["name"])] = p_list

    result = []
    jan_prefix = f"{year}-01-"
    for emp in employees:
        if is_employee_excluded_for_year(emp, year):
            continue

        emp_name = emp.get("name") or emp.get("full_name") or ""
        tab_num = str(emp.get("tab_num") or "")
        vacations = saved_vacations.get(tab_num) or saved_vacations.get(emp_name) or []
        prev_vacs = prev_saved_vacations.get(tab_num) or prev_saved_vacations.get(emp_name) or []
        
        carried_over = []
        for pv in prev_vacs:
            s_date = str(pv.get("start") or "")
            e_date = str(pv.get("end") or "")
            if s_date.startswith(jan_prefix) or e_date.startswith(jan_prefix):
                carried_over.append(pv)

        v_days = int(emp.get("vacation_days")) if emp.get("vacation_days") is not None else 28
        result.append({
            "id": len(result) + 1,
            "tab_num": tab_num,
            "name": emp_name,
            "full_name": emp.get("full_name") or emp_name,
            "position": emp.get("pos") or "",
            "vacation_days": v_days,
            "vacations": vacations,
            "carried_over_vacations": carried_over
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
async def save_vacations(request: Request, year: int = 2026):
    items = await request.json()
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
async def save_holidays(request: Request, year: int = 2026):
    data = await request.json()
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

@app.get("/api/versions")
@app.get(f"{APP_PREFIX}/api/versions")
async def get_versions(year: int = 2026):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, y, version_name, created_at FROM vacation_versions WHERE y=? ORDER BY id DESC",
            (year,)
        ).fetchall()
        return [dict(r) for r in rows]

@app.get("/api/versions/{version_id}")
@app.get(f"{APP_PREFIX}/api/versions/{version_id}")
async def get_version_detail(version_id: int):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, y, version_name, created_at, data_json FROM vacation_versions WHERE id=?",
            (version_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")
        res = dict(row)
        res["data"] = json.loads(res["data_json"] or "[]")
        return res

@app.post("/api/versions")
@app.post(f"{APP_PREFIX}/api/versions")
async def create_version(request: Request, year: int = 2026):
    payload = await request.json()
    v_name = (payload.get("version_name") or "").strip()
    v_data = payload.get("data") or []
    if not v_name:
        v_name = f"Версия от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vacation_versions (y, version_name, created_at, data_json) VALUES (?, ?, ?, ?)",
            (year, v_name, created_at, json.dumps(v_data, ensure_ascii=False))
        )
        conn.commit()
        new_id = cur.lastrowid
        return {"status": "ok", "id": new_id, "version_name": v_name, "created_at": created_at}

@app.delete("/api/versions/{version_id}")
@app.delete(f"{APP_PREFIX}/api/versions/{version_id}")
async def delete_version(version_id: int):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM vacation_versions WHERE id=?", (version_id,))
        conn.commit()
        return {"status": "ok"}

if __name__ == "__main__":
    import os
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8085"))
    uvicorn.run("app:app", host=host, port=port, reload=False)

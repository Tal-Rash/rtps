import json
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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

def format_date_to_iso(date_str: str) -> str:
    if not date_str:
        return ""
    date_str = date_str.strip()
    if "-" in date_str:
        parts = date_str.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return date_str
    if "." in date_str:
        parts = date_str.split(".")
        if len(parts) == 3:
            d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{m}-{d}"
    return date_str

def is_same_person(name1: str, name2: str, tab1: str = "", tab2: str = "") -> bool:
    t1 = str(tab1 or "").strip()
    t2 = str(tab2 or "").strip()
    if t1 and t2 and t1 == t2:
        return True

    n1 = str(name1 or "").replace('.', ' ').strip().split()
    n2 = str(name2 or "").replace('.', ' ').strip().split()

    if not n1 or not n2:
        return False

    if n1[0].lower() != n2[0].lower():
        return False

    if len(n1) > 1 and len(n2) > 1:
        if n1[1][0].lower() != n2[1][0].lower():
            return False

    if len(n1) > 2 and len(n2) > 2:
        if n1[2][0].lower() != n2[2][0].lower():
            return False

    return True

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

        # Query vacations_archive for current year (year) and previous year (year - 1)
        archive_rows = cur.execute(
            "SELECT y, tab_num, name, start_date, end_date, days FROM vacations_archive WHERE y=? OR y=?",
            (year, year - 1)
        ).fetchall()

        archive_items = []
        prev_archive_items = []
        for a_row in archive_rows:
            a_dict = dict(a_row)
            ay = a_dict.get("y")
            t_num = str(a_dict.get("tab_num") or "")
            a_name = str(a_dict.get("name") or "")
            s_iso = format_date_to_iso(a_dict.get("start_date") or "")
            e_iso = format_date_to_iso(a_dict.get("end_date") or "")
            days = int(a_dict.get("days") or 0)

            if s_iso and e_iso:
                entry = {
                    "name": a_name,
                    "tab_num": t_num,
                    "vacation": {"start": s_iso, "end": e_iso, "days": days}
                }
                if ay == year:
                    archive_items.append(entry)
                else:
                    prev_archive_items.append(entry)

    result = []
    jan_prefix = f"{year}-01-"
    processed_archive_names = set()

    for emp in employees:
        if is_employee_excluded_for_year(emp, year):
            continue

        emp_name = emp.get("name") or emp.get("full_name") or ""
        emp_full = emp.get("full_name") or ""
        tab_num = str(emp.get("tab_num") or "")

        vacations = saved_vacations.get(tab_num) or saved_vacations.get(emp_name) or []
        if not vacations:
            for ai in archive_items:
                if (tab_num and ai["tab_num"] and tab_num == ai["tab_num"]) or \
                   is_same_person(emp_name, ai["name"]) or \
                   (emp_full and is_same_person(emp_full, ai["name"])):
                    vacations.append(ai["vacation"])
                    processed_archive_names.add(ai["name"])

        prev_vacs = prev_saved_vacations.get(tab_num) or prev_saved_vacations.get(emp_name) or []
        
        prev_arc_vacs = []
        for pai in prev_archive_items:
            if (tab_num and pai["tab_num"] and tab_num == pai["tab_num"]) or \
               is_same_person(emp_name, pai["name"]) or \
               (emp_full and is_same_person(emp_full, pai["name"])):
                prev_arc_vacs.append(pai["vacation"])

        all_prev_vacs = prev_vacs + prev_arc_vacs

        carried_over = []
        seen_cov = set()
        for pv in all_prev_vacs:
            s_date = str(pv.get("start") or "")
            e_date = str(pv.get("end") or "")
            if s_date.startswith(jan_prefix) or e_date.startswith(jan_prefix):
                key = f"{s_date}_{e_date}"
                if key not in seen_cov:
                    seen_cov.add(key)
                    carried_over.append(pv)

        v_days = int(emp.get("vacation_days")) if emp.get("vacation_days") is not None else 28
        result.append({
            "id": len(result) + 1,
            "tab_num": tab_num,
            "name": emp_name,
            "full_name": emp_full or emp_name,
            "position": emp.get("pos") or "",
            "vacation_days": v_days,
            "vacations": vacations,
            "carried_over_vacations": carried_over
        })

    # Only add archive entries for year if they belong to a completely NEW person not matched above
    for ai in archive_items:
        a_name = ai["name"]
        a_tab = ai["tab_num"]
        
        already_matched = False
        for emp in employees:
            e_name = emp.get("name") or emp.get("full_name") or ""
            e_full = emp.get("full_name") or ""
            e_tab = str(emp.get("tab_num") or "")
            if (a_tab and e_tab and a_tab == e_tab) or \
               is_same_person(e_name, a_name) or \
               (e_full and is_same_person(e_full, a_name)):
                already_matched = True
                break

        if not already_matched and a_name not in processed_archive_names:
            processed_archive_names.add(a_name)
            person_vacs = [x["vacation"] for x in archive_items if is_same_person(a_name, x["name"])]
            
            carried_over = []
            seen_cov = set()
            for pai in prev_archive_items:
                if is_same_person(a_name, pai["name"]):
                    pv = pai["vacation"]
                    s_date = str(pv.get("start") or "")
                    e_date = str(pv.get("end") or "")
                    if s_date.startswith(jan_prefix) or e_date.startswith(jan_prefix):
                        key = f"{s_date}_{e_date}"
                        if key not in seen_cov:
                            seen_cov.add(key)
                            carried_over.append(pv)

            result.append({
                "id": len(result) + 1,
                "tab_num": a_tab if a_tab.isdigit() else "",
                "name": a_name,
                "full_name": a_name,
                "position": "",
                "vacation_days": 28,
                "vacations": person_vacs,
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

def create_archive_excel(rows_data: list, title: str = "Архив отпусков") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Архив отпусков"
    ws.views.sheetView[0].showGridLines = True

    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="276EF1", end_color="276EF1", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    
    thin_border = Border(
        left=Side(style='thin', color='D0D7DE'),
        right=Side(style='thin', color='D0D7DE'),
        top=Side(style='thin', color='D0D7DE'),
        bottom=Side(style='thin', color='D0D7DE')
    )

    headers = ["Год", "Сотрудник", "Табельный номер", "Дата начала", "Дата окончания", "Дней отпуска", "Примечание"]
    ws.append(headers)

    header_row = ws[1]
    ws.row_dimensions[1].height = 28
    for cell in header_row:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    data_font = Font(name="Segoe UI", size=10)
    
    for row_idx, r in enumerate(rows_data, 2):
        ws.append([
            r.get("y", 2025),
            r.get("name", ""),
            r.get("tab_num", ""),
            r.get("start_date", ""),
            r.get("end_date", ""),
            r.get("days", 0),
            r.get("note", "")
        ])
        ws.row_dimensions[row_idx].height = 22
        
        row_cells = ws[row_idx]
        for c_idx, cell in enumerate(row_cells, 1):
            cell.font = data_font
            cell.border = thin_border
            if c_idx in (1, 3, 4, 5, 6):
                cell.alignment = center_align
            else:
                cell.alignment = left_align

    col_widths = {1: 10, 2: 32, 3: 18, 4: 16, 5: 16, 6: 15, 7: 35}
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

@app.get("/api/vacations/archive/export")
@app.get(f"{APP_PREFIX}/api/vacations/archive/export")
async def export_archive():
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT y, tab_num, name, start_date, end_date, days, note FROM vacations_archive ORDER BY y DESC, name ASC"
        ).fetchall()
        rows_data = [dict(r) for r in rows]

    excel_bytes = create_archive_excel(rows_data, title="Архив отпусков")
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vacations_archive.xlsx"}
    )

@app.get("/api/vacations/archive/template")
@app.get(f"{APP_PREFIX}/api/vacations/archive/template")
async def template_archive():
    sample_data = [
        {
            "y": 2025,
            "name": "Иванов Иван Иванович",
            "tab_num": "4001234",
            "start_date": "15.01.2025",
            "end_date": "28.01.2025",
            "days": 14,
            "note": "Ежегодный основной"
        },
        {
            "y": 2025,
            "name": "Петров Петр Петрович",
            "tab_num": "4005678",
            "start_date": "10.05.2025",
            "end_date": "23.05.2025",
            "days": 14,
            "note": "Дополнительный"
        }
    ]
    excel_bytes = create_archive_excel(sample_data, title="Шаблон архива")
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vacations_archive_template.xlsx"}
    )

@app.post("/api/vacations/archive/import")
@app.post(f"{APP_PREFIX}/api/vacations/archive/import")
async def import_archive(file: UploadFile = File(...), mode: str = "append"):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате Excel (.xlsx)")

    contents = await file.read()
    buffer = BytesIO(contents)

    try:
        wb = openpyxl.load_workbook(buffer, data_only=True)
        ws = wb.active
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка чтения Excel файла: {str(e)}")

    imported_items = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not any(row):
            continue

        def val(idx, default=""):
            if idx < len(row) and row[idx] is not None:
                v = row[idx]
                if isinstance(v, datetime):
                    return v.strftime("%Y-%m-%d")
                return str(v).strip()
            return str(default)

        def int_val(idx, default=0):
            try:
                v = val(idx, default)
                return int(float(v))
            except Exception:
                return default

        y_val = int_val(0, 2025)
        name_val = val(1, "")
        tab_val = val(2, "")
        s_date = val(3, "")
        e_date = val(4, "")
        days_val = int_val(5, 0)
        note_val = val(6, "")

        if name_val or tab_val or s_date:
            imported_items.append({
                "y": y_val,
                "name": name_val,
                "tab_num": tab_val,
                "start_date": s_date,
                "end_date": e_date,
                "days": days_val,
                "note": note_val
            })

    if not imported_items:
        raise HTTPException(status_code=400, detail="В файле не найдено строк с данными.")

    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        if mode == "replace":
            cur.execute("DELETE FROM vacations_archive")

        for item in imported_items:
            cur.execute(
                """
                INSERT INTO vacations_archive (y, tab_num, name, start_date, end_date, days, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["y"],
                    item["tab_num"],
                    item["name"],
                    item["start_date"],
                    item["end_date"],
                    item["days"],
                    item["note"]
                )
            )
        conn.commit()

    return {"status": "success", "imported_count": len(imported_items)}

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
@app.get(APP_PREFIX + "/api/versions/{version_id}")
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
@app.delete(APP_PREFIX + "/api/versions/{version_id}")
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

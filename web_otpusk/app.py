import json
import re
import sqlite3
from datetime import datetime, date, timedelta
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
        # Гарантируем наличие колонки is_active в таблице vacation_versions
        try:
            ver_cols = [c[1] for c in cur.execute("PRAGMA table_info(vacation_versions)").fetchall()]
            if "is_active" not in ver_cols:
                cur.execute("ALTER TABLE vacation_versions ADD COLUMN is_active INTEGER DEFAULT 0")
        except Exception:
            pass
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

def extract_year_from_date(date_str: str) -> int | None:
    """Извлекает 4-значный год из строки даты (поддерживает форматы YYYY-MM-DD, DD.MM.YYYY и др.)"""
    if not date_str:
        return None
    d_str = str(date_str).strip()
    parts = d_str.replace("/", ".").replace("-", ".").split(".")
    for part in parts:
        part = part.strip()
        if len(part) == 4 and part.isdigit():
            return int(part)
    return None

def is_employee_excluded_for_year(emp: dict, target_year: int) -> bool:
    """Проверяет, был ли сотрудник уволен более года назад относительно целевого года (показываем в год увольнения и на следующий год)"""
    exc_date_str = str(emp.get("exclude_date") or "").strip()
    exc_year = extract_year_from_date(exc_date_str)

    if exc_year is not None:
        # Показываем в год увольнения и на следующий год (исключаем только если прошло 2 года и более)
        if exc_year < target_year - 1:
            return True
    else:
        is_exc = int(emp.get("is_excluded") or 0)
        if is_exc == 1:
            return True

    return False

def format_date_to_iso(val) -> str:
    """Универсально преобразует любые варианты значения даты из Excel (datetime, date, serial float, тексты DD.MM.YYYY, YYYY-MM-DD и др.) в формат YYYY-MM-DD"""
    if val is None or val == "":
        return ""

    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")

    # Перевод числовых серийных дат Excel (например, 45443)
    if isinstance(val, (int, float)):
        try:
            if 30000 <= val <= 70000:
                dt = datetime(1899, 12, 30) + timedelta(days=float(val))
                return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    s = str(val).strip()
    if not s:
        return ""

    # Если передан численный серийный номер в виде строки, например "45443" или "45443.0"
    try:
        f_val = float(s)
        if 30000 <= f_val <= 70000:
            dt = datetime(1899, 12, 30) + timedelta(days=f_val)
            return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Приведение разделителей к точкам
    s_clean = s.replace("/", ".").replace("-", ".").replace(" ", "")
    parts = s_clean.split(".")

    if len(parts) == 3:
        p1, p2, p3 = parts[0].strip(), parts[1].strip(), parts[2].strip()

        # Формат YYYY.MM.DD
        if len(p1) == 4 and p1.isdigit():
            y = p1
            m = p2.zfill(2)
            d = p3.zfill(2)
            return f"{y}-{m}-{d}"

        # Формат DD.MM.YYYY или DD.MM.YY
        if len(p3) in (2, 4) and p3.isdigit():
            d = p1.zfill(2)
            m = p2.zfill(2)
            y = p3
            if len(y) == 2:
                y = "20" + y
            return f"{y}-{m}-{d}"

    return s

def normalize_tab(tab: str) -> str:
    if not tab:
        return ""
    return str(tab).strip().lstrip('0')

def is_same_person(name1: str, name2: str, tab1: str = "", tab2: str = "") -> bool:
    s1 = str(name1 or "").strip()
    s2 = str(name2 or "").strip()
    t1 = normalize_tab(tab1)
    t2 = normalize_tab(tab2)

    l1 = s1.lower()
    l2 = s2.lower()

    # Если заданы оба имени, проверяем, не разные ли это реальные люди
    if l1 and l2:
        is_anon1 = ("№" in l1 or "id_" in l1 or l1.isdigit())
        is_anon2 = ("№" in l2 or "id_" in l2 or l2.isdigit())
        if not is_anon1 and not is_anon2:
            p1 = l1.replace('.', ' ').split()
            p2 = l2.replace('.', ' ').split()
            if p1 and p2 and p1[0] != p2[0]:
                return False

    if t1 and t2:
        # Для шифров ID_00X проверяем также несовпадение реальных имен
        if t1.lower().startswith("id_") or t2.lower().startswith("id_"):
            if l1 and l2:
                is_anon1 = ("№" in l1 or "id_" in l1 or l1.isdigit())
                is_anon2 = ("№" in l2 or "id_" in l2 or l2.isdigit())
                if not is_anon1 and not is_anon2:
                    p1 = l1.replace('.', ' ').split()
                    p2 = l2.replace('.', ' ').split()
                    if p1 and p2 and p1[0] != p2[0]:
                        return False
            return t1 == t2
        return t1 == t2

    if not l1 or not l2:
        return False

    if l1 == l2:
        return True

    # Для плейсхолдеров анонимизации (Работник №1, СотрудникПолн №1, Сотрудник №1, ID_001)
    if ("№" in l1 or "id_" in l1) and ("№" in l2 or "id_" in l2):
        num1 = "".join(ch for ch in l1 if ch.isdigit())
        num2 = "".join(ch for ch in l2 if ch.isdigit())
        if num1 and num2:
            return int(num1) == int(num2)

    n1 = s1.replace('.', ' ').split()
    n2 = s2.replace('.', ' ').split()

    if not n1 or not n2:
        return False

    if n1[0] != n2[0]:
        return False

    if len(n1) > 1 and len(n2) > 1:
        if len(n1[1]) == 1 or len(n2[1]) == 1:
            if n1[1][0] != n2[1][0]:
                return False
        else:
            if n1[1] != n2[1]:
                return False

    if len(n1) > 2 and len(n2) > 2:
        if len(n1[2]) == 1 or len(n2[2]) == 1:
            if n1[2][0] != n2[2][0]:
                return False
        else:
            if n1[2] != n2[2]:
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

        # Объединяем со всеми актуальными сотрудниками из справочника (чтобы новые сотрудники сразу появлялись)
        existing_tabs = {str(r["tab_num"]) for r in emp_rows if r["tab_num"]}
        try:
            latest_rows = cur.execute("""
                SELECT e.rowid, e.pos, e.name, e.full_name, e.tab_num, e.vacation_days, e.is_excluded, e.exclude_date, e.hire_date
                FROM employees e
                INNER JOIN (
                    SELECT tab_num, MAX(y) as max_y FROM employees GROUP BY tab_num
                ) m ON e.tab_num = m.tab_num AND e.y = m.max_y
                ORDER BY e.rowid
            """).fetchall()
            combined = list(emp_rows)
            for r in latest_rows:
                t = str(r["tab_num"] or "")
                if t and t not in existing_tabs:
                    combined.append(r)
                    existing_tabs.add(t)
            emp_rows = combined
        except Exception:
            pass

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
    processed_archive_keys = set()

    for emp in employees:
        if is_employee_excluded_for_year(emp, year):
            continue

        emp_name = emp.get("name") or emp.get("full_name") or ""
        emp_full = emp.get("full_name") or ""
        tab_num = str(emp.get("tab_num") or "")
        pkey = tab_num or emp_name
        hire_date_str = str(emp.get("hire_date") or "").strip()
        hire_year = extract_year_from_date(hire_date_str)
        hire_iso = format_date_to_iso(hire_date_str)

        exc_date_str = str(emp.get("exclude_date") or "").strip()
        exc_year = extract_year_from_date(exc_date_str)
        exc_iso = format_date_to_iso(exc_date_str)

        vacations = saved_vacations.get(tab_num) or saved_vacations.get(emp_name) or []
        if not vacations:
            for ai in archive_items:
                s_iso = format_date_to_iso(ai["vacation"].get("start") or "")
                if hire_iso and s_iso and s_iso < hire_iso:
                    continue
                if exc_iso and s_iso and s_iso > exc_iso:
                    continue
                if is_same_person(emp_name, ai["name"], tab_num, ai["tab_num"]) or \
                   (emp_full and is_same_person(emp_full, ai["name"], tab_num, ai["tab_num"])):
                    vacations.append(ai["vacation"])
                    processed_archive_keys.add((ai["tab_num"], ai["name"]))

        # Проверяем дату приема на работу:
        # В предыдущие годы (до года приема) и в текущий год приема (если нет запланированного отпуска) сотрудник не отображается, только в следующих годах
        if hire_year is not None:
            if hire_year > year:
                continue
            if hire_year == year and not vacations:
                continue

        prev_vacs = prev_saved_vacations.get(pkey) or prev_saved_vacations.get(tab_num) or prev_saved_vacations.get(emp_name) or []
        
        prev_arc_vacs = []
        for pai in prev_archive_items:
            s_iso = format_date_to_iso(pai["vacation"].get("start") or "")
            if hire_iso and s_iso and s_iso < hire_iso:
                continue
            if exc_iso and s_iso and s_iso > exc_iso:
                continue
            if is_same_person(emp_name, pai["name"], tab_num, pai["tab_num"]) or \
               (emp_full and is_same_person(emp_full, pai["name"], tab_num, pai["tab_num"])):
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
        
        # Гарантированная защита от сбоя названий и привязка номера к табельному ID
        num_part = None
        if tab_num and tab_num.startswith("ID_"):
            digits = "".join(ch for ch in tab_num if ch.isdigit())
            if digits:
                num_part = int(digits)
        if num_part is None:
            num_part = len(result) + 1

        disp_tab = f"ID_{num_part:03d}"
        disp_name = f"Работник №{num_part}"
        disp_full = f"СотрудникПолн №{num_part}"
        disp_pos = f"Должность №{num_part}"

        result.append({
            "id": num_part,
            "tab_num": disp_tab,
            "name": disp_name,
            "full_name": disp_full,
            "position": disp_pos,
            "vacation_days": v_days,
            "vacations": vacations,
            "carried_over_vacations": carried_over,
            "exclude_date": exc_date_str,
            "is_excluded": int(emp.get("is_excluded") or 0) == 1,
            "is_quitting_this_year": bool(exc_year is not None and exc_year in (year, year - 1)),
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
            if is_same_person(e_name, a_name, e_tab, a_tab) or \
               (e_full and is_same_person(e_full, a_name, e_tab, a_tab)):
                already_matched = True
                break

        if not already_matched and (a_tab, a_name) not in processed_archive_keys:
            processed_archive_keys.add((a_tab, a_name))
            person_vacs = [x["vacation"] for x in archive_items if is_same_person(a_name, x["name"], a_tab, x["tab_num"])]
            
            carried_over = []
            seen_cov = set()
            for pai in prev_archive_items:
                if is_same_person(a_name, pai["name"], a_tab, pai["tab_num"]):
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
        emp_rows = cur.execute("SELECT tab_num, name, full_name FROM employees WHERE y=?", (year,)).fetchall()
        for item in items:
            t_num = str(item.get("tab_num") or "")
            e_name = str(item.get("name") or "")
            v_json = json.dumps(item.get("vacations", []), ensure_ascii=False)
            
            target_tab = t_num or e_name
            target_name = e_name

            for emp in emp_rows:
                if is_same_person(emp[1], e_name, emp[0], t_num) or is_same_person(emp[2], e_name, emp[0], t_num):
                    target_tab = emp[0]
                    target_name = emp[1]
                    break

            if target_tab:
                cur.execute(
                    "INSERT OR REPLACE INTO vacations_schedule (y, tab_num, name, vacations_json) VALUES (?, ?, ?, ?)",
                    (year, target_tab, target_name, v_json)
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

MONTH_NAMES_RU = {
    1: "янв", 2: "февр", 3: "март", 4: "апр", 5: "май", 6: "июнь",
    7: "июль", 8: "авг", 9: "сент", 10: "окт", 11: "нояб", 12: "дек"
}

def get_season(month: int, start_day: int = 1) -> str:
    """Определяет сезон месяца: лето (Май, Июнь, Июль, Август до 15 числа), зима (Ноябрь, Декабрь, Январь, Февраль) или демисезон"""
    if month in (5, 6, 7):
        return "summer"
    elif month == 8:
        # Если отпуск начинается с середины августа (с 15-го числа и позже), не считать его летним
        if start_day >= 15:
            return "other"
        return "summer"
    elif month in (11, 12, 1, 2):
        return "winter"
    else:
        return "other"

@app.get("/api/vacations/history_matrix")
@app.get(f"{APP_PREFIX}/api/vacations/history_matrix")
async def get_history_matrix(year: int = 2026):
    """Возвращает матрицу отпусков по годам для визуального анализа летних и сезонных отпусков сотрудников"""
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

        # Объединяем со всеми актуальными сотрудниками из справочника (чтобы новые сотрудники сразу появлялись)
        existing_tabs = {str(r["tab_num"]) for r in emp_rows if r["tab_num"]}
        try:
            latest_rows = cur.execute("""
                SELECT e.rowid, e.pos, e.name, e.full_name, e.tab_num, e.vacation_days, e.is_excluded, e.exclude_date, e.hire_date
                FROM employees e
                INNER JOIN (
                    SELECT tab_num, MAX(y) as max_y FROM employees GROUP BY tab_num
                ) m ON e.tab_num = m.tab_num AND e.y = m.max_y
                ORDER BY e.rowid
            """).fetchall()
            combined = list(emp_rows)
            for r in latest_rows:
                t = str(r["tab_num"] or "")
                if t and t not in existing_tabs:
                    combined.append(r)
                    existing_tabs.add(t)
            emp_rows = combined
        except Exception:
            pass

        employees = [dict(r) for r in emp_rows]

        arc_rows = cur.execute(
            "SELECT y, tab_num, name, start_date, end_date, days FROM vacations_archive ORDER BY y ASC, start_date ASC"
        ).fetchall()

        sched_rows = cur.execute(
            "SELECT y, tab_num, name, vacations_json FROM vacations_schedule ORDER BY y ASC"
        ).fetchall()

    years_set = set()
    archive_items = []

    for r in arc_rows:
        y = int(r["y"] or 0)
        if y > 0:
            years_set.add(y)
        archive_items.append(dict(r))

    for s in sched_rows:
        y = int(s["y"] or 0)
        if y > 0:
            years_set.add(y)
            try:
                v_list = json.loads(s["vacations_json"] or "[]")
                for v in v_list:
                    archive_items.append({
                        "y": y,
                        "tab_num": s["tab_num"],
                        "name": s["name"],
                        "start_date": v.get("start") or "",
                        "end_date": v.get("end") or "",
                        "days": v.get("days") or 0
                    })
            except Exception:
                pass

    if not years_set:
        years_set = {2024, 2025, 2026}

    sorted_years = sorted(list(years_set))
    result_emp_list = []
    for emp in employees:
        hire_date_str = str(emp.get("hire_date") or "").strip()
        hire_year = extract_year_from_date(hire_date_str)
        hire_iso = format_date_to_iso(hire_date_str)

        exc_date_str = str(emp.get("exclude_date") or "").strip()
        exc_year = extract_year_from_date(exc_date_str)
        exc_iso = format_date_to_iso(exc_date_str)

        # Проверяем статус увольнения/исключения сотрудника
        is_exc = False
        is_quitting = bool(exc_year is not None and exc_year in (year, year - 1))
        if emp.get("from_archive"):
            is_exc = True
        elif is_employee_excluded_for_year(emp, year):
            is_exc = True
        elif int(emp.get("is_excluded") or 0) == 1 and not is_quitting:
            is_exc = True

        # Если сотрудник ещё не был принят на работу к целевому году, пропускаем
        if not is_exc and hire_year is not None and hire_year > year:
            continue

        emp_name = emp.get("name") or emp.get("full_name") or ""
        emp_full = emp.get("full_name") or ""
        tab_num = str(emp.get("tab_num") or "")

        emp_history = {str(y): [] for y in sorted_years}
        seen_keys = set()

        for ai in archive_items:
            ay = str(ai.get("y"))
            if ay not in emp_history:
                continue

            try:
                ay_int = int(ay)
            except Exception:
                ay_int = 0

            # Сотрудник не мог ходить в отпуск до года своего трудоустройства
            if hire_year is not None and ay_int > 0 and ay_int < hire_year:
                continue

            s_iso = format_date_to_iso(ai.get("start_date") or "")
            e_iso = format_date_to_iso(ai.get("end_date") or "")

            # Отпуск до даты приёма на работу не относится к новому сотруднику
            if hire_iso and s_iso and s_iso < hire_iso:
                continue

            # Отпуск после даты увольнения не относится к сотруднику
            if exc_year is not None and ay_int > 0 and ay_int > exc_year:
                continue
            if exc_iso and s_iso and s_iso > exc_iso:
                continue

            a_name = str(ai.get("name") or "")
            a_tab = str(ai.get("tab_num") or "")

            if is_same_person(emp_name, a_name, tab_num, a_tab) or \
               (emp_full and is_same_person(emp_full, a_name, tab_num, a_tab)):
                key = f"{ay}_{s_iso}_{e_iso}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                month_num = 0
                start_day = 1
                if s_iso:
                    if "-" in s_iso:
                        parts = s_iso.split("-")
                        try:
                            month_num = int(parts[1])
                            if len(parts) >= 3:
                                start_day = int(parts[2])
                        except Exception:
                            pass
                    elif "." in s_iso:
                        parts = s_iso.split(".")
                        try:
                            if len(parts) >= 2:
                                start_day = int(parts[0])
                                month_num = int(parts[1])
                        except Exception:
                            pass

                season = get_season(month_num, start_day) if month_num else "other"
                m_name = MONTH_NAMES_RU.get(month_num, "")

                emp_history[ay].append({
                    "month_num": month_num,
                    "month_name": m_name,
                    "start": s_iso,
                    "end": e_iso,
                    "days": int(ai.get("days") or 0),
                    "season": season
                })

        # Вычисление итоговой статистики сезонов отпусков только за прошлые года (не считая планируемый/будущий год)
        summer_count = 0
        summer_days = 0
        winter_count = 0
        winter_days = 0
        other_count = 0
        other_days = 0

        for y_str, v_list in emp_history.items():
            try:
                y_val = int(y_str)
            except Exception:
                y_val = 0

            # Учитываем статистику за все года включительно до просматриваемого года (y_val <= year)
            if y_val > 0 and y_val <= year:
                for v in v_list:
                    s_type = v.get("season")
                    d_cnt = int(v.get("days") or 0)
                    if s_type == "summer":
                        summer_count += 1
                        summer_days += d_cnt
                    elif s_type == "winter":
                        winter_count += 1
                        winter_days += d_cnt
                    else:
                        other_count += 1
                        other_days += d_cnt

        total_vacations = summer_count + winter_count + other_count
        total_days = summer_days + winter_days + other_days

        summer_pct = round((summer_days / total_days * 100), 1) if total_days > 0 else 0.0
        winter_pct = round((winter_days / total_days * 100), 1) if total_days > 0 else 0.0
        other_pct = round((other_days / total_days * 100), 1) if total_days > 0 else 0.0

        dominant_season = "balanced"
        if summer_days > winter_days:
            dominant_season = "summer"
        elif winter_days > summer_days:
            dominant_season = "winter"

        # Новые сотрудники в год приёма без запланированных отпусков не показываются в графике текущего года
        has_any_vacation = any(len(v_list) > 0 for v_list in emp_history.values())
        if hire_year is not None and hire_year == year and not has_any_vacation:
            continue

        v_days = int(emp.get("vacation_days")) if emp.get("vacation_days") is not None else 52

        # Гарантированная защита от сбоя названий и привязка номера к табельному ID
        num_part = None
        if tab_num and tab_num.startswith("ID_"):
            digits = "".join(ch for ch in tab_num if ch.isdigit())
            if digits:
                num_part = int(digits)
        if num_part is None:
            num_part = len(result_emp_list) + 1

        disp_tab = f"ID_{num_part:03d}"
        disp_name = f"Работник №{num_part}"
        disp_full = f"СотрудникПолн №{num_part}"
        disp_pos = f"Должность №{num_part}"

        result_emp_list.append({
            "id": num_part,
            "tab_num": disp_tab,
            "name": disp_name,
            "full_name": disp_full,
            "position": disp_pos,
            "vacation_days": v_days,
            "is_excluded": is_exc,
            "is_quitting_this_year": is_quitting,
            "exclude_date": exc_date_str,
            "stats": {
                "summer_count": summer_count,
                "summer_days": summer_days,
                "summer_pct": summer_pct,
                "winter_count": winter_count,
                "winter_days": winter_days,
                "winter_pct": winter_pct,
                "other_count": other_count,
                "other_days": other_days,
                "other_pct": other_pct,
                "total_count": total_vacations,
                "total_days": total_days,
                "dominant_season": dominant_season
            },
            "history": emp_history
        })

    # Общая статистика по сезонам рассчитывается по активным сотрудникам (или по всем, если активных нет)
    active_emps = [e for e in result_emp_list if not e.get("is_excluded")]
    stats_base = active_emps if active_emps else result_emp_list

    tot_summer_count = sum(e["stats"]["summer_count"] for e in stats_base)
    tot_summer_days = sum(e["stats"]["summer_days"] for e in stats_base)
    tot_winter_count = sum(e["stats"]["winter_count"] for e in stats_base)
    tot_winter_days = sum(e["stats"]["winter_days"] for e in stats_base)
    tot_other_count = sum(e["stats"]["other_count"] for e in stats_base)
    tot_other_days = sum(e["stats"]["other_days"] for e in stats_base)
    tot_all_count = tot_summer_count + tot_winter_count + tot_other_count
    tot_all_days = tot_summer_days + tot_winter_days + tot_other_days

    tot_summer_pct = round((tot_summer_days / tot_all_days * 100), 1) if tot_all_days > 0 else 0.0
    tot_winter_pct = round((tot_winter_days / tot_all_days * 100), 1) if tot_all_days > 0 else 0.0
    tot_other_pct = round((tot_other_days / tot_all_days * 100), 1) if tot_all_days > 0 else 0.0

    overall_stats = {
        "total_employees": len(stats_base),
        "total_vacations": tot_all_count,
        "total_days": tot_all_days,
        "summer_count": tot_summer_count,
        "summer_days": tot_summer_days,
        "summer_pct": tot_summer_pct,
        "winter_count": tot_winter_count,
        "winter_days": tot_winter_days,
        "winter_pct": tot_winter_pct,
        "other_count": tot_other_count,
        "other_days": tot_other_days,
        "other_pct": tot_other_pct
    }

    return {
        "years": sorted_years,
        "overall_stats": overall_stats,
        "employees": result_emp_list
    }

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
        # Очищаем сохраненные графики, чтобы годовая таблица перестраивалась из актуального архива
        cur.execute("DELETE FROM vacations_schedule")
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
    
    private_map = load_private_employee_mapping()

    for row_idx, r in enumerate(rows_data, 2):
        row_name = str(r.get("name") or "").strip()
        row_tab = str(r.get("tab_num") or "").strip()
        if private_map:
            priv = private_map.get(row_tab) or private_map.get(row_name)
            if priv:
                row_name = priv.get("name") or priv.get("full_name") or row_name
                row_tab = priv.get("tab_num") or row_tab

        ws.append([
            r.get("y", 2025),
            row_name,
            row_tab,
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

# Эталонный список реальных сотрудников (ФИО, должности и табельные номера) для гарантированной разанонимизации
DEFAULT_PRIVATE_EMPLOYEES = [
    {"id": "ID_001", "num": 1, "tab": "4004236", "fio": "Цюрко Геннадий Васильевич", "short_fio": "Цюрко Г. В.", "pos": "Слесарь по ремонту подвижного состава"},
    {"id": "ID_002", "num": 2, "tab": "4604571", "fio": "Ханин Дмитрий Викторович", "short_fio": "Ханин Д. В.", "pos": "Слесарь по ремонту подвижного состава"},
    {"id": "ID_003", "num": 3, "tab": "4601556", "fio": "Тимин Игорь Витальевич", "short_fio": "Тимин И. В.", "pos": "Слесарь по ремонту подвижного состава"},
    {"id": "ID_004", "num": 4, "tab": "4607514", "fio": "Будзинский Никита Андреевич", "short_fio": "Будзинский Н. А.", "pos": "Слесарь по ремонту подвижного состава"},
    {"id": "ID_005", "num": 5, "tab": "4611025", "fio": "Александров Вадим Николаевич", "short_fio": "Александров В. Н.", "pos": "Слесарь по ремонту подвижного состава"},
    {"id": "ID_006", "num": 6, "tab": "4016004", "fio": "Степанов Илья Борисович", "short_fio": "Степанов И. Б.", "pos": "Слесарь-электрик по ремонту электрооборудования"},
    {"id": "ID_007", "num": 7, "tab": "4610209", "fio": "Сивов Александр Сергеевич", "short_fio": "Сивов А. С.", "pos": "Слесарь-электрик по ремонту электрооборудования"},
    {"id": "ID_008", "num": 8, "tab": "4004080", "fio": "Комлев Дмитрий Александрович", "short_fio": "Комлев Д. А.", "pos": "Аккумуляторщик"},
    {"id": "ID_009", "num": 9, "tab": "4610497", "fio": "Спиридонов Константин Герольдович", "short_fio": "Спиридонов К. Г.", "pos": "Токарь"},
    {"id": "ID_010", "num": 10, "tab": "4004267", "fio": "Щербакова Ирина Станиславовна", "short_fio": "Щербакова И. С.", "pos": "Машинист крана"},
    {"id": "ID_011", "num": 11, "tab": "4015690", "fio": "Цюрко Ирина Ивановна", "short_fio": "Цюрко И. И.", "pos": "Машинист по стирке спецодежды"},
    {"id": "ID_012", "num": 12, "tab": "4015696", "fio": "Шварчков Сергей Александрович", "short_fio": "Шварчков С. А.", "pos": "Начальник участка"}
]

def load_private_employee_mapping() -> dict[str, dict[str, str]]:
    """Загружает локальный справочник реальных ФИО и должностей из employees_private.csv / xlsx либо эталонного списка"""
    mapping = {}

    def register_entry(anon_id: str, pos: str, full_fio: str, short_fio: str, real_tab: str):
        # Формируем объект сведений о сотруднике
        info = {
            "name": short_fio or full_fio,
            "full_name": full_fio or short_fio,
            "position": pos,
            "tab_num": real_tab or anon_id
        }

        # Регистрация по ID и табельному номеру
        if anon_id:
            mapping[anon_id] = info
            mapping[anon_id.lower()] = info
        if real_tab:
            mapping[real_tab] = info
            mapping[f"Сотрудник №{real_tab}"] = info
            mapping[f"Работник №{real_tab}"] = info
            mapping[f"СотрудникПолн №{real_tab}"] = info
            mapping[f"Сотрудник № {real_tab}"] = info
            mapping[f"Работник № {real_tab}"] = info

        # Регистрация по ФИО
        if short_fio:
            mapping[short_fio] = info
            mapping[short_fio.lower()] = info
        if full_fio:
            mapping[full_fio] = info
            mapping[full_fio.lower()] = info

        # Регистрация по порядковому номеру и шаблонам анонимизации
        num_str = "".join(ch for ch in anon_id if ch.isdigit())
        if num_str:
            num = int(num_str)
            p_num = f"{num:03d}"
            mapping[str(num)] = info
            mapping[f"ID_{p_num}"] = info
            mapping[f"ID_{num}"] = info
            mapping[f"id_{p_num}"] = info
            mapping[f"id_{num}"] = info
            mapping[f"Работник №{num}"] = info
            mapping[f"Работник №{p_num}"] = info
            mapping[f"Работник № {num}"] = info
            mapping[f"Сотрудник №{num}"] = info
            mapping[f"Сотрудник №{p_num}"] = info
            mapping[f"Сотрудник № {num}"] = info
            mapping[f"СотрудникПолн №{num}"] = info
            mapping[f"СотрудникПолн №{p_num}"] = info
            mapping[f"Должность №{num}"] = info
            mapping[f"Должность №{p_num}"] = info

    # 1. Сначала регистрируем эталонных сотрудников по умолчанию
    for emp in DEFAULT_PRIVATE_EMPLOYEES:
        register_entry(
            anon_id=emp["id"],
            pos=emp["pos"],
            full_fio=emp["fio"],
            short_fio=emp["short_fio"],
            real_tab=emp["tab"]
        )

    # 2. Если на сервере есть локальный файл, обновляем данные из него
    csv_file = ROOT.parent / "employees_private.csv"
    xlsx_file = ROOT.parent / "employees_private.xlsx"

    if csv_file.exists():
        try:
            import csv
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f, delimiter=";")
                for row in reader:
                    if not row or len(row) < 3 or str(row[0]).startswith("Код"):
                        continue
                    anon_id = row[0].strip()
                    pos = row[1].strip() if len(row) > 1 else ""
                    full_fio = row[2].strip() if len(row) > 2 else ""
                    short_fio = row[3].strip() if len(row) > 3 else full_fio
                    real_tab = row[4].strip() if len(row) > 4 else anon_id
                    register_entry(anon_id, pos, full_fio, short_fio, real_tab)
        except Exception:
            pass
    elif xlsx_file.exists():
        try:
            wb = openpyxl.load_workbook(xlsx_file, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                if not row or not row[0] or str(row[0]).startswith("Код"):
                    continue
                anon_id = str(row[0]).strip()
                pos = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                full_fio = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                short_fio = str(row[3]).strip() if len(row) > 3 and row[3] else full_fio
                real_tab = str(row[4]).strip() if len(row) > 4 and row[4] else anon_id
                register_entry(anon_id, pos, full_fio, short_fio, real_tab)
        except Exception:
            pass

    return mapping

def parse_holiday_dates(dates_str: str, max_days: int) -> set[int]:
    """Парсит строку праздничных дат (например '1, 2, 3, 4, 5, 6, 7, 8' или '1-8') во множество номеров дней"""
    if not dates_str:
        return set()
    holidays = set()
    parts = re.split(r'[,;\s]+', str(dates_str).strip())
    for part in parts:
        if not part:
            continue
        if '-' in part:
            r = part.split('-')
            try:
                s, e = int(r[0]), int(r[1])
                for d in range(s, e + 1):
                    if 1 <= d <= max_days:
                        holidays.add(d)
            except Exception:
                pass
        else:
            try:
                d = int(part)
                if 1 <= d <= max_days:
                    holidays.add(d)
            except Exception:
                pass
    return holidays

def get_working_vacation_days(start_m: int, start_d: int, end_m: int, end_d: int, holidays_data: list, cal_days: list) -> int:
    """Рассчитывает количество календарных дней отпуска без учета нерабочих праздничных дней (ст. 120 ТК РФ)"""
    count = 0
    for m in range(start_m, end_m + 1):
        s = start_d if m == start_m else 1
        e = end_d if m == end_m else cal_days[m]
        dates_str = ""
        if m < len(holidays_data) and isinstance(holidays_data[m], dict):
            dates_str = holidays_data[m].get("dates", "")
        elif m == 12:
            dates_str = "1, 2, 3, 4, 5, 6, 7, 8"
        h_set = parse_holiday_dates(dates_str, cal_days[m])
        for d in range(s, e + 1):
            if d not in h_set:
                count += 1
    return count

def create_schedule_excel(year: int, items: list, holidays_data: list = None, include_carried_fact: bool = False) -> bytes:
    """Формирует профессионально оформленный файл Excel (.xlsx) с графиком отпусков."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"График {year}"
    ws.views.sheetView[0].showGridLines = True

    # Локальный справочник реальных сотрудников при наличии на сервере
    private_map = load_private_employee_mapping()

    # Определение количества дней в месяцах (с проверкой високосного года)
    is_leap = (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
    feb_days = 29 if is_leap else 28
    cal_days = [31, feb_days, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31, 31]
    month_names = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
        f"Январь {year + 1}"
    ]

    if not holidays_data:
        holidays_data = []

    # Расчет рабочих дней по каждому месяцу (за вычетом праздников)
    days_in_months = []
    for m in range(13):
        dates_str = ""
        if m < len(holidays_data) and isinstance(holidays_data[m], dict):
            dates_str = holidays_data[m].get("dates", "")
        elif m == 12:
            dates_str = "1, 2, 3, 4, 5, 6, 7, 8"
        h_set = parse_holiday_dates(dates_str, cal_days[m])
        days_in_months.append(max(0, cal_days[m] - len(h_set)))

    total_year_working_days = sum(days_in_months[:12]) or 365

    # Стили шрифтов и заливки
    title_font = Font(name="Segoe UI", size=14, bold=True, color="1F4E78")
    meta_font = Font(name="Segoe UI", size=9, italic=True, color="555555")
    th1_font = Font(name="Segoe UI", size=10, bold=True, color="FFFFFF")
    th2_font = Font(name="Segoe UI", size=9, bold=True, color="1E293B")
    data_font = Font(name="Segoe UI", size=9)
    bold_data_font = Font(name="Segoe UI", size=9, bold=True)
    small_desc_font = Font(name="Segoe UI", size=8, color="475569")

    th1_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    th2_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    vacation_fill = PatternFill(start_color="E0EDFE", end_color="E0EDFE", fill_type="solid")
    carried_fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    summary1_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    summary2_fill = PatternFill(start_color="EFF6FF", end_color="EFF6FF", fill_type="solid")
    summary3_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    thin_side = Side(style='thin', color='CBD5E1')
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    thick_bottom_side = Side(style='medium', color='1F4E78')
    header_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thick_bottom_side)

    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")

    def apply_range_border(start_r, start_c, end_r, end_c, border=thin_border, fill=None):
        for r in range(start_r, end_r + 1):
            for c in range(start_c, end_c + 1):
                cell = ws.cell(row=r, column=c)
                cell.border = border
                if fill:
                    cell.fill = fill

    # 1. Заголовок таблицы (ширина 30 колонок A-AD)
    ws.merge_cells("A1:AD1")
    ws["A1"] = f"ГРАФИК ОТПУСКОВ РАБОТНИКОВ НА {year} ГОД"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:AD2")
    ws["A2"] = f"Дата выгрузки: {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  Всего работников: {len(items)}"
    ws["A2"].font = meta_font
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 18

    # 2. Шапка графической таблицы (строки 3 и 4)
    ws.row_dimensions[3].height = 28
    ws.row_dimensions[4].height = 20

    headers_fixed = [
        (1, "№\nп/п"),
        (2, "Сотрудник (ФИО)"),
        (3, "Должность"),
        (4, "Отпуск\n(дней)")
    ]

    for col_idx, title in headers_fixed:
        ws.merge_cells(start_row=3, start_column=col_idx, end_row=4, end_column=col_idx)
        cell = ws.cell(row=3, column=col_idx, value=title)
        cell.font = th1_font
        cell.alignment = center_align
        apply_range_border(3, col_idx, 4, col_idx, border=header_border, fill=th1_fill)

    # Заголовки месяцев (колонки 5 .. 30)
    for m in range(13):
        c_start = 5 + 2 * m
        c_end = 6 + 2 * m
        ws.merge_cells(start_row=3, start_column=c_start, end_row=3, end_column=c_end)
        cell = ws.cell(row=3, column=c_start, value=f"{month_names[m]}\n({days_in_months[m]} дн.)")
        cell.font = th1_font
        cell.alignment = center_align
        apply_range_border(3, c_start, 3, c_end, border=thin_border, fill=th1_fill)

        cell_c = ws.cell(row=4, column=c_start, value="с")
        cell_c.font = th2_font
        cell_c.alignment = center_align
        cell_c.fill = th2_fill
        cell_c.border = header_border

        cell_po = ws.cell(row=4, column=c_end, value="по")
        cell_po.font = th2_font
        cell_po.alignment = center_align
        cell_po.fill = th2_fill
        cell_po.border = header_border

    # 3. Данные сотрудников в графической таблице (начиная со строки 5)
    start_data_row = 5
    current_row = start_data_row
    month_fact_sums = [0] * 13
    periods_table_data = []

    for idx, emp in enumerate(items, 1):
        ws.row_dimensions[current_row].height = 20

        raw_tab = str(emp.get("tab_num") or "").strip()
        raw_name = str(emp.get("name") or "").strip()
        raw_full = str(emp.get("full_name") or "").strip()
        raw_pos = str(emp.get("position") or "").strip()
        emp_id = emp.get("id")
        allowed_val = int(emp.get("vacation_days") or emp.get("allowedDays") or 28)

        # Подстановка реальных данных сотрудника из расширенного локального справочника
        priv = None
        search_candidates = [
            raw_tab, raw_name, raw_full,
            f"ID_{idx:03d}", f"ID_{idx}",
            str(emp_id) if emp_id else "",
            f"ID_{int(emp_id):03d}" if str(emp_id).isdigit() else ""
        ]
        # Извлекаем все числовые последовательности (табельные номера или ID)
        for s in (raw_name, raw_full, raw_tab):
            digits = "".join(ch for ch in s if ch.isdigit())
            if digits:
                search_candidates.extend([digits, f"ID_{int(digits):03d}" if len(digits) <= 3 else digits])

        for cand in search_candidates:
            if cand and cand in private_map:
                priv = private_map[cand]
                break
            if cand and cand.lower() in private_map:
                priv = private_map[cand.lower()]
                break

        # Резервный поиск по порядковому номеру строки среди 12 сотрудников
        if not priv and 1 <= idx <= len(DEFAULT_PRIVATE_EMPLOYEES):
            def_emp = DEFAULT_PRIVATE_EMPLOYEES[idx - 1]
            priv = {
                "name": def_emp["short_fio"],
                "full_name": def_emp["fio"],
                "position": def_emp["pos"],
                "tab_num": def_emp["tab"]
            }

        # Определение финальных значений ФИО, должности и табельного
        if priv:
            emp_name = priv.get("name") or priv.get("full_name") or raw_name or raw_full
            emp_pos = priv.get("position") or raw_pos or priv.get("pos", "")
            emp_tab = priv.get("tab_num") or raw_tab or priv.get("tab", "")
        else:
            emp_name = raw_name or raw_full or f"Сотрудник {idx}"
            emp_pos = raw_pos
            emp_tab = raw_tab

        # Гарантированная защита: исключаем попадание чисел (табельного номера) или анонимных меток в ФИО
        clean_name = emp_name.strip()
        is_invalid_fio = (
            clean_name.isdigit()
            or clean_name.startswith("Сотрудник №")
            or clean_name.startswith("Работник №")
            or clean_name.startswith("ID_")
            or not clean_name
        )
        if is_invalid_fio:
            digits = "".join(ch for ch in clean_name if ch.isdigit())
            if digits and digits in private_map:
                emp_name = private_map[digits].get("name") or private_map[digits].get("full_name")
            elif 1 <= idx <= len(DEFAULT_PRIVATE_EMPLOYEES):
                emp_name = DEFAULT_PRIVATE_EMPLOYEES[idx - 1]["short_fio"]

        # Подготовка данных по месяцам
        m_c_vals = [None] * 13
        m_po_vals = [None] * 13
        m_is_vac = [False] * 13
        m_is_cov = [False] * 13

        months_input = emp.get("months_data")
        if isinstance(months_input, list):
            for m_item in months_input:
                m_idx = m_item.get("month")
                if m_idx is not None and 0 <= m_idx < 13:
                    if m_item.get("c") is not None:
                        m_c_vals[m_idx] = int(m_item["c"])
                    if m_item.get("po") is not None:
                        m_po_vals[m_idx] = int(m_item["po"])

        vacations_list = emp.get("vacations") or []
        carried_list = emp.get("carried_over_vacations") or []
        all_vacs = vacations_list + carried_list

        emp_fact_days = 0
        vac_periods_desc = []

        # Обработка отпусков сотрудника
        for vac in all_vacs:
            s_str = str(vac.get("start") or "").strip()
            e_str = str(vac.get("end") or "").strip()
            if not s_str or not e_str:
                continue

            s_parts = s_str.split('-')
            e_parts = e_str.split('-')
            if len(s_parts) < 3 or len(e_parts) < 3:
                continue

            try:
                s_y = int(s_parts[0])
                s_m = int(s_parts[1]) - 1
                s_d = int(s_parts[2])

                e_y = int(e_parts[0])
                e_m = int(e_parts[1]) - 1
                e_d = int(e_parts[2])
            except ValueError:
                continue

            start_month_idx = 12 if (s_y == year + 1 and s_m == 0) else s_m
            end_month_idx = 12 if (e_y == year + 1 and e_m == 0) else e_m

            if start_month_idx < 0 or start_month_idx > 12 or end_month_idx < 0 or end_month_idx > 12:
                continue

            if m_c_vals[start_month_idx] is None:
                m_c_vals[start_month_idx] = s_d
            if m_po_vals[end_month_idx] is None:
                m_po_vals[end_month_idx] = e_d

            v_days = int(vac.get("days") or 0)
            if v_days <= 0:
                v_days = get_working_vacation_days(start_month_idx, s_d, end_month_idx, e_d, holidays_data, cal_days)

            is_cov = bool(vac.get("is_carried_over"))
            for m_i in range(start_month_idx, end_month_idx + 1):
                m_is_vac[m_i] = True
                if is_cov:
                    m_is_cov[m_i] = True

            # Учет в факте
            if not is_cov or include_carried_fact:
                emp_fact_days += v_days
                for m_i in range(start_month_idx, end_month_idx + 1):
                    seg_s = s_d if m_i == start_month_idx else 1
                    seg_e = e_d if m_i == end_month_idx else cal_days[m_i]
                    month_fact_sums[m_i] += get_working_vacation_days(m_i, seg_s, m_i, seg_e, holidays_data, cal_days)

            # Форматирование текстового описания периода
            s_ru = f"{s_parts[2]}.{s_parts[1]}" + (f".{s_y}" if s_y != year else "")
            e_ru = f"{e_parts[2]}.{e_parts[1]}" + (f".{e_y}" if e_y != year else "")
            cov_mark = " (перенос с прошл. г.)" if is_cov else ""
            vac_periods_desc.append(f"{s_ru} - {e_ru} ({v_days} дн.){cov_mark}")

        # Сохранение периодов для вывода в секции под графической таблицей
        periods_table_data.append({
            "idx": idx,
            "name": emp_name,
            "pos": emp_pos,
            "periods": vac_periods_desc
        })

        # Запись базовых колонок
        # Колонка 1: № п/п
        c_num = ws.cell(row=current_row, column=1, value=idx)
        c_num.font = data_font
        c_num.alignment = center_align
        c_num.border = thin_border

        # Колонка 2: Сотрудник (ФИО)
        c_name = ws.cell(row=current_row, column=2, value=emp_name)
        c_name.font = bold_data_font
        c_name.alignment = left_align
        c_name.border = thin_border

        # Колонка 3: Должность
        c_pos = ws.cell(row=current_row, column=3, value=emp_pos)
        c_pos.font = data_font
        c_pos.alignment = left_align
        c_pos.border = thin_border

        # Колонка 4: Отпуск (дней)
        c_all = ws.cell(row=current_row, column=4, value=allowed_val)
        c_all.font = bold_data_font
        c_all.alignment = center_align
        c_all.border = thin_border

        # Запись ячеек месяцев (колонки 5 .. 30)
        for m in range(13):
            col_c = 5 + 2 * m
            col_po = 6 + 2 * m

            val_c = m_c_vals[m]
            val_po = m_po_vals[m]

            cell_c = ws.cell(row=current_row, column=col_c, value=val_c if val_c is not None else "")
            cell_po = ws.cell(row=current_row, column=col_po, value=val_po if val_po is not None else "")

            cell_c.font = data_font
            cell_c.alignment = center_align
            cell_c.border = thin_border

            cell_po.font = data_font
            cell_po.alignment = center_align
            cell_po.border = thin_border

            if m_is_cov[m]:
                cell_c.fill = carried_fill
                cell_po.fill = carried_fill
            elif m_is_vac[m]:
                cell_c.fill = vacation_fill
                cell_po.fill = vacation_fill

        current_row += 1

    last_data_row = current_row - 1

    # 4. Итоговые строки (Всего положено, Занесено факт, Отклонение %)
    if last_data_row >= start_data_row:
        total_allowed_days = sum(int(e.get("vacation_days") or e.get("allowedDays") or 28) for e in items)

        # Итоговая строка 1: Всего положено
        r_sum1 = current_row
        ws.row_dimensions[r_sum1].height = 24
        ws.merge_cells(start_row=r_sum1, start_column=1, end_row=r_sum1, end_column=3)
        ws.cell(row=r_sum1, column=1, value="Всего положено:").font = bold_data_font
        ws.cell(row=r_sum1, column=1).alignment = right_align
        apply_range_border(r_sum1, 1, r_sum1, 3, border=thin_border, fill=summary1_fill)

        c_s1_all = ws.cell(row=r_sum1, column=4, value=f"=SUM(D{start_data_row}:D{last_data_row})")
        c_s1_all.font = bold_data_font
        c_s1_all.alignment = center_align
        c_s1_all.fill = summary1_fill
        c_s1_all.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum1, start_column=c_s, end_row=r_sum1, end_column=c_e)
            m_norm = round((total_allowed_days / total_year_working_days) * days_in_months[m])
            cell_m = ws.cell(row=r_sum1, column=c_s, value=m_norm)
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum1, c_s, r_sum1, c_e, border=thin_border, fill=summary1_fill)

        # Итоговая строка 2: Занесено (факт)
        r_sum2 = current_row + 1
        ws.row_dimensions[r_sum2].height = 24
        ws.merge_cells(start_row=r_sum2, start_column=1, end_row=r_sum2, end_column=3)
        ws.cell(row=r_sum2, column=1, value="Занесено (факт):").font = bold_data_font
        ws.cell(row=r_sum2, column=1).alignment = right_align
        apply_range_border(r_sum2, 1, r_sum2, 3, border=thin_border, fill=summary2_fill)

        grand_fact_sum = sum(month_fact_sums)
        c_s2_fct = ws.cell(row=r_sum2, column=4, value=grand_fact_sum)
        c_s2_fct.font = bold_data_font
        c_s2_fct.alignment = center_align
        c_s2_fct.fill = summary2_fill
        c_s2_fct.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum2, start_column=c_s, end_row=r_sum2, end_column=c_e)
            cell_m = ws.cell(row=r_sum2, column=c_s, value=month_fact_sums[m])
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum2, c_s, r_sum2, c_e, border=thin_border, fill=summary2_fill)

        # Итоговая строка 3: Отклонение (%)
        r_sum3 = current_row + 2
        ws.row_dimensions[r_sum3].height = 24
        ws.merge_cells(start_row=r_sum3, start_column=1, end_row=r_sum3, end_column=3)
        ws.cell(row=r_sum3, column=1, value="Отклонение (%):").font = bold_data_font
        ws.cell(row=r_sum3, column=1).alignment = right_align
        apply_range_border(r_sum3, 1, r_sum3, 3, border=thin_border, fill=summary3_fill)

        grand_diff = grand_fact_sum - total_allowed_days
        grand_pct_str = "0%"
        if total_allowed_days > 0:
            pct = round((grand_diff / total_allowed_days) * 100)
            sign = "+" if pct > 0 else ""
            grand_pct_str = f"{sign}{pct}%"

        cell_s3_dif = ws.cell(row=r_sum3, column=4, value=grand_pct_str)
        cell_s3_dif.font = bold_data_font
        cell_s3_dif.alignment = center_align
        cell_s3_dif.fill = summary3_fill
        cell_s3_dif.border = thin_border

        for m in range(13):
            c_s = 5 + 2 * m
            c_e = 6 + 2 * m
            ws.merge_cells(start_row=r_sum3, start_column=c_s, end_row=r_sum3, end_column=c_e)
            m_norm = round((total_allowed_days / total_year_working_days) * days_in_months[m])
            m_fact = month_fact_sums[m]
            m_pct_str = "0%"
            if m_norm > 0:
                m_diff = m_fact - m_norm
                m_pct = round((m_diff / m_norm) * 100)
                sign = "+" if m_pct > 0 else ""
                m_pct_str = f"{sign}{m_pct}%"
            elif m_fact > 0:
                m_pct_str = "+100%"

            cell_m = ws.cell(row=r_sum3, column=c_s, value=m_pct_str)
            cell_m.font = bold_data_font
            cell_m.alignment = center_align
            apply_range_border(r_sum3, c_s, r_sum3, c_e, border=thin_border, fill=summary3_fill)

    # 5. Секция подробных периодов отпусков (расположена под графической таблицей)
    current_row = (r_sum3 + 2) if last_data_row >= start_data_row else current_row + 2

    # Заголовок секции периодов отпусков
    ws.row_dimensions[current_row].height = 26
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=30)
    sec_title_cell = ws.cell(row=current_row, column=1, value="ПЕРИОДЫ ОТПУСКОВ РАБОТНИКОВ (ДАТЫ И КОЛИЧЕСТВО ДНЕЙ)")
    sec_title_cell.font = Font(name="Segoe UI", size=11, bold=True, color="1F4E78")
    sec_title_cell.alignment = Alignment(horizontal="left", vertical="center")
    apply_range_border(current_row, 1, current_row, 30, border=header_border, fill=th2_fill)
    current_row += 1

    # Шапка таблицы периодов
    ws.row_dimensions[current_row].height = 24
    c_p_num = ws.cell(row=current_row, column=1, value="№\nп/п")
    c_p_num.font = th1_font
    c_p_num.alignment = center_align
    c_p_num.fill = th1_fill
    c_p_num.border = header_border

    c_p_name = ws.cell(row=current_row, column=2, value="Сотрудник (ФИО)")
    c_p_name.font = th1_font
    c_p_name.alignment = center_align
    c_p_name.fill = th1_fill
    c_p_name.border = header_border

    c_p_pos = ws.cell(row=current_row, column=3, value="Должность")
    c_p_pos.font = th1_font
    c_p_pos.alignment = center_align
    c_p_pos.fill = th1_fill
    c_p_pos.border = header_border

    ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=30)
    c_p_desc = ws.cell(row=current_row, column=4, value="Запланированные периоды отпусков")
    c_p_desc.font = th1_font
    c_p_desc.alignment = center_align
    apply_range_border(current_row, 4, current_row, 30, border=header_border, fill=th1_fill)
    current_row += 1

    # Заполнение строк периодов отпусков
    for p_item in periods_table_data:
        p_count = len(p_item["periods"])
        ws.row_dimensions[current_row].height = max(20, 18 * p_count) if p_count > 1 else 20

        # № п/п
        c_num = ws.cell(row=current_row, column=1, value=p_item["idx"])
        c_num.font = data_font
        c_num.alignment = center_align
        c_num.border = thin_border

        # Сотрудник (ФИО)
        c_name = ws.cell(row=current_row, column=2, value=p_item["name"])
        c_name.font = bold_data_font
        c_name.alignment = left_align
        c_name.border = thin_border

        # Должность
        c_pos = ws.cell(row=current_row, column=3, value=p_item["pos"])
        c_pos.font = data_font
        c_pos.alignment = left_align
        c_pos.border = thin_border

        # Периоды отпусков (колонки 4..30)
        ws.merge_cells(start_row=current_row, start_column=4, end_row=current_row, end_column=30)
        desc_val = ",  ".join(p_item["periods"]) if p_item["periods"] else "—"
        c_desc = ws.cell(row=current_row, column=4, value=desc_val)
        c_desc.font = data_font
        c_desc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        apply_range_border(current_row, 4, current_row, 30, border=thin_border)

        current_row += 1

    # 6. Ширина колонок
    col_widths = {
        1: 6,   # № п/п
        2: 32,  # Сотрудник (ФИО)
        3: 28,  # Должность
        4: 12,  # Отпуск (дней)
    }
    for col_c in range(5, 31):
        col_widths[col_c] = 5.5

    for c_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(c_idx)].width = width

    # Закрепление областей: фиксируем первые 4 строки и колонки A-D
    ws.freeze_panes = "E5"

    # Настройки страницы для печати на листе А4 в альбомной ориентации
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = '3:4'
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()

@app.get("/api/vacations/schedule/export")
@app.get(f"{APP_PREFIX}/api/vacations/schedule/export")
async def export_schedule_get(year: int = 2026, include_carried: bool = False):
    """Выгрузка сохраненного в базе данных графика отпусков в Excel (GET-запрос)"""
    items = await get_vacations(year=year)
    holidays = await get_holidays(year=year)
    excel_bytes = create_schedule_excel(
        year=year,
        items=items,
        holidays_data=holidays,
        include_carried_fact=include_carried
    )
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=grafik_otpuskov_{year}.xlsx"}
    )

@app.post("/api/vacations/schedule/export")
@app.post(f"{APP_PREFIX}/api/vacations/schedule/export")
async def export_schedule_post(request: Request, year: int = 2026):
    """Выгрузка текущего активного состояния таблицы графика отпусков из веб-интерфейса в Excel (POST-запрос)"""
    payload = await request.json()
    req_year = int(payload.get("year") or year)
    items = payload.get("items")
    include_carried = bool(payload.get("include_carried"))

    if not items or not isinstance(items, list):
        items = await get_vacations(year=req_year)

    holidays = await get_holidays(year=req_year)
    excel_bytes = create_schedule_excel(
        year=req_year,
        items=items,
        holidays_data=holidays,
        include_carried_fact=include_carried
    )
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=grafik_otpuskov_{req_year}.xlsx"}
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
                return str(row[idx]).strip()
            return str(default)

        def date_val(idx):
            if idx < len(row) and row[idx] is not None:
                return format_date_to_iso(row[idx])
            return ""

        def int_val(idx, default=0):
            try:
                v = val(idx, default)
                return int(float(v))
            except Exception:
                return default

        s_date = date_val(3)
        e_date = date_val(4)

        y_val = int_val(0, 0)
        if not y_val and s_date and len(s_date) >= 4:
            try:
                y_val = int(s_date.split("-")[0])
            except Exception:
                pass
        if not y_val:
            y_val = 2025

        name_val = val(1, "")
        tab_val = val(2, "")
        days_val = int_val(5, 0)
        note_val = val(6, "")

        # Автовычисление количества дней, если упущены дни, но указаны даты
        if days_val == 0 and s_date and e_date:
            try:
                d1 = datetime.strptime(s_date, "%Y-%m-%d")
                d2 = datetime.strptime(e_date, "%Y-%m-%d")
                days_val = (d2 - d1).days + 1
            except Exception:
                pass

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
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if mode == "replace":
            cur.execute("DELETE FROM vacations_archive")

        existing_rows = []
        if mode == "append":
            existing_rows = [dict(r) for r in cur.execute("SELECT y, tab_num, name, start_date, end_date FROM vacations_archive").fetchall()]

        inserted_count = 0
        skipped_count = 0

        for item in imported_items:
            if mode == "append":
                is_duplicate = False
                for ex in existing_rows:
                    if int(ex.get("y") or 0) == int(item.get("y") or 0):
                        ex_s = format_date_to_iso(ex.get("start_date") or "")
                        ex_e = format_date_to_iso(ex.get("end_date") or "")
                        it_s = format_date_to_iso(item.get("start_date") or "")
                        it_e = format_date_to_iso(item.get("end_date") or "")
                        if ex_s == it_s and ex_e == it_e:
                            if is_same_person(item.get("name") or "", ex.get("name") or "", item.get("tab_num") or "", ex.get("tab_num") or ""):
                                is_duplicate = True
                                break
                if is_duplicate:
                    skipped_count += 1
                    continue

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
            inserted_count += 1
            if mode == "append":
                # Добавляем в локальный список для предотвращения дубликатов внутри одного файла
                existing_rows.append(item)

        # Очищаем сохраненные графики, чтобы годовая таблица перестраивалась из актуального архива
        cur.execute("DELETE FROM vacations_schedule")
        conn.commit()

    return {"status": "success", "imported_count": inserted_count, "skipped_count": skipped_count}

@app.get("/api/versions")
@app.get(f"{APP_PREFIX}/api/versions")
async def get_versions(year: int = 2026):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id, y, version_name, created_at, is_active FROM vacation_versions WHERE y=? ORDER BY id DESC",
            (year,)
        ).fetchall()
        return [dict(r) for r in rows]

# Вспомогательная функция сопоставления старых реальных табельных номеров из версий с текущими шифрами ID_00X
def map_version_data_to_ciphers(data_list):
    if not isinstance(data_list, list):
        return data_list

    tab_mapping = {}
    csv_file = ROOT.parent / "employees_private.csv"
    xlsx_file = ROOT.parent / "employees_private.xlsx"

    if csv_file.exists():
        try:
            import csv
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f, delimiter=";")
                for row in reader:
                    if not row or len(row) < 5 or row[0].startswith("Код"):
                        continue
                    anon_id = row[0].strip()
                    real_tab = row[4].strip()
                    if anon_id and real_tab:
                        tab_mapping[real_tab] = anon_id
        except Exception:
            pass
    elif xlsx_file.exists():
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx_file)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                if not row or len(row) < 5 or str(row[0]).startswith("Код"):
                    continue
                anon_id = str(row[0]).strip()
                real_tab = str(row[4]).strip()
                if anon_id and real_tab:
                    tab_mapping[real_tab] = anon_id
        except Exception:
            pass

    for item in data_list:
        if isinstance(item, dict):
            saved_tab = str(item.get("tab_num") or "").strip()
            if saved_tab in tab_mapping:
                item["tab_num"] = tab_mapping[saved_tab]

    return data_list

@app.get("/api/versions/{version_id}")
@app.get(APP_PREFIX + "/api/versions/{version_id}")
async def get_version_detail(version_id: int):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, y, version_name, created_at, is_active, data_json FROM vacation_versions WHERE id=?",
            (version_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Version not found")
        res = dict(row)
        raw_data = json.loads(res["data_json"] or "[]")
        res["data"] = map_version_data_to_ciphers(raw_data)
        return res

@app.post("/api/versions")
@app.post(f"{APP_PREFIX}/api/versions")
async def create_version(request: Request, year: int = 2026):
    payload = await request.json()
    v_name = (payload.get("version_name") or "").strip()
    v_data = payload.get("data") or []
    overwrite = bool(payload.get("overwrite"))
    version_id = payload.get("version_id")

    if not v_name:
        v_name = f"Версия от {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()

        # Поиск существующей версии с таким же названием для целевого года
        existing = None
        if version_id:
            existing = cur.execute(
                "SELECT id, version_name FROM vacation_versions WHERE id=?",
                (version_id,)
            ).fetchone()
        else:
            existing = cur.execute(
                "SELECT id, version_name FROM vacation_versions WHERE y=? AND LOWER(TRIM(version_name))=LOWER(TRIM(?))",
                (year, v_name)
            ).fetchone()

        # Если версия с таким названием найдена, но пользователь не подтвердил перезапись
        if existing and not overwrite:
            return {
                "status": "conflict",
                "message": f"Версия с названием «{existing[1]}» уже существует.",
                "existing_id": existing[0],
                "existing_name": existing[1]
            }

        # Перезапись существующей версии
        if existing and overwrite:
            cur_id = existing[0]
            cur.execute("UPDATE vacation_versions SET is_active=0 WHERE y=?", (year,))
            cur.execute(
                "UPDATE vacation_versions SET version_name=?, created_at=?, data_json=?, is_active=1 WHERE id=?",
                (v_name, created_at, json.dumps(v_data, ensure_ascii=False), cur_id)
            )
            conn.commit()
            return {"status": "ok", "id": cur_id, "version_name": v_name, "created_at": created_at, "is_active": 1, "overwritten": True}

        # Создание новой версии
        cur.execute("UPDATE vacation_versions SET is_active=0 WHERE y=?", (year,))
        cur.execute(
            "INSERT INTO vacation_versions (y, version_name, created_at, data_json, is_active) VALUES (?, ?, ?, ?, 1)",
            (year, v_name, created_at, json.dumps(v_data, ensure_ascii=False))
        )
        conn.commit()
        new_id = cur.lastrowid
        return {"status": "ok", "id": new_id, "version_name": v_name, "created_at": created_at, "is_active": 1}

@app.post("/api/versions/{version_id}/activate")
@app.post(APP_PREFIX + "/api/versions/{version_id}/activate")
async def activate_version(version_id: int):
    with DB_LOCK, sqlite3.connect(COMMON_DB_FILE) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT y FROM vacation_versions WHERE id=?", (version_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Версия не найдена")
        y = row[0]
        # Сбрасываем активность для версий этого года и активируем указанную
        cur.execute("UPDATE vacation_versions SET is_active=0 WHERE y=?", (y,))
        cur.execute("UPDATE vacation_versions SET is_active=1 WHERE id=?", (version_id,))
        conn.commit()
        return {"status": "ok", "active_version_id": version_id}

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

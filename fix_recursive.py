import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# I will just write the exact correct lines for load_system_dates, load_state, and debug_startup.
# Let's fix the whole block from FIXED_HOLIDAYS to api_get_state

pattern = re.compile(r'FIXED_HOLIDAYS = \{.*?(?=@app\.get\("/api/state"\))', re.DOTALL)

correct_code = """FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

def load_system_dates(year: int) -> dict[str, list[tuple[int, int]]]:
    transfer_dates: set[tuple[int, int]] = set()
    holiday_dates: set[tuple[int, int]] = set(FIXED_HOLIDAYS)
    db_path = ROOT.parent / "base" / "common_database.db"
    if not db_path.exists():
        return {
            "transfer": sorted(transfer_dates),
            "holiday": sorted(holiday_dates),
        }

    try:
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT c, v FROM ts_norms_data WHERE y=? AND c IN (6, 7)",
                (year,),
            ).fetchall()
        for col_idx, raw_text in rows:
            if not raw_text:
                continue
            text = str(raw_text).replace(";", "\\n").replace(",", "\\n")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(".")
                if len(parts) == 2:
                    try:
                        d, m = int(parts[0]), int(parts[1])
                        if col_idx == 6:
                            transfer_dates.add((m, d))
                        elif col_idx == 7:
                            holiday_dates.add((m, d))
                    except ValueError:
                        pass
    except Exception:
        pass

    return {
        "transfer": sorted(transfer_dates),
        "holiday": sorted(holiday_dates),
    }

def load_state(year: int, month: int) -> dict:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        
        employees = []
        try:
            emp_rows = cur.execute(
                "SELECT pos, name, tab_num, milk, milk_issue, full_name, milk_note FROM employees WHERE y=? ORDER BY rowid", (year,)
            ).fetchall()
            for r in emp_rows:
                employees.append({
                    "pos": text(r["pos"]),
                    "name": text(r["name"]),
                    "tab_num": text(r["tab_num"]),
                    "milk": int(r["milk"] or 0),
                    "milk_issue": int(r["milk_issue"] or 0),
                    "full_name": text(r["full_name"]),
                    "milk_note": text(r["milk_note"])
                })
        except Exception:
            pass

        timesheet = {}
        try:
            m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
            ts_rows = cur.execute(
                "SELECT tab_num, c, v FROM timesheet WHERE y=? AND m=?", (year, m_str)
            ).fetchall()
            for r in ts_rows:
                timesheet.setdefault(text(r["tab_num"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass
            
        vacations = {}
        try:
            vac_rows = cur.execute("SELECT tab_num, c, v FROM vacations WHERE y=?", (year,)).fetchall()
            for r in vac_rows:
                vacations.setdefault(text(r["tab_num"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

        ts_norms_data = {}
        try:
            norms_rows = cur.execute("SELECT r, c, v FROM ts_norms_data WHERE y=?", (year,)).fetchall()
            for r in norms_rows:
                ts_norms_data.setdefault(int(r["r"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

    return {
        "system_dates": load_system_dates(year),
        "year": year,
        "month": month,
        "employees": employees,
        "timesheet": timesheet,
        "vacations": vacations,
        "ts_norms_data": ts_norms_data,
    }

@app.get("/api/debug_startup")
async def debug_startup(request: Request):
    error_file = ROOT / "startup_error.log"
    if error_file.exists():
        return {"error": error_file.read_text(encoding="utf-8")}
    return {"error": "No startup error found."}

"""

new_text = pattern.sub(correct_code, text)

# Bump version to 1.28
new_text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.28"', new_text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Fixed app.py")

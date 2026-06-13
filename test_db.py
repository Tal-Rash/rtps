import sys
sys.path.append(r"g:\Мой диск\Codex\rtps\web_tabel")
import app
import sqlite3

app.init_db()

try:
    with app.connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        emp_rows = cur.execute(
            "SELECT pos, name, tab_num, milk, milk_issue, full_name, milk_note, is_excluded FROM employees WHERE y=2026 ORDER BY rowid"
        ).fetchall()
        print("ROWS:", len(emp_rows))
except Exception as e:
    import traceback
    traceback.print_exc()

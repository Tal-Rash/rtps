import sqlite3
import os

db_path = r'g:\Мой диск\Codex\rtps\web_tabel\data\tabel.db'
if not os.path.exists(db_path):
    print("DB not found")
    exit()

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Read current employees to map r -> tab_num
years = cur.execute("SELECT DISTINCT y FROM employees").fetchall()
for y_row in years:
    year = y_row["y"]
    emps = cur.execute("SELECT rowid, tab_num FROM employees WHERE y=? ORDER BY rowid", (year,)).fetchall()
    
    # In web_tabel app.py, load_state just does:
    # "SELECT ... FROM employees WHERE y=?"
    # which returns them in insertion order (rowid).
    # So r is the index in this list!
    r_to_tab = {}
    for idx, emp in enumerate(emps):
        r_to_tab[idx] = emp["tab_num"]
        
    print(f"Year {year} mapping:", r_to_tab)

    # 2. Migrate timesheet
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS timesheet_v2 (y INT, m TEXT, tab_num TEXT, c INT, v TEXT, PRIMARY KEY(y,m,tab_num,c))")
        ts_rows = cur.execute("SELECT m, r, c, v FROM timesheet WHERE y=?", (year,)).fetchall()
        for row in ts_rows:
            tab_num = r_to_tab.get(row["r"])
            if tab_num is not None:
                cur.execute("INSERT OR REPLACE INTO timesheet_v2 (y, m, tab_num, c, v) VALUES (?, ?, ?, ?, ?)", 
                            (year, row["m"], tab_num, row["c"], row["v"]))
    except Exception as e:
        print("timesheet error:", e)

    # 3. Migrate vacations
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS vacations_v2 (y INT, tab_num TEXT, c INT, v TEXT, PRIMARY KEY(y,tab_num,c))")
        vac_rows = cur.execute("SELECT r, c, v FROM vacations WHERE y=?", (year,)).fetchall()
        for row in vac_rows:
            tab_num = r_to_tab.get(row["r"])
            if tab_num is not None:
                cur.execute("INSERT OR REPLACE INTO vacations_v2 (y, tab_num, c, v) VALUES (?, ?, ?, ?)", 
                            (year, tab_num, row["c"], row["v"]))
    except Exception as e:
        print("vacations error:", e)
        
    # 4. Migrate ts_norms_data
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS ts_norms_data_v2 (y INT, tab_num TEXT, c INT, v TEXT, PRIMARY KEY(y,tab_num,c))")
        norms_rows = cur.execute("SELECT r, c, v FROM ts_norms_data WHERE y=?", (year,)).fetchall()
        for row in norms_rows:
            tab_num = r_to_tab.get(row["r"])
            if tab_num is not None:
                cur.execute("INSERT OR REPLACE INTO ts_norms_data_v2 (y, tab_num, c, v) VALUES (?, ?, ?, ?)", 
                            (year, tab_num, row["c"], row["v"]))
    except Exception as e:
        print("norms error:", e)

conn.commit()
print("Migration to v2 completed.")

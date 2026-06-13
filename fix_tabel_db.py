import sqlite3
db_path = r'g:\Мой диск\Codex\rtps\web_tabel\data\tabel.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Build mapping bad_to_true
bad_to_true = {}
for row in cur.execute("SELECT tab_num, v FROM timesheet WHERE c=3").fetchall():
    bad_to_true[row['tab_num']] = row['v']

print("Mapping:", bad_to_true)

# 2. Fix timesheet
ts_rows = cur.execute("SELECT y, m, tab_num, c, v FROM timesheet").fetchall()
cur.execute("DELETE FROM timesheet")
insert_ts = []
for r in ts_rows:
    t = r['tab_num']
    c = r['c']
    # Skip c=0, 1, 2, 3 because they are just employee info duplicates!
    if c <= 3:
        continue
    true_t = bad_to_true.get(t, t)
    insert_ts.append((r['y'], r['m'], true_t, c, r['v']))

cur.executemany("INSERT INTO timesheet(y, m, tab_num, c, v) VALUES(?,?,?,?,?)", insert_ts)

# 3. Fix vacations
vac_rows = cur.execute("SELECT y, tab_num, c, v FROM vacations").fetchall()
cur.execute("DELETE FROM vacations")
insert_vac = []
for r in vac_rows:
    t = r['tab_num']
    true_t = bad_to_true.get(t, t)
    insert_vac.append((r['y'], true_t, r['c'], r['v']))

cur.executemany("INSERT INTO vacations(y, tab_num, c, v) VALUES(?,?,?,?)", insert_vac)

conn.commit()
print("DB fixed successfully!")

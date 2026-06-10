import sqlite3
import os

db_path = 'base/common_database.db'
if not os.path.exists(db_path):
    print("DB not found!")
    exit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

swap_map = {2: 4, 3: 5, 4: 2, 5: 3}

# Input data
input_rows = cur.execute('SELECT y, locomotive, r, c, v FROM input_data WHERE c IN (2, 3, 4, 5)').fetchall()
if input_rows:
    cur.execute('DELETE FROM input_data WHERE c IN (2, 3, 4, 5)')
    migrated_input = [(y, locomotive, r, swap_map.get(int(c), int(c)), v) for y, locomotive, r, c, v in input_rows]
    cur.executemany('INSERT INTO input_data (y, locomotive, r, c, v) VALUES (?, ?, ?, ?, ?)', migrated_input)

# Archive data
archive_rows = cur.execute('SELECT y, measurement_date, locomotive, repair_type, r, c, v FROM archive_data WHERE c IN (2, 3, 4, 5)').fetchall()
if archive_rows:
    cur.execute('DELETE FROM archive_data WHERE c IN (2, 3, 4, 5)')
    migrated_archive = [(y, measurement_date, locomotive, repair_type, r, swap_map.get(int(c), int(c)), v) for y, measurement_date, locomotive, repair_type, r, c, v in archive_rows]
    cur.executemany('INSERT INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)', migrated_archive)

# Remove the meta flag so if someone runs it again it would work (but we will remove the python function)
cur.execute('DELETE FROM app_meta WHERE k="greben_prokat_swap_v1"')

conn.commit()
print('Reverted!')

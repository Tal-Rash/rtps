import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add table creation
create_table = '            cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")\n            conn.commit()'
text = text.replace('            conn.commit()', create_table, 1)

# 2. Add load logic to load_state
load_logic = """
        month_hint = ""
        try:
            m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
            hint_row = cur.execute("SELECT hint FROM month_hints WHERE y=? AND m=?", (year, m_str)).fetchone()
            if hint_row:
                month_hint = str(hint_row["hint"])
        except Exception:
            pass

    return {"""

text = text.replace('    return {', load_logic, 1)
text = text.replace('"ts_norms_data": ts_norms_data,', '"ts_norms_data": ts_norms_data,\n        "month_hint": month_hint,')

# 3. Add save logic to api_save_state
save_logic1 = """        vacations = payload.get("vacations")
        ts_norms_data = payload.get("ts_norms_data")
        month_hint = payload.get("month_hint")"""

text = text.replace('        vacations = payload.get("vacations")\n        ts_norms_data = payload.get("ts_norms_data")', save_logic1)

save_logic2 = """
            if month_hint is not None:
                m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
                cur.execute("INSERT OR REPLACE INTO month_hints (y, m, hint) VALUES (?, ?, ?)", (year, m_str, str(month_hint)))

            conn.commit()"""

text = text.replace('            conn.commit()', save_logic2)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.30"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated app.py for month hints")

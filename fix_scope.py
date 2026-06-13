import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Clean up load_system_dates
bad_load_system_dates = '''
        month_hint = ""
        try:
            m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
            hint_row = cur.execute("SELECT hint FROM month_hints WHERE y=? AND m=?", (year, m_str)).fetchone()
            if hint_row:
                month_hint = str(hint_row["hint"])
        except Exception:
            pass

    return {'''
text = text.replace(bad_load_system_dates, '\n    return {')

# 2. Add month_hint code to load_state properly
good_load_state_add = '''        ts_norms_data = {}
        try:
            norms_rows = cur.execute("SELECT r, c, v FROM ts_norms_data WHERE y=?", (year,)).fetchall()
            for r in norms_rows:
                ts_norms_data.setdefault(int(r["r"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

        month_hint = ""
        try:
            m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
            hint_row = cur.execute("SELECT hint FROM month_hints WHERE y=? AND m=?", (year, m_str)).fetchone()
            if hint_row:
                month_hint = str(hint_row["hint"])
        except Exception:
            pass

    return {'''

text = re.sub(r'        ts_norms_data = \{\}\n        try:\n            norms_rows = cur\.execute\("SELECT r, c, v FROM ts_norms_data WHERE y=\?", \(year,\)\)\.fetchall\(\)\n            for r in norms_rows:\n                ts_norms_data\.setdefault\(int\(r\["r"\]\), \{\}\)\[int\(r\["c"\]\)\] = text\(r\["v"\]\)\n        except Exception:\n            pass\n\n    return \{', good_load_state_add, text)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.36"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed month_hint scope bug")

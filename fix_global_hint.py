import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix load_state
old_load = """
        hint_row = cur.execute("SELECT hint FROM month_hints WHERE y=? AND m=?", (year, m_str)).fetchone()
        month_hint = str(hint_row["hint"]) if hint_row else ""
"""
new_load = """
        hint_row = cur.execute("SELECT v FROM ts_settings WHERE k='month_hint'").fetchone()
        month_hint = str(hint_row["v"]) if hint_row else ""
"""
text = text.replace(old_load, new_load)

# Fix api_save_state
old_save = """
            if month_hint is not None:
                m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
                cur.execute("INSERT OR REPLACE INTO month_hints (y, m, hint) VALUES (?, ?, ?)", (year, m_str, str(month_hint)))
"""
new_save = """
            if month_hint is not None:
                # Save it globally
                cur.execute("INSERT OR REPLACE INTO ts_settings (k, v) VALUES ('month_hint', ?)", (str(month_hint),))
"""
text = text.replace(old_save, new_save)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.47"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed month_hint saving/loading to be global")

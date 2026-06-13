import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace the export_milk logic for counting
old_code = """
        count = 0
        emp_ts = ts_data.get(tab_num, {})
        for d in range(1, days_cnt + 1):
            val = emp_ts.get(d, "")
            if type == "компенсация":
                try:
                    float(val.replace(',', '.'))
                    count += 1
                except ValueError:
                    if val in ["В", "РВ", "ДО", "О", "У", "Б"]: 
                        if val in ["РВ"]: count += 1 # is_milk_cell equivalent
            else:
                try:
                    float(val.replace(',', '.'))
                    count += 1
                except ValueError:
                    if not val and is_workday(year, month, d): 
                        count += 1
"""

new_code = """
        count = 0
        emp_ts = ts_data.get(tab_num, {})
        for d in range(1, days_cnt + 1):
            val = emp_ts.get(d, "").strip().upper()
            if type == "компенсация":
                if "М" in val:
                    count += 1
            else:
                try:
                    float(val.replace(',', '.'))
                    count += 1
                except ValueError:
                    if not val and is_workday(year, month, d): 
                        count += 1
"""

text = text.replace(old_code, new_code)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.43"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed milk count logic")

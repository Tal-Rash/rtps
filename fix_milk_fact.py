import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix is_workday logic
text = text.replace('dt = calendar.datetime.date(y, m, d)', 'dt_obj = dt.date(y, m, d)')
text = text.replace('is_we = dt.weekday() >= 5', 'is_we = dt_obj.weekday() >= 5')

# Improve milk counting logic for fact
old_count_logic = """
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

new_count_logic = """
        count = 0
        emp_ts = ts_data.get(tab_num, {})
        for d in range(1, days_cnt + 1):
            val = emp_ts.get(d, "").strip().upper()
            if type == "компенсация":
                if "М" in val:
                    count += 1
            else:
                # For issue_plan and issue_fact, if "М" is explicitly marked, count it!
                # Even if they put "8М", we should count it as a shift.
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

text = text.replace(old_count_logic, new_count_logic)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.46"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed is_workday and fact counting logic")

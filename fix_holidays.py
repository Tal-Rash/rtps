import sys
import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
script_js = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'

with open(app_py, 'r', encoding='utf-8') as f:
    app_text = f.read()

fixed_holidays_code = """
FIXED_HOLIDAYS = {
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

def load_state(year: int, month: int) -> dict:"""

if 'FIXED_HOLIDAYS' not in app_text:
    app_text = app_text.replace("def load_state(year: int, month: int) -> dict:", fixed_holidays_code)

if '"system_dates"' not in app_text:
    app_text = app_text.replace(
        'return {',
        'return {\n        "system_dates": load_system_dates(year),'
    )

app_text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.27"', app_text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(app_text)


with open(script_js, 'r', encoding='utf-8') as f:
    js_text = f.read()

# Update script.js Headers
header_orig = """      const headTh = document.createElement("th");
      headTh.className = "col-day";
      if ([0, 6].includes(new Date(year, month - 1, d).getDay())) {
        headTh.className += " holiday-col";
      }
      headTh.textContent = d;
      trHead.appendChild(headTh);"""

header_new = """      const headTh = document.createElement("th");
      headTh.className = "col-day";
      let isH = false, isT = false;
      if (appState.system_dates) {
        isT = appState.system_dates.transfer.some(date => date[0] === month && date[1] === d);
        isH = appState.system_dates.holiday.some(date => date[0] === month && date[1] === d);
      }
      const isW = [0, 6].includes(new Date(year, month - 1, d).getDay());
      if (isH) {
        headTh.className += " bg-holiday";
      } else if (isW || isT) {
        headTh.className += " bg-weekend";
      }
      headTh.textContent = d;
      trHead.appendChild(headTh);"""

if "if ([0, 6].includes(new Date(year, month - 1, d).getDay())) {" in js_text:
    js_text = js_text.replace(header_orig, header_new)
elif "bg-weekend" in js_text and "isH" not in js_text:
    # already partially modified by previous commits? Let's use regex
    pass

# Update cell class assignment
cell_regex = re.compile(r'let tdClass = "col-day";\s+if \(isWeekend \|\| val === "В"\) \{.*?\s+\}\s+if \(val\.match', re.DOTALL)

cell_new = """let tdClass = "col-day";
        let isH = false, isT = false;
        if (appState.system_dates) {
          isT = appState.system_dates.transfer.some(date => date[0] === month && date[1] === d);
          isH = appState.system_dates.holiday.some(date => date[0] === month && date[1] === d);
        }
        
        if (val === "О" || val === "ДО") {
          tdClass += " bg-vacation";
        } else if (val === "К" || val === "У") {
          tdClass += " bg-trip";
        } else if (val === "Б" || val === "РВ") {
          tdClass += " bg-ill";
        } else if (isH) {
          tdClass += " bg-holiday";
        } else if (isWeekend || isT || val === "В") {
          tdClass += " bg-weekend";
        }
        if (val.match"""

js_text = cell_regex.sub(cell_new, js_text)

# Also fix the header if the regex didn't catch it
head_regex = re.compile(r'const headTh = document\.createElement\("th"\);\s+headTh\.className = "col-day";\s+if \(\[0, 6\]\.includes\(new Date.*?headTh\.className \+= " bg-weekend";\s+\}\s+headTh\.textContent = d;\s+trHead\.appendChild\(headTh\);', re.DOTALL)
js_text = head_regex.sub(header_new, js_text)


with open(script_js, 'w', encoding='utf-8') as f:
    f.write(js_text)

print("Updated app.py and script.js!")

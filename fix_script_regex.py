import re

filepath = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

pattern = re.compile(r'let tdClass = "col-day";\s*if \(isWeekend\).*?if \(val\.match\(/', re.DOTALL)
replacement = """let tdClass = "col-day";
        if (isWeekend || val === "В") {
          tdClass += " bg-weekend";
        } else if (val === "О" || val === "ДО") {
          tdClass += " bg-vacation";
        } else if (val === "К") {
          tdClass += " bg-trip";
        } else if (val === "Б" || val === "У" || val === "РВ") {
          tdClass += " bg-ill";
        }
        if (val.match(/"""

new_text = pattern.sub(replacement, text)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_text)
print("Replaced script.js using regex")

import sys

filepath = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

# We know the exact lines with the  characters are lines 116-119
# We will just replace them using regex or string replace

orig = """        let tdClass = "col-day";
        if (isWeekend) tdClass += " holiday-col";
        if (val === "") tdClass += " holiday-col";
        if (val === "" || val === "" || val === "" || val === "" || val === "") tdClass += " transfer-col";
        if (val === "") tdClass += " holiday-col";"""

replacement = """        let tdClass = "col-day";
        if (isWeekend || val === "В") {
          tdClass += " bg-weekend";
        } else if (val === "О" || val === "ДО") {
          tdClass += " bg-vacation";
        } else if (val === "К") {
          tdClass += " bg-trip";
        } else if (val === "Б" || val === "У" || val === "РВ") {
          tdClass += " bg-ill";
        }"""

if orig in text:
    text = text.replace(orig, replacement)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Fixed script.js successfully")
else:
    print("Could not find the exact corrupted lines in script.js")

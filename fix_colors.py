import sys

filepath = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacement = """
        let tdClass = "col-day";
        if (isWeekend || val === "В") {
          tdClass += " bg-weekend";
        } else if (val === "О" || val === "ДО") {
          tdClass += " bg-vacation";
        } else if (val === "К") {
          tdClass += " bg-trip";
        } else if (val === "Б" || val === "У" || val === "РВ") {
          tdClass += " bg-ill";
        }
"""

# The original lines in the file
orig = """
        let tdClass = "col-day";
        if (isWeekend) tdClass += " holiday-col";
        if (val === "В") tdClass += " holiday-col";
        if (val === "РВ" || val === "К" || val === "ДО" || val === "У" || val === "Б") tdClass += " transfer-col";
        if (val === "О") tdClass += " holiday-col";
"""

if orig.strip() in text:
    text = text.replace(orig.strip(), replacement.strip())
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Replaced successfully")
else:
    print("Original text not found in file")

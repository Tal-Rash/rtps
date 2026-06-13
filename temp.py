import codecs

with open(r'g:\Мой диск\Codex\Windows\src\Табель учета\Табель учета.py', 'rb') as f:
    text = f.read().decode('utf-8', errors='ignore')

for line in text.split('\n'):
    if 'QColor' in line or 'txt in' in line or 'txt ==' in line:
        print(line.strip())

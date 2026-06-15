import glob
files = glob.glob(r'g:\Мой диск\Codex\rtps\*\app.py')
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    content = content.replace('reload=True', 'reload=False')
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
print("Done")

import glob

files = glob.glob(r'g:\Мой диск\Codex\rtps\*\app.py')
for f in files:
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    new_content = content.replace('sqlite3.connect(ROOT.parent / "base" / "web_users.db")', 'sqlite3.connect(DB_FILE)')
    if new_content != content:
        with open(f, 'w', encoding='utf-8') as file:
            file.write(new_content)
        print(f"Fixed {f}")

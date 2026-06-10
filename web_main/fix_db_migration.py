import os
from pathlib import Path
import sqlite3

def fix_main_db(app_path):
    path = Path(app_path)
    if not path.exists(): return
    content = path.read_text("utf-8")
    
    # Inject auto-migration for modules column
    migration_code = '''
def init_db() -> None:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'view',
                full_name TEXT NOT NULL DEFAULT '',
                modules TEXT NOT NULL DEFAULT 'zamer_kp,grafik_ppr,spravochnik,admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Auto-migrate: add modules column if missing
        try:
            existing_cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
            if "modules" not in existing_cols:
                cur.execute("ALTER TABLE users ADD COLUMN modules TEXT NOT NULL DEFAULT 'zamer_kp,grafik_ppr,spravochnik,admin'")
        except Exception:
            pass
'''
    if "Auto-migrate: add modules column if missing" not in content:
        # replace the old init_db
        import re
        content = re.sub(r'def init_db\(\) -> None:.*?CREATE TABLE IF NOT EXISTS users.*?\)"""\)', migration_code.strip(), content, flags=re.DOTALL)
        path.write_text(content, "utf-8")
        print("Fixed web_main init_db")
        
fix_main_db("G:/Мой диск/Codex/rtps/web_main/app.py")

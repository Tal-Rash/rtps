import os
import re
from pathlib import Path

def update_web_main():
    path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
    content = path.read_text("utf-8")
    
    # Update init_db to add modules
    init_db_code = '''def init_db() -> None:
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    password TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    allowed_modules TEXT NOT NULL
                )
            """)
            cur = conn.cursor()
            
            # auto migrate
            try:
                cols = {row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()}
                if "allowed_modules" not in cols:
                    cur.execute("ALTER TABLE users ADD COLUMN allowed_modules TEXT NOT NULL DEFAULT 'zamer_kp,grafik_ppr,spravochnik,admin'")
            except Exception as e:
                print("migration error:", e)
                
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users (password, full_name, role, allowed_modules) VALUES (?, ?, ?, ?)",
                    ("12345", " (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,admin")
                )
    except Exception as e:
        print(f"Init DB Error: {e}")'''

    content = re.sub(r'def init_db\(\) -> None:.*?print\(f"Init DB Error: \{e\}"\)', init_db_code, content, flags=re.DOTALL)
    path.write_text(content, "utf-8")
    print("Updated web_main init_db")

def update_app_secret(app_name):
    path = Path(f"G:/Мой диск/Codex/rtps/{app_name}/app.py")
    content = path.read_text("utf-8")
    
    secret_code = '''
ROOT = Path(__file__).parent
SHARED_DATA_DIR = ROOT.parent / "data"

def load_web_secret() -> str:
    secret = os.environ.get("WEB_SECRET", "").strip()
    if secret: return secret
    
    secret_file = SHARED_DATA_DIR / "web_secret.txt"
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"

WEB_SECRET = load_web_secret()
'''

    if app_name == "web_zamer_kp":
        content = re.sub(r'def config\(key: str.*?LEGACY_WEB_SECRET = config\("LEGACY_WEB_SECRET", default=""\)', secret_code.strip(), content, flags=re.DOTALL)
    elif app_name == "web_spravochnik":
        # in spravochnik, WEB_SECRET is defined via os.environ.get
        content = re.sub(r'WEB_SECRET = os\.environ\.get\("WEB_SECRET", ""\)', secret_code.strip(), content)
        # make sure ROOT and SHARED_DATA_DIR aren't defined twice
        if "ROOT =" not in content:
            pass
    path.write_text(content, "utf-8")
    print(f"Updated {app_name} secret")

update_web_main()
update_app_secret("web_zamer_kp")
update_app_secret("web_spravochnik")

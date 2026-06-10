import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

# Add init_db function
init_db_func = '''
def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
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
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users (password, full_name, role, allowed_modules) VALUES (?, ?, ?, ?)",
                    ("12345", "Администратор (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,admin")
                )
                print("Создан администратор по умолчанию. Пароль: 12345")
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()
'''

if "def init_db() -> None:" not in content:
    content = content.replace("SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}\nDB_FILE = ROOT.parent / \"base\" / \"common_database.db\"", 
                              "SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}\nDB_FILE = ROOT.parent / \"base\" / \"common_database.db\"\n" + init_db_func)

app_path.write_text(content, "utf-8")
print("Added init_db to app.py")

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_FILE = ROOT.parent / "base" / "common_database.db"
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

with sqlite3.connect(DB_FILE) as conn:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            password TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            allowed_modules TEXT NOT NULL
        )
    ''')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        # Временный пароль для входа: 12345
        conn.execute(
            "INSERT INTO users (password, full_name, role, allowed_modules) VALUES (?, ?, ?, ?)",
            ("12345", "Администратор (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,admin")
        )
        print("Создан администратор по умолчанию. Пароль: 12345")
    else:
        print("Таблица users уже существует и не пуста.")

import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "base" / "web_users.db"

def fix_users():
    if not DB_FILE.exists():
        return
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET allowed_modules = 'zamer_kp,grafik_ppr,spravochnik,admin' WHERE password = '12345'")
        print("Fixed 12345 user allowed_modules.")

if __name__ == "__main__":
    fix_users()

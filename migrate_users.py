import sqlite3
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMON_DB = ROOT / "base" / "common_database.db"
WEB_USERS_DB = ROOT / "base" / "web_users.db"

def migrate():
    if not COMMON_DB.exists():
        print(f"{COMMON_DB} does not exist. Nothing to migrate.")
        return

    # Ensure base directory exists
    WEB_USERS_DB.parent.mkdir(parents=True, exist_ok=True)

    print("Connecting to databases...")
    conn_common = sqlite3.connect(COMMON_DB)
    conn_common.row_factory = sqlite3.Row
    
    conn_web = sqlite3.connect(WEB_USERS_DB)
    
    cur_common = conn_common.cursor()
    cur_web = conn_web.cursor()

    # 1. Create tables in web_users.db
    print("Ensuring tables exist in web_users.db...")
    cur_web.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            password TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            allowed_modules TEXT
        )
    """)
    cur_web.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            login_time TEXT NOT NULL
        )
    """)
    conn_web.commit()

    # 2. Check if users table exists in common_database.db
    try:
        cur_common.execute("SELECT COUNT(*) FROM users")
        print("Table 'users' found in common_database.db. Starting migration...")
        
        # Migrate users
        users_rows = cur_common.execute("SELECT id, full_name, password, role, allowed_modules FROM users").fetchall()
        for row in users_rows:
            # Check if user already exists in web_users.db to prevent duplicates on multiple runs
            exists = cur_web.execute("SELECT 1 FROM users WHERE id=?", (row["id"],)).fetchone()
            if not exists:
                cur_web.execute(
                    "INSERT INTO users (id, full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], row["full_name"], row["password"], row["role"], row["allowed_modules"])
                )
        print(f"Migrated {len(users_rows)} users.")

        # Migrate login_logs
        try:
            logs_rows = cur_common.execute("SELECT id, user_name, login_time FROM login_logs").fetchall()
            for row in logs_rows:
                exists = cur_web.execute("SELECT 1 FROM login_logs WHERE id=?", (row["id"],)).fetchone()
                if not exists:
                    cur_web.execute(
                        "INSERT INTO login_logs (id, user_name, login_time) VALUES (?, ?, ?)",
                        (row["id"], row["user_name"], row["login_time"])
                    )
            print(f"Migrated {len(logs_rows)} login logs.")
        except sqlite3.OperationalError:
            print("No login_logs table in common_database.db.")
            
        conn_web.commit()

        # 3. Drop tables from common_database.db to clean up
        print("Dropping migrated tables from common_database.db...")
        cur_common.execute("DROP TABLE users")
        try:
            cur_common.execute("DROP TABLE login_logs")
        except sqlite3.OperationalError:
            pass
        conn_common.commit()
        
        print("Migration complete! Users and login logs have been moved to web_users.db.")
        
    except sqlite3.OperationalError as e:
        print(f"Skipping migration. Reason: {e} (Already migrated or table missing)")

    finally:
        conn_common.close()
        conn_web.close()

if __name__ == "__main__":
    migrate()

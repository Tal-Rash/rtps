import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

old_login = '''            try:
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
                    user_record = cur.fetchone()
            except Exception as e:
                print(f"DB Error: {e}")
                
            if user_record:'''

new_login = '''            password = password.strip()
            db_err = ""
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
                    user_record = cur.fetchone()
            except Exception as e:
                print(f"DB Error: {e}")
                db_err = f"<p>DB Error: {e} | Path: {DB_FILE}</p>"
                
            if user_record:'''

content = content.replace(old_login, new_login)

old_error = '''                LOGIN_TEMPLATE.replace("{{USER}}", "")
                + "<p style='text-align:center;color:#b00020;'>Неверный пароль</p>",'''

new_error = '''                LOGIN_TEMPLATE.replace("{{USER}}", "")
                + f"<p style='text-align:center;color:#b00020;'>Неверный пароль ({password})</p>"
                + db_err,'''

content = content.replace(old_error, new_error)

app_path.write_text(content, "utf-8")
print("Added login debug!")

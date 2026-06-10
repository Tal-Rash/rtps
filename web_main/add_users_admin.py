import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

USERS_TEMPLATE = """
USERS_TEMPLATE = '''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Управление доступом</title>
  <style>
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:#f4f7fb; color:#102033; padding:20px; }
    .card { max-width:800px; margin:0 auto; background:#fff; border:1px solid #d9e2ef; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.08); }
    table { width:100%; border-collapse:collapse; margin-top:20px; }
    th, td { text-align:left; padding:10px; border-bottom:1px solid #d9e2ef; }
    input, select, button { padding:8px; border-radius:6px; border:1px solid #d9e2ef; font:inherit; }
    button { background:#276ef1; color:#fff; font-weight:700; cursor:pointer; border:0; }
    .btn-danger { background:#e11d48; }
    .flex { display:flex; gap:10px; align-items:center; }
    .muted { color:#607086; font-size:13px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="flex" style="justify-content:space-between; margin-bottom:20px;">
        <h1 style="margin:0;">Управление доступом</h1>
        <a href="/" style="color:#276ef1; text-decoration:none; font-weight:bold;">На главную</a>
    </div>
    
    <form method="post" action="/users/add" style="background:#f8fafc; padding:16px; border-radius:12px; margin-bottom:20px;">
      <h3 style="margin-top:0;">Добавить пользователя</h3>
      <div class="flex" style="flex-wrap:wrap;">
        <input name="full_name" placeholder="Фамилия И.О." required>
        <input name="password" placeholder="Пароль (ПИН)" required>
        <select name="role">
            <option value="viewer">Зритель</option>
            <option value="editor">Редактор</option>
            <option value="admin">Администратор</option>
        </select>
        <input name="modules" placeholder="zamer_kp,grafik_ppr" value="zamer_kp,grafik_ppr" style="flex:1;">
        <button type="submit">Добавить</button>
      </div>
      <p class="muted" style="margin:5px 0 0;">Доступные модули через запятую: zamer_kp, grafik_ppr, spravochnik</p>
    </form>

    <table>
      <thead>
        <tr>
          <th>ID</th><th>ФИО</th><th>Пароль</th><th>Роль</th><th>Модули</th><th>Действие</th>
        </tr>
      </thead>
      <tbody>
        {{USERS_ROWS}}
      </tbody>
    </table>
  </div>
</body>
</html>
'''
"""

if "USERS_TEMPLATE" not in content:
    content = content.replace("def _cookie_value", USERS_TEMPLATE + "\ndef _cookie_value")

# In do_GET
get_logic = '''        if parsed.path == "/users":
            if not user_id or "admin" not in modules:
                _redirect(self, "/")
                return
            
            rows_html = ""
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, password, role, allowed_modules FROM users ORDER BY id")
                    for u in cur.fetchall():
                        rows_html += f"<tr><td>{u[0]}</td><td>{u[1]}</td><td>{u[2]}</td><td>{u[3]}</td><td>{u[4]}</td>"
                        rows_html += f"<td><form method='post' action='/users/delete' style='margin:0;'><input type='hidden' name='id' value='{u[0]}'><button class='btn-danger' type='submit'>Удалить</button></form></td></tr>"
            except Exception as e:
                rows_html = f"<tr><td colspan='6'>Ошибка БД: {e}</td></tr>"
                
            _send_html(self, USERS_TEMPLATE.replace("{{USERS_ROWS}}", rows_html))
            return
'''
if 'parsed.path == "/users"' not in content:
    content = content.replace('        if parsed.path == "/":', get_logic + '\n        if parsed.path == "/":')

# In do_POST
post_logic = '''        if parsed.path == "/users/add":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?)",
                        (form.get("full_name", [""])[0], form.get("password", [""])[0], form.get("role", ["viewer"])[0], form.get("modules", [""])[0]))
            except Exception as e:
                print("Error adding user:", e)
            _redirect(self, "/users")
            return
            
        if parsed.path == "/users/delete":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("DELETE FROM users WHERE id=?", (form.get("id", ["0"])[0],))
            except Exception as e:
                print("Error deleting user:", e)
            _redirect(self, "/users")
            return
'''
if 'parsed.path == "/users/add"' not in content:
    content = content.replace('        if parsed.path == "/login":', post_logic + '\n        if parsed.path == "/login":')

# In render_home, add a link to Admin Panel if user is admin
home_admin_link = '''        .replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})")
        .replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})")''' # dummy
if "Управление доступом" not in content:
    content = content.replace(
        '.replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})")',
        '.replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})" + (" <a href=\'/users\' style=\'margin-left:10px; color:#1d4ed8;\'>Управление доступом</a>" if "admin" in mods else ""))'
    )

app_path.write_text(content, "utf-8")
print("Updated web_main with Admin UI!")

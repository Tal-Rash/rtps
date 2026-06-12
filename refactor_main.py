import os
import re

app_path = r'g:\Мой диск\Codex\rtps\web_main\app.py'
templates_dir = r'g:\Мой диск\Codex\rtps\web_main\templates'

os.makedirs(templates_dir, exist_ok=True)

with open(app_path, 'r', encoding='utf-8') as f:
    text = f.read()

patterns = {
    'HOME_TEMPLATE': r'HOME_TEMPLATE\s*=\s*"""(.*?)"""',
    'LOGIN_TEMPLATE': r'LOGIN_TEMPLATE\s*=\s*"""(.*?)"""',
    'USERS_TEMPLATE': r"USERS_TEMPLATE\s*=\s*'''(.*?)'''",
    'LOGS_TEMPLATE': r"LOGS_TEMPLATE\s*=\s*'''(.*?)'''",
}

replacements = {
    'HOME_TEMPLATE': 'home.html',
    'LOGIN_TEMPLATE': 'login.html',
    'USERS_TEMPLATE': 'users.html',
    'LOGS_TEMPLATE': 'logs.html'
}

for var_name, pattern in patterns.items():
    match = re.search(pattern, text, flags=re.DOTALL)
    if match:
        html_content = match.group(1).strip() + '\n'
        filename = replacements[var_name]
        with open(os.path.join(templates_dir, filename), 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        replacement_code = f'{var_name} = (ROOT / "templates" / "{filename}").read_text(encoding="utf-8")'
        text = text[:match.start()] + replacement_code + text[match.end():]

with open(app_path, 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")

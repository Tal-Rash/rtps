import re

yaml_file = r'g:\Мой диск\Codex\rtps\.github\workflows\deploy.yml'
with open(yaml_file, 'r', encoding='utf-8') as f:
    text = f.read()

# Insert pip install openpyxl before systemctl daemon-reload
insert_code = '''          restore_path web_tabel/data

          python3 -m pip install openpyxl || pip3 install openpyxl --break-system-packages || true

          for unit in deploy/*.service; do'''

text = text.replace('''          restore_path web_tabel/data

          for unit in deploy/*.service; do''', insert_code)

with open(yaml_file, 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated deploy.yml")

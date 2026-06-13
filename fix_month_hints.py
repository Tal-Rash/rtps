import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix the month_hints creation block
old_code = """
            cur.execute("DROP TABLE IF EXISTS vacations")
            cur.execute("ALTER TABLE vacations_new RENAME TO vacations")
            cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")

            if month_hint is not None:
"""

new_code = """
            cur.execute("DROP TABLE IF EXISTS vacations")
            cur.execute("ALTER TABLE vacations_new RENAME TO vacations")

        cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")

"""

# Let's use a simpler replace
text = text.replace('cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")', '')

# Now inject it at the end of init_db
injection = '''
        cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")
'''

text = text.replace('        cur = conn.cursor()', '        cur = conn.cursor()' + injection)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.44"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed month_hints creation")

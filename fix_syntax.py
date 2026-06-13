import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix the broken line
text = text.replace('text = str(raw_text).replace(";", "\n").replace(",", "\n")', 'text = str(raw_text).replace(";", "\\n").replace(",", "\\n")')

# Also just to be safe, I'll search for the unterminated string literal and fix it directly if the above replace fails because of weird line breaks
bad_code1 = 'text = str(raw_text).replace(";", "\n'
bad_code2 = '").replace(",", "\n'
bad_code3 = '")'

# Let's just use regex to fix it
text = re.sub(r'text = str\(raw_text\)\.replace\(";", "\n\s*"\)\.replace\(",", "\n\s*"\)', r'text = str(raw_text).replace(";", "\\n").replace(",", "\\n")', text)

# Actually, if I look at the error:
# text = str(raw_text).replace(";", "
#                                       ^
# It literally broke the line.
text = re.sub(r'text = str\(raw_text\)\.replace\(";", "\n\s*"\)\.replace\(",", "\n\s*"\)', 'text = str(raw_text).replace(";", "\\\\n").replace(",", "\\\\n")', text, flags=re.MULTILINE)

# If it didn't match, let's just do a blanket replace of the block
block_to_replace = r'''        for col_idx, raw_text in rows:
            if not raw_text:
                continue
            text = str(raw_text).replace(";", "
").replace(",", "
")
            for line in text.splitlines():'''

replacement = '''        for col_idx, raw_text in rows:
            if not raw_text:
                continue
            text = str(raw_text).replace(";", "\\n").replace(",", "\\n")
            for line in text.splitlines():'''

text = text.replace(block_to_replace, replacement)

# Bump version
text = re.sub(r'APP_VERSION = "web-tabel-1\.\d+"', 'APP_VERSION = "web-tabel-1.29"', text)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(text)

print("Fixed syntax error")

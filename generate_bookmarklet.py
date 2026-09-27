# -*- coding: utf-8 -*-
"""
Скрипт генерирует минифицированную ссылку javascript:... для закладки браузера из файла bookmarklet_code.js
"""

import urllib.parse
from pathlib import Path

js_path = Path("bookmarklet_code.js")
out_path = Path("BOOKMARKLET_LINK.txt")

if js_path.exists():
    raw_js = js_path.read_text(encoding="utf-8")
    
    # Простая очистка однострочных комментариев и переносов строк
    lines = []
    for line in raw_js.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*") or line.startswith("*"):
            continue
        lines.append(line)
        
    js_code = " ".join(lines)
    bookmarklet = "javascript:" + urllib.parse.quote(js_code)
    
    out_path.write_text(bookmarklet, encoding="utf-8")
    print(f"Ссылка для закладки создана и сохранена в {out_path}")

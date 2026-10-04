# -*- coding: utf-8 -*-
"""
Генератор автономного bookmarklet URL из файла standalone_bookmarklet.js.
"""

import urllib.parse
from pathlib import Path

DIR = Path(__file__).resolve().parent
js_path = DIR / "standalone_bookmarklet.js"
out_path = DIR / "BOOKMARKLET_LINK.txt"

if js_path.exists():
    raw_js = js_path.read_text(encoding="utf-8")
    
    # Очистка от комментариев и лишних пробелов
    lines = []
    for line in raw_js.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*") or line.startswith("*"):
            continue
        lines.append(line)
        
    js_code = " ".join(lines)
    bookmarklet = "javascript:" + urllib.parse.quote(js_code)
    
    out_path.write_text(bookmarklet, encoding="utf-8")
    print(f"Автономная ссылка для закладки сохранена в {out_path}")

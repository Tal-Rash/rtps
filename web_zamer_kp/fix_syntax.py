import re
from pathlib import Path

def fix_syntax(app_path):
    path = Path(app_path)
    content = path.read_text("utf-8")
    
    # Remove the legacy secret block entirely from zamer_kp
    content = re.sub(r'try:\s+if LEGACY_WEB_SECRET_FILE\.exists\(\):.*?LEGACY_WEB_SECRET = ""', 'LEGACY_WEB_SECRET = ""', content, flags=re.DOTALL)
    path.write_text(content, "utf-8")

fix_syntax("G:/Мой диск/Codex/rtps/web_zamer_kp/app.py")

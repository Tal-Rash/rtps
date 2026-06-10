import os
from pathlib import Path

def fix_zamer_kp(app_path):
    path = Path(app_path)
    if not path.exists(): return
    content = path.read_text("utf-8")
    
    new_code = '''
def config(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val is not None:
        return val
    try:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text("utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip()
    except Exception:
        pass
    return default

WEB_SECRET = config("WEB_SECRET", default="opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024")
LEGACY_WEB_SECRET = config("LEGACY_WEB_SECRET", default="")
'''
    
    import re
    # We want to replace load_web_secret and the WEB_SECRET definitions
    content = re.sub(r'def load_web_secret\(\) -> str:.*?LEGACY_WEB_SECRET = ""', new_code.strip(), content, flags=re.DOTALL)
    path.write_text(content, "utf-8")
    print("Fixed zamer_kp secret")

fix_zamer_kp("G:/Мой диск/Codex/rtps/web_zamer_kp/app.py")

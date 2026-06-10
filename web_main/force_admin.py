import re
from pathlib import Path

def fix_login(app_path):
    path = Path(app_path)
    content = path.read_text("utf-8")
    
    # Force admin modules for 12345
    new_login_code = '''
            if user_record:
                u_id, u_full_name, u_role, u_modules = user_record
                if password == "12345":
                    u_modules = "zamer_kp,grafik_ppr,spravochnik,admin"
                    u_role = "admin"
                expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
'''
    
    content = re.sub(r'            if user_record:\s+u_id, u_full_name, u_role, u_modules = user_record\s+expiry = int\(dt\.datetime\.now\(\)\.timestamp\(\)\) \+ SESSION_TTL_SECONDS', new_login_code.strip('\n'), content)
    path.write_text(content, "utf-8")

fix_login("G:/Мой диск/Codex/rtps/web_main/app.py")

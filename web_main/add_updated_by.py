import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_zamer_kp/app.py")
content = app_path.read_text("utf-8")

# 1. Update setup_db
setup_db_old = '''    if "wheel_pair_count" not in existing_inventory_cols:
        conn.execute("ALTER TABLE inventory ADD COLUMN wheel_pair_count INT NOT NULL DEFAULT 0")'''
setup_db_new = '''    if "wheel_pair_count" not in existing_inventory_cols:
        conn.execute("ALTER TABLE inventory ADD COLUMN wheel_pair_count INT NOT NULL DEFAULT 0")
        
    kp_data_cols = [row[1] for row in conn.execute("PRAGMA table_info(kp_data)")]
    if "updated_by" not in kp_data_cols:
        conn.execute("ALTER TABLE kp_data ADD COLUMN updated_by TEXT")'''
content = content.replace(setup_db_old, setup_db_new)

# 2. Update save_state signature
content = content.replace(
    'def save_state(payload: dict) -> dict:',
    'def save_state(payload: dict, full_name: str = "") -> dict:'
)

# 3. Inside save_state, where we insert into kp_data
insert_old = '''                    conn.execute(
                        "INSERT OR REPLACE INTO kp_data (locomotive, key, value, updated_at) VALUES (?, ?, ?, ?)",
                        (locomotive, key, value, ts),
                    )'''
insert_new = '''                    conn.execute(
                        "INSERT OR REPLACE INTO kp_data (locomotive, key, value, updated_at, updated_by) VALUES (?, ?, ?, ?, ?)",
                        (locomotive, key, value, ts, full_name),
                    )'''
content = content.replace(insert_old, insert_new)

# 4. Inside do_POST /api/state
post_old = '''        if route == "/api/state":
            session = require_auth(self, need_edit=True)
            if not session:
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                send_json(self, save_state(payload))'''
# Wait, do_POST might look slightly different. Let's find exactly.
if 'send_json(self, save_state(payload))' in content:
    content = content.replace(
        'send_json(self, save_state(payload))',
        'send_json(self, save_state(payload, full_name=session[3] if session and len(session) > 3 else ""))'
    )

app_path.write_text(content, "utf-8")
print("Updated web_zamer_kp with updated_by logic!")

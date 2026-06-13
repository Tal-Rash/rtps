import os, sqlite3

def update_admin():
    db_path = os.path.join('g:/Мой диск/Codex/rtps/base', 'common_database.db')
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE users SET allowed_modules='zamer_kp:admin,spravochnik:admin' WHERE id='admin'")
        conn.commit()
        print('Admin permissions updated')
    finally:
        conn.close()

if __name__ == '__main__':
    update_admin()

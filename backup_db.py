import sqlite3
import datetime
import os
import zipfile
import sys
from pathlib import Path

# Пути
ROOT_DIR = Path(__file__).resolve().parent
DB_PATHS = [
    ROOT_DIR / "base" / "common_database.db",
    ROOT_DIR / "base" / "web_users.db"
]
BACKUP_DIR = ROOT_DIR / "backups"

def backup_and_send():
    BACKUP_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = BACKUP_DIR / f"rtps_db_backup_{timestamp}.zip"

    try:
        print(f"[{timestamp}] Архивация баз данных...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for db_path in DB_PATHS:
                if not db_path.exists():
                    print(f"[{timestamp}] Предупреждение: База данных {db_path} не найдена. Пропуск.")
                    continue
                
                temp_db_path = BACKUP_DIR / f"temp_{db_path.name}"
                print(f"[{timestamp}] Создание безопасной копии {db_path.name} (с учетом WAL)...")
                # Используем встроенный механизм бэкапа SQLite, чтобы данные не побились, если кто-то пишет в базу
                with sqlite3.connect(db_path) as src, sqlite3.connect(temp_db_path) as dst:
                    src.backup(dst)

                zipf.write(temp_db_path, arcname=db_path.name)

                # Удаляем временную распакованную базу
                if temp_db_path.exists():
                    os.remove(temp_db_path)
            
        print(f"[{timestamp}] Локальный бэкап успешно создан: {zip_path}")

        # Удаляем старые бэкапы (старше 30 дней)
        print(f"[{timestamp}] Очистка старых бэкапов...")
        retention_days = 30
        now = datetime.datetime.now()
        for f in BACKUP_DIR.glob("*.zip"):
            if f.is_file():
                file_age = now - datetime.datetime.fromtimestamp(f.stat().st_mtime)
                if file_age.days > retention_days:
                    f.unlink()
                    print(f"[{timestamp}] Удален старый архив: {f.name}")

    except Exception as e:
        print(f"[{timestamp}] ПРОИЗОШЛА ОШИБКА: {e}")

if __name__ == "__main__":
    backup_and_send()

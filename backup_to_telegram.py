import sqlite3
import datetime
import requests
import os
import zipfile
import sys
from pathlib import Path
import socket
import urllib3.util.connection as urllib3_cn

def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# ==========================================
# НАСТРОЙКИ (Вставьте свои данные сюда)
# ==========================================
TELEGRAM_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
TELEGRAM_CHAT_ID = "ВАШ_CHAT_ID"

# Пути
ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "base" / "common_database.db"
BACKUP_DIR = ROOT_DIR / "backups"

def backup_and_send():
    if not DB_PATH.exists():
        print(f"Ошибка: База данных {DB_PATH} не найдена.")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    temp_db_path = BACKUP_DIR / f"common_database_backup.db"
    zip_path = BACKUP_DIR / f"rtps_db_backup_{timestamp}.zip"

    try:
        print(f"[{timestamp}] Создание безопасной копии SQLite (с учетом WAL)...")
        # Используем встроенный механизм бэкапа SQLite, чтобы данные не побились, если кто-то пишет в базу
        with sqlite3.connect(DB_PATH) as src, sqlite3.connect(temp_db_path) as dst:
            src.backup(dst)

        print(f"[{timestamp}] Архивация базы...")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(temp_db_path, arcname="common_database.db")

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

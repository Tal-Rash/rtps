from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import unquote


def read_text(path: Path, default: str = "") -> str:
    try:
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            return value if value else default
    except Exception:
        pass
    return default


def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_user_access(
    users_db: Path,
    user_id: str,
    default_role: str,
    default_modules: str,
) -> tuple[str, str] | None:
    if user_id == "legacy":
        return None
    try:
        # Гарантируем закрытие подключения после запроса
        conn = connect_sqlite(users_db)
        try:
            row = conn.execute(
                "SELECT role, allowed_modules FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return str(row["role"] or ""), str(row["allowed_modules"] or "")
        finally:
            conn.close()
    except Exception:
        return None


def _module_tokens(modules: str) -> list[str]:
    return [part.strip() for part in str(modules or "").split(",") if part.strip()]


def module_role(role: str, modules: str, module_name: str) -> str | None:
    tokens = _module_tokens(modules)
    # Администратор всегда имеет полный доступ ко всем модулям
    if role == "admin" or "admin" in tokens:
        return "admin"

    # Проверяем явные правила для конкретного модуля в списке разрешений
    for token in tokens:
        base, sep, access = token.partition(":")
        if base != module_name:
            continue
        if access in ("none", "no"):
            return None
        if access:
            return access
        if role in ("edit", "editor"):
            return "edit"
        return "view"

    # Если для модуля нет явного правила в tokens, права наследуются от глобальной роли
    if role in ("edit", "editor"):
        return "edit"
    if role in ("view", "viewer"):
        return "view"

    return None


def module_has_access(role: str, modules: str, module_name: str) -> bool:
    return module_role(role, modules, module_name) is not None


def module_can_edit(role: str, modules: str, module_name: str) -> bool:
    access = module_role(role, modules, module_name)
    return access in ("admin", "edit", "editor")


def decode_cookie_parts(*parts: str) -> tuple[str, str, str, str]:
    return tuple(unquote(part) for part in parts)  # type: ignore[return-value]

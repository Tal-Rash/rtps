# RTPS Agent Guide

## Goal
When adding a new module to RTPS, connect it to the existing shared auth flow instead of inventing a separate one.

## Shared Helpers
Use the common helper package:
- `rtps_common.connect_sqlite(path)` for SQLite connections
- `rtps_common.resolve_user_access(users_db, user_id, role, modules)` to refresh access from `web_users.db`
- `rtps_common.module_role(role, modules, module_name)` to resolve module permissions
- `rtps_common.module_has_access(role, modules, module_name)` when you only need a yes/no check

## New Module Checklist
1. Add the module route and UI.
2. Reuse the existing `grafik_ppr_session` cookie format.
3. Validate the cookie, then refresh user access from `base/web_users.db`.
4. Check module access with the shared helper.
5. If the module supports editing, verify `edit` rights separately.
6. Register the module in `web_main` or the relevant launcher/menu.
7. Add the module name to `allowed_modules` for users who should see it.
8. Keep database migrations local to the module unless the schema is truly shared.
9. Do not duplicate direct `sqlite3.connect(ROOT.parent / "base" / "web_users.db")` calls.
10. Do not change the cookie format for a single module.

## FastAPI Pattern
```python
from rtps_common import resolve_user_access, module_role

resolved = resolve_user_access(WEB_USERS_DB, user_id, role, modules)
if not resolved:
    return None
role, modules = resolved
access = module_role(role, modules, "new_module")
if not access:
    return None
```

## Handler Pattern
For `BaseHTTPRequestHandler` modules:
- parse the cookie
- verify the session
- resolve the latest access from `web_users.db`
- apply module permissions through the shared helper

## What To Avoid
- separate auth logic per module
- copy-pasting the old access checks from large modules
- new cookie formats
- moving shared code into `base/` if that folder is meant for data

## When To Test
After wiring a new module, verify:
- login
- access without permissions
- access with view permissions
- access with edit permissions
- menu entry visibility

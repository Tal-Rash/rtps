import sys
sys.path.append(r"g:\Мой диск\Codex\rtps\web_tabel")
import app

try:
    print(app.load_state(2026, 6))
except Exception as e:
    import traceback
    traceback.print_exc()

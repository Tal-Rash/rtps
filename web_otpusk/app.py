import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="График Отпусков")
ROOT = Path(__file__).resolve().parent

# Ensure directories exist
(ROOT / "static").mkdir(exist_ok=True)
(ROOT / "templates").mkdir(exist_ok=True)

APP_PREFIX = "/otpusk"

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=ROOT / "static"), name="otpusk_static")

@app.get("/", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse)
async def read_root():
    index_file = ROOT / "templates" / "index.html"
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/vacations")
@app.get(f"{APP_PREFIX}/api/vacations")
async def get_vacations():
    data_file = ROOT / "data" / "mock_data.json"
    if not data_file.exists():
        return []
    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

@app.post("/api/vacations")
@app.post(f"{APP_PREFIX}/api/vacations")
async def save_vacations(request: Request):
    new_data = await request.json()
    data_file = ROOT / "data" / "mock_data.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

DEFAULT_HOLIDAYS = [
    {"month": 0, "name": "Январь", "totalDays": 31, "dates": "1, 2, 3, 4, 5, 6, 7, 8"},
    {"month": 1, "name": "Февраль", "totalDays": 28, "dates": ""},
    {"month": 2, "name": "Март", "totalDays": 31, "dates": "8"},
    {"month": 3, "name": "Апрель", "totalDays": 30, "dates": ""},
    {"month": 4, "name": "Май", "totalDays": 31, "dates": "1, 9"},
    {"month": 5, "name": "Июнь", "totalDays": 30, "dates": "12"},
    {"month": 6, "name": "Июль", "totalDays": 31, "dates": ""},
    {"month": 7, "name": "Август", "totalDays": 31, "dates": ""},
    {"month": 8, "name": "Сентябрь", "totalDays": 30, "dates": ""},
    {"month": 9, "name": "Октябрь", "totalDays": 31, "dates": ""},
    {"month": 10, "name": "Ноябрь", "totalDays": 30, "dates": "4"},
    {"month": 11, "name": "Декабрь", "totalDays": 31, "dates": ""}
]

@app.get("/api/holidays")
@app.get(f"{APP_PREFIX}/api/holidays")
async def get_holidays():
    file_path = ROOT / "data" / "holidays.json"
    if not file_path.exists():
        file_path.parent.mkdir(exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_HOLIDAYS, f, ensure_ascii=False, indent=2)
        return DEFAULT_HOLIDAYS
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.post("/api/holidays")
@app.post(f"{APP_PREFIX}/api/holidays")
async def save_holidays(request: Request):
    data = await request.json()
    file_path = ROOT / "data" / "holidays.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "success"}

if __name__ == "__main__":
    import os
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8085"))
    uvicorn.run("app:app", host=host, port=port, reload=False)

import re

app_py = r'g:\Мой диск\Codex\rtps\web_tabel\app.py'
with open(app_py, 'r', encoding='utf-8') as f:
    text = f.read()

# I will add the endpoints /api/export-sick-email and /api/export-summary

endpoints_code = '''
import io
import base64
from fastapi.responses import FileResponse, StreamingResponse
from urllib.parse import quote

@app.get("/api/export-sick-email")
async def export_sick_email(emp: str, type: str, start: str, end: str, email: str):
    import urllib.parse
    emp = urllib.parse.unquote(emp)
    type = urllib.parse.unquote(type)
    email = urllib.parse.unquote(email)

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        emp_data = cur.execute("SELECT tab_num FROM employees WHERE name=?", (emp,)).fetchone()
        tab_num = str(emp_data["tab_num"]) if emp_data else ""
        
    html_body = f"""
    <html>
    <head>
    <style>
        table {{ border-collapse: collapse; width: 550px; font-family: Arial, sans-serif; border: 1px solid #000000; }}
        td {{ border: 1px solid #000000; padding: 6px; text-align: left; font-size: 13px; }}
    </style>
    </head>
    <body>
        <table>
            <tr>
                <td style="width: 40%;">Табельный номер</td>
                <td style="width: 60%;">{tab_num}</td>
            </tr>
            <tr>
                <td>ФИО сотрудника</td>
                <td>{emp}</td>
            </tr>
            <tr>
                <td>Тип операции</td>
                <td>{type}</td>
            </tr>
            <tr>
                <td style="padding-left: 20px;">Дата начала</td>
                <td>{start}</td>
            </tr>
            <tr>
                <td style="padding-left: 20px;">Дата окончания</td>
                <td>{end}</td>
            </tr>
            <tr>
                <td>Структурное подразделение</td>
                <td>3040 Рудник Таймырский</td>
            </tr>
        </table>
        <br>
    </body>
    </html>
    """

    encoded_subject = base64.b64encode("3040".encode('utf-8')).decode('utf-8')
    mime_subject = f"=?utf-8?B?{encoded_subject}?="
    
    eml_headers = [
        "MIME-Version: 1.0",
        f"To: {email}",
        f"Subject: {mime_subject}",
        "X-Unsent: 1",
        "Content-Type: text/html; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
        "",
        html_body
    ]
    
    eml_data = "\\r\\n".join(eml_headers)
    
    return StreamingResponse(
        io.BytesIO(eml_data.encode('utf-8')),
        media_type="message/rfc822",
        headers={"Content-Disposition": f"attachment; filename=SickLeaveDraft.eml"}
    )
'''

# We also need /api/export-summary for 'Отпуска', 'Отпуска внеплановые', 'Отпуск б/с', 'Учебный отпуск', 'Больничный'
# The python code generate_unpaid_leave_report did an export. We can just generate a CSV or Excel. Since openpyxl is installed now, we can use it!
# Wait, for now let's just make sure the sick-email is there.
# Let's add the endpoints.

if '/api/export-sick-email' not in text:
    text = text.replace('@app.get("/api/state")', endpoints_code + '\n\n@app.get("/api/state")')
    
    with open(app_py, 'w', encoding='utf-8') as f:
        f.write(text)
    print("Added sick email endpoint")
else:
    print("Already added")

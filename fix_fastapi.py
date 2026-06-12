import re
path = r'g:\Мой диск\Codex\rtps\web_main\app.py'
with open(path, 'r', encoding='utf-8') as f:
    data = f.read()

# Pattern matches: templates.TemplateResponse("filename.html", {
data = re.sub(
    r'templates\.TemplateResponse\(\"([^"]+)\",\s*\{',
    r'templates.TemplateResponse(request=request, name="\1", context={',
    data
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(data)
print("Fixed TemplateResponse calls.")

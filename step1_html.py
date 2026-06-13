import re

index_html = r'g:\Мой диск\Codex\rtps\web_tabel\templates\index.html'
with open(index_html, 'r', encoding='utf-8') as f:
    text = f.read()

pattern = re.compile(r'(<div class="table-wrap month-table-wrap">\s*<table id="tabelGrid" class="month-table compact">.*?</table>\s*</div>)', re.DOTALL)

replacement = r'''\1
        <div class="month-hint-wrap" style="margin-top: 10px; display: {{ 'block' if CAN_EDIT else 'none' }};">
          <textarea id="monthHint" class="month-hint" style="width: 100%; min-height: 60px; padding: 5px; box-sizing: border-box; resize: vertical;" placeholder="Сноска / Примечания к месяцу..." oninput="appState.month_hint = this.value; markUnsaved();"></textarea>
        </div>'''

new_text = pattern.sub(replacement, text)

# For users who CANNOT edit, we should still show the hint as readonly text or readonly textarea
replacement2 = r'''\1
        <div class="month-hint-wrap" style="margin-top: 10px;">
          <textarea id="monthHint" class="month-hint" style="width: 100%; min-height: 60px; padding: 5px; box-sizing: border-box; resize: vertical;" placeholder="Сноска / Примечания к месяцу..." oninput="appState.month_hint = this.value; markUnsaved();" {{ '' if CAN_EDIT else 'readonly' }}></textarea>
        </div>'''

# Oh wait, CAN_EDIT is injected by app.py via {{CAN_EDIT}} which evaluates to true/false in js context, but in html it's a raw string replacement.
# In app.py: html.replace("{{CAN_EDIT}}", "true" if can_edit else "false")
# So we can't use jinja if/else. We can just set readonly via JS, or let it be editable but the save API will reject it. Let's just set readonly via JS.

replacement_final = r'''\1
        <div class="month-hint-wrap" style="margin-top: 10px;">
          <textarea id="monthHint" class="month-hint" style="width: 100%; min-height: 60px; padding: 5px; box-sizing: border-box; resize: vertical;" placeholder="Сноска / Примечания к месяцу..." oninput="appState.month_hint = this.value; markUnsaved();"></textarea>
        </div>'''

new_text = pattern.sub(replacement_final, text)

with open(index_html, 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Updated index.html")

import re

index_html = r'g:\Мой диск\Codex\rtps\web_tabel\templates\index.html'
with open(index_html, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Add "Отчеты" menu and "Письмо: Больничный" button next to "Молоко"
milk_menu = r'''<div class="json-menu">
            <button class="dropdown-toggle" onclick="this.parentElement.classList.toggle('open')">Молоко  </button>
            <div class="json-menu-panel">
              <button onclick="exportMilk('компенсация')">Компенсация (План)</button>
              <button onclick="exportMilk('план')">Выдача (План)</button>
              <button onclick="exportMilk('факт')">Выдача (Факт)</button>
            </div>
          </div>'''

reports_menu = r'''<div class="json-menu">
            <button class="dropdown-toggle" onclick="this.parentElement.classList.toggle('open')">Молоко  </button>
            <div class="json-menu-panel">
              <button onclick="exportMilk('компенсация')">Компенсация (План)</button>
              <button onclick="exportMilk('план')">Выдача (План)</button>
              <button onclick="exportMilk('факт')">Выдача (Факт)</button>
            </div>
          </div>
          <div class="json-menu">
            <button class="dropdown-toggle" onclick="this.parentElement.classList.toggle('open')">Выгрузка  </button>
            <div class="json-menu-panel">
              <button onclick="exportSummary('Отпуска')">Отпуска</button>
              <button onclick="exportSummary('Отпуска внеплановые')">Отпуска внеплановые</button>
              <button onclick="exportSummary('Отпуск б/с')">Отпуск б/с</button>
              <button onclick="exportSummary('Учебный отпуск')">Учебный отпуск</button>
              <button onclick="exportSummary('Больничный')">Больничный</button>
            </div>
          </div>
          <button onclick="openSickModal()" style="margin-right: 5px;">Письмо: Больничный</button>'''

if 'exportSummary' not in text:
    # Need to match the actual text ignoring some spaces because of encoding
    pattern = re.compile(r'<div class="json-menu">\s*<button class="dropdown-toggle".*?>.*?Молоко.*?</div>\s*</div>', re.DOTALL)
    text = pattern.sub(reports_menu, text)

# 2. Add Modal for Sick Leave Email
modal_html = r'''
  <!-- Modal for Sick Leave Email -->
  <div id="sickModal" class="modal-overlay">
    <div class="modal-content">
      <div class="modal-header">Письмо: Больничный</div>
      <div class="modal-body" style="padding: 15px;">
        <label>1. Выберите сотрудника:</label><br>
        <select id="sickEmp" style="width: 100%; margin-bottom: 10px; padding: 5px;"></select>
        
        <label>2. Тип операции:</label><br>
        <select id="sickType" style="width: 100%; margin-bottom: 10px; padding: 5px;">
          <option value="Открытие">Открытие</option>
          <option value="Закрытие">Закрытие</option>
        </select>
        
        <label>3. Дата начала:</label><br>
        <input type="date" id="sickStart" style="width: 100%; margin-bottom: 10px; padding: 5px;">
        
        <label>4. Дата окончания:</label><br>
        <input type="date" id="sickEnd" style="width: 100%; margin-bottom: 10px; padding: 5px;">
        
        <label>5. Email получателя:</label><br>
        <input type="text" id="sickEmail" value="nn-kgmk-ps@nornik.ru" style="width: 100%; margin-bottom: 10px; padding: 5px;">
      </div>
      <div class="modal-footer" style="text-align: right; padding: 10px;">
        <button onclick="closeSickModal()">Отмена</button>
        <button onclick="generateSickEmail()" style="background-color: #c8e6c9; font-weight: bold; margin-left: 5px;">Сформировать письмо</button>
      </div>
    </div>
  </div>

  <style>
  .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
  .modal-content { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); background: #fff; width: 400px; border-radius: 4px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
  .modal-header { background: #e8e8e8; padding: 10px; font-weight: bold; border-bottom: 1px solid #ccc; }
  </style>
'''

if 'id="sickModal"' not in text:
    text = text.replace('</body>', modal_html + '\n</body>')

with open(index_html, 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated HTML with menus and modals")

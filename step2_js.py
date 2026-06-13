import re

js_file = r'g:\Мой диск\Codex\rtps\web_tabel\static\script.js'
with open(js_file, 'r', encoding='utf-8') as f:
    js_text = f.read()

funcs = r'''
function exportSummary(type) {
  const year = document.getElementById("yearInput").value;
  const month = document.getElementById("monthInput").value;
  window.open(`${APP_PREFIX}/api/export-summary?year=${year}&month=${month}&type=${encodeURIComponent(type)}`, "_blank");
}

function openSickModal() {
  const sel = document.getElementById("sickEmp");
  sel.innerHTML = "";
  appState.employees.forEach(emp => {
    if (emp && emp.name) {
      const opt = document.createElement("option");
      opt.value = emp.name;
      opt.textContent = emp.name;
      sel.appendChild(opt);
    }
  });
  const d = new Date();
  document.getElementById("sickStart").valueAsDate = d;
  document.getElementById("sickEnd").valueAsDate = d;
  document.getElementById("sickModal").style.display = "block";
}

function closeSickModal() {
  document.getElementById("sickModal").style.display = "none";
}

function generateSickEmail() {
  const emp = encodeURIComponent(document.getElementById("sickEmp").value);
  const type = encodeURIComponent(document.getElementById("sickType").value);
  const start = document.getElementById("sickStart").value;
  const end = document.getElementById("sickEnd").value;
  const email = encodeURIComponent(document.getElementById("sickEmail").value);
  
  window.open(`${APP_PREFIX}/api/export-sick-email?emp=${emp}&type=${type}&start=${start}&end=${end}&email=${email}`, "_blank");
  closeSickModal();
}
'''

if 'function exportSummary' not in js_text:
    js_text = js_text + funcs
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(js_text)
    print("Updated script.js with modal funcs")
else:
    print("Already updated script.js")

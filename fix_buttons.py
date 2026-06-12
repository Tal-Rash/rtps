import re
import os

svg = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'

for p in [r'web_grafik_ppr\templates\index.html', r'web_zamer_kp\templates\index.html']:
    if not os.path.exists(p): continue
    with open(p, 'r', encoding='utf-8') as f:
        text = f.read()
    
    text = re.sub(r'(<button[^>]*class="modal-close"[^>]*>)(?:&times;|×)(</button>)', r'\g<1>' + svg + r'\g<2>', text)
    text = re.sub(r'(<button[^>]*title="Закрыть"[^>]*>)(?:&times;|×)(</button>)', r'\g<1>' + svg + r'\g<2>', text)
    
    with open(p, 'w', encoding='utf-8') as f:
        f.write(text)

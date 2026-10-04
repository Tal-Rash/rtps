/*
 * JavaScript код для закладки браузера (Bookmarklet).
 * 
 * Описание:
 * 1. Загружает файл Excel (employees_private.xlsx) со столбцами:
 *    - Код системы (ID_001...)
 *    - Должность
 *    - ФИО
 *    - Табельный номер
 * 2. Сохраняет эти сопоставления в localStorage.
 * 3. Подменяет на открытой странице сайта:
 *    - "Работник №X" -> ФИО
 *    - "Должность №X" -> Должность
 *    - "ID_00X" -> Настоящий Табельный номер
 */

(function () {
    var STORAGE_KEY = 'rtps_employees_full_dict';

    // Функция подстановки на странице
    function applyReplacements(records) {
        var count = 0;
        var walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

        // Готовим список всех сопоставлений для быстрой замены
        var replacements = [];
        
        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            var anonId = rec.id;           // e.g. ID_001
            var realPos = rec.pos;         // e.g. Слесарь...
            var realFio = rec.fio;         // e.g. Цюрко...
            var realTab = rec.tab;         // e.g. 4004236
            var num = anonId.replace('ID_', '').replace(/^0+/, '');

            // 1. Замена имен
            replacements.push({ from: "Работник №" + num, to: realFio });
            replacements.push({ from: "Работник №0" + num, to: realFio });
            replacements.push({ from: "Работник №00" + num, to: realFio });
            
            // 2. Замена должностей
            replacements.push({ from: "Должность №" + num, to: realPos });
            replacements.push({ from: "Должность №0" + num, to: realPos });
            replacements.push({ from: "Должность №00" + num, to: realPos });

            // 3. Замена ID на Табельный номер
            replacements.push({ from: anonId, to: realTab });

            // 4. Дополнительные сопоставления по старым данным
            if (realTab && realTab !== anonId) {
                replacements.push({ from: realTab, to: realFio });
            }
        }

        var node;
        while ((node = walker.nextNode())) {
            var text = node.nodeValue;
            if (!text || !text.trim()) continue;

            var newText = text;
            for (var r = 0; r < replacements.length; r++) {
                var item = replacements[r];
                if (!item.from || !item.to) continue;
                
                if (newText.indexOf(item.from) !== -1) {
                    newText = newText.split(item.from).join(item.to);
                    count++;
                }
            }

            if (newText !== text) {
                node.nodeValue = newText;
            }
        }
        return count;
    }

    // Загрузка библиотеки SheetJS при отсутствии
    function loadXLSXLibrary(callback) {
        if (window.XLSX) {
            callback();
            return;
        }
        var script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
        script.onload = function () {
            callback();
        };
        script.onerror = function () {
            alert("Не удалось загрузить модуль чтения Excel. Проверьте сеть.");
        };
        document.head.appendChild(script);
    }

    // Выбор файла пользователем
    function promptFileLoad(currentRecords, callback) {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.xlsx,.xls,.csv,.txt';
        input.onchange = function (e) {
            var file = e.target.files[0];
            if (!file) return;

            var isExcel = file.name.endsWith('.xlsx') || file.name.endsWith('.xls');

            if (isExcel) {
                loadXLSXLibrary(function () {
                    var reader = new FileReader();
                    reader.onload = function (evt) {
                        var data = new Uint8Array(evt.target.result);
                        var workbook = XLSX.read(data, { type: 'array' });
                        var firstSheetName = workbook.SheetNames[0];
                        var worksheet = workbook.Sheets[firstSheetName];
                        var rows = XLSX.utils.sheet_to_json(worksheet, { header: 1 });
                        
                        var records = [];
                        for (var i = 0; i < rows.length; i++) {
                            var row = rows[i];
                            if (!row || row.length < 3) continue;
                            var id = String(row[0] || '').trim();
                            var pos = String(row[1] || '').trim();
                            var fio = String(row[2] || '').trim();
                            var tab = String(row[3] || row[0] || '').trim();

                            if (id && fio && id !== 'Код системы (ID)' && id !== 'Табельный номер') {
                                records.push({
                                    id: id,
                                    pos: pos,
                                    fio: fio,
                                    tab: tab
                                });
                            }
                        }

                        localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
                        alert("Загружено " + records.length + " сотрудников из Excel!");
                        callback(records);
                    };
                    reader.readAsArrayBuffer(file);
                });
            } else {
                var reader = new FileReader();
                reader.onload = function (evt) {
                    var content = evt.target.result;
                    var lines = content.split(/\r?\n/);
                    var records = [];

                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line || line.indexOf('#') === 0) continue;

                        var parts = line.split('=');
                        if (parts.length >= 2) {
                            var id = parts[0].trim();
                            var fio = parts.slice(1).join('=').trim();
                            if (id && fio && id !== 'Код системы (ID)') {
                                records.push({
                                    id: id,
                                    pos: 'Должность',
                                    fio: fio,
                                    tab: id
                                });
                            }
                        }
                    }

                    localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
                    alert("Загружено " + records.length + " сотрудников!");
                    callback(records);
                };
                reader.readAsText(file, 'UTF-8');
            }
        };
        input.click();
    }

    // Запуск
    var stored = localStorage.getItem(STORAGE_KEY);
    var records = stored ? JSON.parse(stored) : null;

    if (!records || window.event && window.event.shiftKey) {
        promptFileLoad(records, function (newRecords) {
            var replaced = applyReplacements(newRecords);
            console.log("Заменено элементов: " + replaced);
        });
    } else {
        var replaced = applyReplacements(records);
        console.log("Заменено элементов: " + replaced);
    }
})();

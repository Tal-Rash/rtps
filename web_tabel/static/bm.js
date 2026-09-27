/*
 * Вспомогательный скрипт для закладки подмены ПДн (bm.js).
 * Автоматически подключает библиотеку парсинга Excel и заменяет обезличенные записи на ФИО из Excel.
 */

(function () {
    var STORAGE_KEY = 'rtps_employees_full_dict';

    // 1. Функция замену текста на странице
    function applyReplacements(records) {
        if (!records || !records.length) {
            alert("Список сотрудников пуст! Зажмите Shift при клике на закладку, чтобы загрузить Excel файл.");
            return;
        }

        var count = 0;
        var replacements = [];
        
        for (var i = 0; i < records.length; i++) {
            var rec = records[i];
            var anonId = rec.id;
            var realPos = rec.pos;
            var realFio = rec.fio;
            var realTab = rec.tab;

            // Формируем численный номер (например, для ID_001 -> 1)
            var numStr = anonId.replace('ID_', '');
            var num = parseInt(numStr, 10);

            if (!isNaN(num)) {
                replacements.push({ from: "Работник №" + num, to: realFio });
                replacements.push({ from: "Должность №" + num, to: realPos });
            }

            // Дополнения по полным ID
            replacements.push({ from: anonId, to: realTab });
            if (realTab && realTab !== anonId) {
                replacements.push({ from: realTab, to: realFio });
            }
        }

        var walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            null,
            false
        );

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

        alert("Готово! На странице обновлено элементов: " + count);
    }

    // 2. Подключение библиотеки SheetJS для Excel
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
            alert("Не удалось загрузить модуль чтения Excel с внешнего сервера. Проверьте интернет на рабочем ПК.");
        };
        document.head.appendChild(script);
    }

    // 3. Выбор файла Excel
    function promptFileLoad(callback) {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.xlsx,.xls,.csv,.txt';
        input.onchange = function (e) {
            var file = e.target.files[0];
            if (!file) return;

            loadXLSXLibrary(function () {
                var reader = new FileReader();
                reader.onload = function (evt) {
                    try {
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

                            if (id && fio && id.indexOf('ID') !== -1) {
                                records.push({
                                    id: id,
                                    pos: pos,
                                    fio: fio,
                                    tab: tab
                                });
                            }
                        }

                        localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
                        alert("Загружено сотрудников из Excel: " + records.length);
                        callback(records);
                    } catch (err) {
                        alert("Ошибка обработки файла Excel: " + err.message);
                    }
                };
                reader.readAsArrayBuffer(file);
            });
        };
        input.click();
    }

    // 4. Запуск
    var stored = localStorage.getItem(STORAGE_KEY);
    var records = stored ? JSON.parse(stored) : null;

    if (!records) {
        alert("Выберите ваш файл employees_private.xlsx...");
        promptFileLoad(function (newRecords) {
            applyReplacements(newRecords);
        });
    } else {
        applyReplacements(records);
    }
})();

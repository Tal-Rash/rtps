/*
 * JavaScript код для закладки браузера (Bookmarklet) с поддержкой файлов Excel (.xlsx, .xls) и Текстовых файлов (.txt, .csv).
 * 
 * Описание:
 * 1. Загружает лёгкий парсер SheetJS при выборе файла Excel.
 * 2. Сохраняет словарь (Табельный номер -> ФИО) в localStorage браузера.
 * 3. Заменяет на открытой странице сайта записи "Сотрудник №XXXXX" и табельные номера XXXXX на реальные ФИО.
 */

(function () {
    var STORAGE_KEY = 'rtps_employees_dict';

    // Функция подстановки ФИО в открытый HTML документ
    function applyReplacements(map) {
        var count = 0;
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
            for (var tab in map) {
                if (map.hasOwnProperty(tab)) {
                    var fio = map[tab];
                    var target1 = "Сотрудник №" + tab;
                    var target2 = "Сотрудник " + tab;
                    
                    if (newText.indexOf(target1) !== -1) {
                        newText = newText.split(target1).join(fio);
                        count++;
                    } else if (newText.indexOf(target2) !== -1) {
                        newText = newText.split(target2).join(fio);
                        count++;
                    } else if (newText === tab) {
                        newText = fio;
                        count++;
                    }
                }
            }

            if (newText !== text) {
                node.nodeValue = newText;
            }
        }
        return count;
    }

    // Подключение парсера SheetJS XLSX при необходимости
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
            alert("Не удалось загрузить библиотеку обработки Excel. Проверьте подключение к сети.");
        };
        document.head.appendChild(script);
    }

    // Запрос выбора файла Excel или TXT
    function promptFileLoad(currentMap, callback) {
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
                        
                        var map = {};
                        var loaded = 0;
                        for (var i = 0; i < rows.length; i++) {
                            var row = rows[i];
                            if (!row || row.length < 2) continue;
                            var tab = String(row[0]).trim();
                            var fio = String(row[1]).trim();
                            if (tab && fio && tab !== 'Табельный номер' && tab !== 'ID') {
                                map[tab] = fio;
                                loaded++;
                            }
                        }

                        localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
                        alert("Успешно загружено " + loaded + " сотрудников из Excel!");
                        callback(map);
                    };
                    reader.readAsArrayBuffer(file);
                });
            } else {
                var reader = new FileReader();
                reader.onload = function (evt) {
                    var content = evt.target.result;
                    var lines = content.split(/\r?\n/);
                    var map = {};
                    var loaded = 0;

                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line || line.indexOf('#') === 0) continue;

                        var parts = line.indexOf('=') !== -1 ? line.split('=') : line.split(';');
                        if (parts.length >= 2) {
                            var tab = parts[0].trim();
                            var fio = parts.slice(1).join('=').trim();
                            if (tab && fio && tab !== 'Табельный номер') {
                                map[tab] = fio;
                                loaded++;
                            }
                        }
                    }

                    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
                    alert("Успешно загружено " + loaded + " сотрудников!");
                    callback(map);
                };
                reader.readAsText(file, 'UTF-8');
            }
        };
        input.click();
    }

    // Основной запуск
    var stored = localStorage.getItem(STORAGE_KEY);
    var map = stored ? JSON.parse(stored) : null;

    if (!map || window.event && window.event.shiftKey) {
        promptFileLoad(map, function (newMap) {
            var replaced = applyReplacements(newMap);
            console.log("Заменено элементов: " + replaced);
        });
    } else {
        var replaced = applyReplacements(map);
        console.log("Заменено элементов: " + replaced);
    }
})();

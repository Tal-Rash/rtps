/*
 * JavaScript код для закладки браузера (Bookmarklet).
 * 
 * Описание:
 * 1. Сохраняет словарь (Табельный номер -> ФИО) в localStorage браузера при выборе файла.
 * 2. Заменяет на открытой странице сайта записи "Сотрудник №XXXXX" и табельные номера XXXXX на реальные ФИО.
 * 3. Если зажать Shift при нажатии или если список пуст — запрашивает выбор нового файла employees_private.txt.
 */

(function () {
    // Ключ для хранения в localStorage
    var STORAGE_KEY = 'rtps_employees_dict';

    // Функция замены текста на странице
    function applyReplacements(map) {
        var count = 0;
        // Все текстовые узлы в документе
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
                    // Варианты поиска
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

    // Функция запроса выбора файла
    function promptFileLoad(currentMap, callback) {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.txt,.csv';
        input.onchange = function (e) {
            var file = e.target.files[0];
            if (!file) return;

            var reader = new FileReader();
            reader.onload = function (evt) {
                var content = evt.target.result;
                var lines = content.split(/\r?\n/);
                var map = {};
                var loaded = 0;

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.indexOf('#') === 0) continue;

                    var parts = line.split('=');
                    if (parts.length >= 2) {
                        var tab = parts[0].trim();
                        var fio = parts.slice(1).join('=').trim();
                        if (tab && fio) {
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
        };
        input.click();
    }

    // Основная логика
    var stored = localStorage.getItem(STORAGE_KEY);
    var map = stored ? JSON.parse(stored) : null;

    // Если список не загружен или нажата клавиша Shift
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

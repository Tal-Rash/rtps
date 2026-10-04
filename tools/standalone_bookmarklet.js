/*
 * Автономный JavaScript код для закладки браузера.
 * 
 * Точное сопоставление по столбцам:
 * - "Работник №X" -> ФИО сокращённое (Цюрко Г. В.)
 * - "СотрудникПолн №X" / "Сотрудник №X" -> ФИО полное (Цюрко Геннадий Васильевич)
 * - "Должность №X" -> Должность
 * - "ID_00X" -> Табельный номер (4004236)
 */

(function () {
    var KEY = 'rtps_emp_dict';

    function replaceText(map, silent) {
        if (!map) return;
        var count = 0;

        var pairs = [];
        for (var k in map) {
            if (map.hasOwnProperty(k) && k && map[k]) {
                pairs.push({ from: k, to: map[k] });
            }
        }

        pairs.sort(function (a, b) {
            return b.from.length - a.from.length;
        });

        // 1. Текстовые узлы
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        var node;

        while ((node = walker.nextNode())) {
            var val = node.nodeValue;
            if (!val || !val.trim()) continue;

            var newVal = val;
            for (var p = 0; p < pairs.length; p++) {
                var item = pairs[p];
                if (newVal.indexOf(item.from) !== -1) {
                    newVal = newVal.split(item.from).join(item.to);
                    count++;
                }
            }

            if (newVal !== val) {
                node.nodeValue = newVal;
            }
        }

        // 2. Инпуты и списки
        var inputs = document.querySelectorAll('input, select, option, textarea');
        for (var i = 0; i < inputs.length; i++) {
            var el = inputs[i];
            if (el.value) {
                var val = el.value, newVal = val;
                for (var p = 0; p < pairs.length; p++) {
                    var item = pairs[p];
                    if (newVal.indexOf(item.from) !== -1) {
                        newVal = newVal.split(item.from).join(item.to);
                        count++;
                    }
                }
                if (newVal !== val) el.value = newVal;
            }
        }

        if (!silent && count > 0) {
            alert("Подстановка успешно выполнена! Изменено элементов: " + count);
        }
    }

    function loadFile(callback) {
        var inp = document.createElement('input');
        inp.type = 'file';
        inp.accept = '.csv,.txt,.xlsx';
        inp.onchange = function (e) {
            var f = e.target.files[0];
            if (!f) return;

            var reader = new FileReader();
            reader.onload = function (evt) {
                var txt = evt.target.result;
                var lines = txt.split(/\r?\n/);
                var map = {};
                var loaded = 0;

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.indexOf('#') === 0) continue;

                    var parts = line.split(';');
                    if (parts.length < 2) parts = line.split(',');

                    if (parts.length >= 2) {
                        var id = parts[0] ? parts[0].trim() : '';
                        var pos = parts[1] ? parts[1].trim() : '';
                        var fullFio = parts[2] ? parts[2].trim() : parts[1].trim();
                        var shortFio = parts[3] ? parts[3].trim() : fullFio;
                        var tab = parts[4] ? parts[4].trim() : (parts[3] || id);

                        if (id && fullFio && id.indexOf('Код') === -1 && id.indexOf('Табельный') === -1) {
                            var numStr = id.replace('ID_', '');
                            var num = parseInt(numStr, 10);

                            if (!isNaN(num)) {
                                // "Работник №X" (столбец ФИО) -> Цюрко Г. В.
                                map["Работник №" + num] = shortFio || fullFio;

                                // "СотрудникПолн №X" и "Сотрудник №X" (столбец ФИО полное) -> Цюрко Геннадий Васильевич
                                map["СотрудникПолн №" + num] = fullFio;
                                map["Сотрудник №" + num] = fullFio;

                                // "Должность №X" -> Слесарь по ремонту...
                                if (pos) map["Должность №" + num] = pos;

                                // "ID_00X" -> 4004236 (Табельный номер)
                                map[id] = tab || id;
                            }
                            loaded++;
                        }
                    }
                }

                localStorage.removeItem('rtps_employees_full_dict');
                localStorage.setItem(KEY, JSON.stringify(map));

                alert("Новый файл загружен! Записей сотрудников: " + loaded);
                callback(map);
            };
            reader.readAsText(f, 'UTF-8');
        };
        inp.click();
    }

    loadFile(function (newMap) {
        replaceText(newMap, false);
    });
})();

/*
 * Автономный JavaScript код для закладки браузера.
 * 
 * Точное сопоставление по столбцам:
 * - "Работник №X" -> ФИО сокращённое (Иванов И. И.)
 * - "СотрудникПолн №X" / "Сотрудник №X" -> ФИО полное (Иванов Иван Иванович)
 * - "Должность №X" -> Должность
 * - "ID_00X" -> Табельный номер (1234567)
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
                        var fullFio = '';
                        var shortFio = '';
                        var tab = '';

                        // Корректное определение колонок в зависимости от формата (4 или 5 колонок)
                        if (parts.length === 4) {
                            // Формат: ID; Должность; ФИО; Табельный
                            fullFio = parts[2] ? parts[2].trim() : '';
                            shortFio = fullFio;
                            tab = parts[3] ? parts[3].trim() : id;
                        } else if (parts.length >= 5) {
                            // Формат: ID; Должность; ФИО полное; ФИО краткое; Табельный
                            fullFio = parts[2] ? parts[2].trim() : '';
                            var col3 = parts[3] ? parts[3].trim() : '';
                            var col4 = parts[4] ? parts[4].trim() : '';
                            if (col3 && /^\d+$/.test(col3) && !col4) {
                                shortFio = fullFio;
                                tab = col3;
                            } else {
                                shortFio = col3 || fullFio;
                                tab = col4 || col3 || id;
                            }
                        } else {
                            fullFio = parts[2] ? parts[2].trim() : (parts[1] ? parts[1].trim() : '');
                            shortFio = fullFio;
                            tab = parts[3] ? parts[3].trim() : id;
                        }

                        // Защита: ФИО никогда не должно быть числовым табельным номером
                        if (shortFio && /^\d+$/.test(shortFio.trim())) {
                            shortFio = (fullFio && !/^\d+$/.test(fullFio.trim())) ? fullFio : '';
                        }
                        if (fullFio && /^\d+$/.test(fullFio.trim())) {
                            fullFio = (shortFio && !/^\d+$/.test(shortFio.trim())) ? shortFio : '';
                        }

                        if (id && fullFio && id.indexOf('Код') === -1 && id.indexOf('Табельный') === -1) {
                            var numStr = id.replace('ID_', '');
                            var num = parseInt(numStr, 10);

                            if (!isNaN(num)) {
                                // "Работник №X" (столбец ФИО) -> Иванов И. И.
                                map["Работник №" + num] = shortFio || fullFio;

                                // "СотрудникПолн №X" и "Сотрудник №X" (столбец ФИО полное) -> Иванов Иван Иванович
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

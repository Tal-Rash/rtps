/*
 * Автономный скрипт подстановки ФИО с гарантированной очисткой старых дублей.
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
            alert("Данные успешно обновлены! Подставлено элементов: " + count);
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

                    var parts = line.split(/[,;\t=]/);
                    if (parts.length >= 2) {
                        var id = parts[0].trim();
                        var pos = parts.length >= 3 ? parts[1].trim() : '';
                        var fio = parts.length >= 3 ? parts[2].trim() : parts[1].trim();
                        var tab = parts.length >= 4 ? parts[3].trim() : id;

                        if (id && fio && id !== 'Код системы (ID)' && id !== 'Табельный номер') {
                            var numStr = id.replace('ID_', '');
                            var num = parseInt(numStr, 10);

                            if (!isNaN(num)) {
                                map["Работник №" + num] = fio;
                                if (pos) map["Должность №" + num] = pos;
                            }
                            if (tab && tab !== id) {
                                map[id] = tab;
                            }
                            loaded++;
                        }
                    }
                }

                // Очистка старых версий хранилища
                localStorage.removeItem('rtps_employees_full_dict');
                localStorage.setItem(KEY, JSON.stringify(map));

                alert("Загружен новый файл! Записей: " + loaded);
                callback(map);
            };
            reader.readAsText(f, 'UTF-8');
        };
        inp.click();
    }

    // Принудительный запуск выбора нового файла при каждом вызове для 100% точности
    loadFile(function (newMap) {
        replaceText(newMap, false);
    });
})();

/*
 * Автономный JavaScript код для закладки браузера.
 * 
 * Логика замены:
 * - Сортировка ключей по убыванию длины для предотвращения коллизий (например "Работник №10" не перехватывается как "Работник №1" + "0").
 * - Интерактивный диалог: "Применить сохраненный список?" или выбор нового файла.
 */

(function () {
    var KEY = 'rtps_emp_dict';

    function replaceText(map) {
        if (!map) return;
        var count = 0;

        // Создаем массив пар {from, to} и сортируем по УБЫВАНИЮ ДЛИНЫ ключа
        var pairs = [];
        for (var k in map) {
            if (map.hasOwnProperty(k) && k && map[k]) {
                pairs.push({ from: k, to: map[k] });
            }
        }

        // Сортировка по длине от самых длинных к коротким
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
        alert("Готово! На странице успешно обновлено элементов: " + count);
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
                        var fio = parts[parts.length >= 3 ? 2 : 1].trim();
                        var pos = parts.length >= 3 ? parts[1].trim() : '';
                        var tab = parts.length >= 4 ? parts[3].trim() : id;

                        if (id && fio && id !== 'Код системы (ID)' && id !== 'Табельный номер') {
                            var numStr = id.replace('ID_', '');
                            var num = parseInt(numStr, 10);

                            if (!isNaN(num)) {
                                map["Работник №" + num] = fio;
                                if (pos) map["Должность №" + num] = pos;
                            }
                            map[id] = tab || fio;
                            if (tab && tab !== id) map[tab] = fio;
                            loaded++;
                        }
                    }
                }

                localStorage.setItem(KEY, JSON.stringify(map));
                alert("Успешно загружено сотрудников из файла: " + loaded);
                callback(map);
            };
            reader.readAsText(f, 'UTF-8');
        };
        inp.click();
    }

    var saved = localStorage.getItem(KEY);
    var map = saved ? JSON.parse(saved) : null;

    if (!map) {
        loadFile(function (newMap) {
            replaceText(newMap);
        });
    } else {
        var useSaved = confirm("Применить сохранённый список сотрудников?\n\n[OK] — Заменить ФИО на странице\n[Отмена] — Выбрать НОВЫЙ файл с компьютера");
        if (useSaved) {
            replaceText(map);
        } else {
            loadFile(function (newMap) {
                replaceText(newMap);
            });
        }
    }
})();

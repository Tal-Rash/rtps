/*
 * Автономный JavaScript код для закладки браузера.
 * 
 * Логика работы:
 * 1. Если список сохранён, спрашивает через confirm: "Применить сохраненный список? (Отмена — для выбора нового файла)".
 * 2. При выборе "Отмена" или если список пуст — открывает окно выбора файла Excel/CSV.
 */

(function () {
    var KEY = 'rtps_emp_dict';

    // Функция замены элементов на странице
    function replaceText(map) {
        if (!map) return;
        var count = 0;
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        var node;

        while ((node = walker.nextNode())) {
            var val = node.nodeValue;
            if (!val || !val.trim()) continue;

            var newVal = val;
            for (var k in map) {
                if (map.hasOwnProperty(k) && map[k]) {
                    if (newVal.indexOf(k) !== -1) {
                        newVal = newVal.split(k).join(map[k]);
                        count++;
                    }
                }
            }
            if (newVal !== val) {
                node.nodeValue = newVal;
            }
        }
        alert("Готово! На странице обновлено элементов: " + count);
    }

    // Функция выбора файла CSV / TXT / Excel
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
                alert("Успешно загружено сотрудников: " + loaded);
                callback(map);
            };
            reader.readAsText(f, 'UTF-8');
        };
        inp.click();
    }

    var saved = localStorage.getItem(KEY);
    var map = saved ? JSON.parse(saved) : null;

    if (!map) {
        // Если база еще не загружалась
        loadFile(function (newMap) {
            replaceText(newMap);
        });
    } else {
        // Если база уже загружена, спрашиваем пользователю выбор
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

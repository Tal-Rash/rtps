/*
 * Автономный JavaScript код для закладки браузера с глубокой заменой (включая input.value и title).
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

        // 1. Замена во всех обычных текстовых узлах
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

        // 2. Замена внутри атрибутов value и title элементов ввода (input, select, option)
        var inputs = document.querySelectorAll('input, select, option, textarea');
        for (var i = 0; i < inputs.length; i++) {
            var el = inputs[i];
            
            // Проверка value
            if (el.value) {
                var val = el.value;
                var newVal = val;
                for (var p = 0; p < pairs.length; p++) {
                    var item = pairs[p];
                    if (newVal.indexOf(item.from) !== -1) {
                        newVal = newVal.split(item.from).join(item.to);
                        count++;
                    }
                }
                if (newVal !== val) {
                    el.value = newVal;
                }
            }

            // Проверка title
            if (el.title) {
                var val = el.title;
                var newVal = val;
                for (var p = 0; p < pairs.length; p++) {
                    var item = pairs[p];
                    if (newVal.indexOf(item.from) !== -1) {
                        newVal = newVal.split(item.from).join(item.to);
                        count++;
                    }
                }
                if (newVal !== val) {
                    el.title = newVal;
                }
            }
        }

        if (!silent && count > 0) {
            alert("Подстановка ФИО и Должностей успешно выполнена! Элементов: " + count);
        }
    }

    function startAutoObserver(map) {
        replaceText(map, false);

        if (window.__rtps_observer) {
            window.__rtps_observer.disconnect();
        }

        var timer = null;
        window.__rtps_observer = new MutationObserver(function () {
            if (timer) clearTimeout(timer);
            timer = setTimeout(function () {
                replaceText(map, true);
            }, 100);
        });

        window.__rtps_observer.observe(document.body, { childList: true, subtree: true });
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
            startAutoObserver(newMap);
        });
    } else {
        var useSaved = confirm("Включить отображение ФИО и Должностей на этой странице?\n\n[OK] — Применить сохраненные ФИО\n[Отмена] — Выбрать НОВЫЙ файл с компьютера");
        if (useSaved) {
            startAutoObserver(map);
        } else {
            loadFile(function (newMap) {
                startAutoObserver(newMap);
            });
        }
    }
})();

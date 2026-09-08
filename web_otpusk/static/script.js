document.addEventListener('DOMContentLoaded', () => {
    const APP_PREFIX = window.location.pathname.startsWith('/otpusk') ? '/otpusk' : '';
    const months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
    const calendarDaysInMonths = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    
    let holidaysData = [];
    let daysInMonths = [...calendarDaysInMonths];

    const headerMonths = document.getElementById('headerMonths');
    const headerSub = document.getElementById('headerSub');
    const tableBody = document.getElementById('tableBody');
    const saveBtn = document.getElementById('saveBtn');
    const toggleBadges = document.getElementById('toggleBadges');

    // Modal elements
    const holidaysBtn = document.getElementById('holidaysBtn');
    const holidaysModal = document.getElementById('holidaysModal');
    const closeHolidaysModal = document.getElementById('closeHolidaysModal');
    const cancelHolidaysBtn = document.getElementById('cancelHolidaysBtn');
    const saveHolidaysBtn = document.getElementById('saveHolidaysBtn');
    const holidaysTableBody = document.getElementById('holidaysTableBody');

    if (toggleBadges) {
        toggleBadges.addEventListener('change', (e) => {
            if (e.target.checked) {
                document.body.classList.add('hide-badges');
            } else {
                document.body.classList.remove('hide-badges');
            }
        });
    }

    let allData = [];

    function escapeHtml(val) {
        return String(val ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // Helper: Parse date string into Set of holiday day numbers
    function parseHolidayDates(datesStr, maxDays) {
        if (!datesStr) return new Set();
        const holidaysSet = new Set();
        const parts = String(datesStr).split(/[,;\s]+/);
        parts.forEach(part => {
            part = part.trim();
            if (part.includes('-')) {
                const range = part.split('-');
                const s = parseInt(range[0]);
                const e = parseInt(range[1]);
                if (!isNaN(s) && !isNaN(e) && s <= e) {
                    for (let d = s; d <= e; d++) {
                        if (d >= 1 && d <= maxDays) holidaysSet.add(d);
                    }
                }
            } else {
                const d = parseInt(part);
                if (!isNaN(d) && d >= 1 && d <= maxDays) {
                    holidaysSet.add(d);
                }
            }
        });
        return holidaysSet;
    }

    // Helper: Count actual vacation days excluding specific holiday dates
    function getWorkingVacationDays(startM, startD, endM, endD) {
        let count = 0;
        for (let m = startM; m <= endM; m++) {
            let s = (m === startM) ? startD : 1;
            let e = (m === endM) ? endD : calendarDaysInMonths[m];
            let datesStr = (holidaysData[m] && holidaysData[m].dates) ? holidaysData[m].dates : '';
            let hSet = parseHolidayDates(datesStr, calendarDaysInMonths[m]);

            for (let d = s; d <= e; d++) {
                if (!hSet.has(d)) {
                    count++;
                }
            }
        }
        return count;
    }

    function renderHeaders() {
        // Clear old month headers (keep first 2: Сотрудник and Отпуск)
        headerMonths.querySelectorAll('th:nth-child(n+3)').forEach(el => el.remove());
        headerSub.innerHTML = '';

        months.forEach((m, i) => {
            const th = document.createElement('th');
            th.innerHTML = `${m}<br><span style="font-weight:400; font-size:0.75rem;">${daysInMonths[i]}</span>`;
            headerMonths.appendChild(th);

            const thSub = document.createElement('th');
            thSub.innerHTML = `<div style="display:flex; width: 100%;"><div style="flex:1;">с</div><div style="flex:1;">по</div></div>`;
            headerSub.appendChild(thSub);
        });
    }

    function updateDaysInMonths() {
        daysInMonths = months.map((m, i) => {
            const totalD = calendarDaysInMonths[i];
            const datesStr = (holidaysData[i] && holidaysData[i].dates) ? holidaysData[i].dates : '';
            const hSet = parseHolidayDates(datesStr, totalD);
            return totalD - hSet.size;
        });
    }

    // Load Data (holidays & vacations)
    Promise.all([
        fetch(`${APP_PREFIX}/api/holidays`).then(res => res.json()),
        fetch(`${APP_PREFIX}/api/vacations`).then(res => res.json())
    ]).then(([holidays, vacations]) => {
        holidaysData = holidays;
        updateDaysInMonths();
        renderHeaders();
        allData = vacations;
        renderTable(allData);
    }).catch(err => console.error(err));

    // Modal Handlers
    function openHolidaysModal() {
        if (!holidaysTableBody) return;
        holidaysTableBody.innerHTML = '';
        holidaysData.forEach((item, index) => {
            const tr = document.createElement('tr');
            const totalD = calendarDaysInMonths[index];
            const datesStr = item.dates || '';
            const hSet = parseHolidayDates(datesStr, totalD);
            const hCount = hSet.size;
            const vacationDays = totalD - hCount;

            tr.innerHTML = `
                <td><strong>${item.name}</strong></td>
                <td>${totalD} дн.</td>
                <td>
                    <input type="text" class="holiday-input" data-index="${index}" placeholder="1, 9 или 1-8" value="${datesStr}">
                </td>
                <td class="holiday-count-cell" data-index="${index}">${hCount} дн.</td>
                <td class="vacation-days-cell" data-index="${index}" style="font-weight:600; color: var(--accent-color);">${vacationDays} дн.</td>
            `;
            holidaysTableBody.appendChild(tr);
        });

        holidaysTableBody.querySelectorAll('.holiday-input').forEach(input => {
            input.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.index);
                const dStr = e.target.value;
                const totalD = calendarDaysInMonths[idx];
                const hSet = parseHolidayDates(dStr, totalD);
                const hCount = hSet.size;
                const calculated = Math.max(0, totalD - hCount);

                const hCell = holidaysTableBody.querySelector(`.holiday-count-cell[data-index="${idx}"]`);
                if (hCell) hCell.textContent = `${hCount} дн.`;

                const vCell = holidaysTableBody.querySelector(`.vacation-days-cell[data-index="${idx}"]`);
                if (vCell) vCell.textContent = `${calculated} дн.`;
            });
        });

        holidaysModal.classList.add('active');
    }

    function closeHolidaysModalFn() {
        if (holidaysModal) holidaysModal.classList.remove('active');
    }

    if (holidaysBtn) holidaysBtn.addEventListener('click', openHolidaysModal);
    if (closeHolidaysModal) closeHolidaysModal.addEventListener('click', closeHolidaysModalFn);
    if (cancelHolidaysBtn) cancelHolidaysBtn.addEventListener('click', closeHolidaysModalFn);

    if (saveHolidaysBtn) {
        saveHolidaysBtn.addEventListener('click', () => {
            const inputs = holidaysTableBody.querySelectorAll('.holiday-input');
            inputs.forEach(input => {
                const idx = parseInt(input.dataset.index);
                holidaysData[idx].dates = input.value.trim();
            });

            saveHolidaysBtn.textContent = 'Сохранение...';

            fetch(`${APP_PREFIX}/api/holidays`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(holidaysData)
            })
            .then(res => res.json())
            .then(() => {
                saveHolidaysBtn.textContent = 'Сохранить праздники';
                closeHolidaysModalFn();
                updateDaysInMonths();
                renderHeaders();
                document.querySelectorAll('#tableBody tr').forEach(tr => calculateRow(tr));
            })
            .catch(err => {
                saveHolidaysBtn.textContent = 'Ошибка';
                console.error(err);
            });
        });
    }

    function renderTable(data) {
        if (!tableBody) return;
        tableBody.innerHTML = '';
        if (!Array.isArray(data)) return;

        data.forEach((employee, empIndex) => {
            const tr = document.createElement('tr');
            tr.dataset.empId = employee.id;

            const empName = escapeHtml(employee.name || employee.full_name || '');
            const empPos = escapeHtml(employee.position || '');
            const allowedVal = employee.vacation_days ?? employee.allowedDays ?? 28;

            // Employee info
            const tdInfo = document.createElement('td');
            tdInfo.className = 'col-sticky-1';
            tdInfo.style.width = '250px';
            tdInfo.style.minWidth = '250px';
            tdInfo.style.maxWidth = '250px';
            tdInfo.innerHTML = `
                <div class="employee-name">${empName}</div>
                <div class="employee-pos">${empPos}</div>
            `;
            tr.appendChild(tdInfo);

            const tdAllowed = document.createElement('td');
            tdAllowed.className = 'col-sticky-2';
            tdAllowed.style.width = '100px';
            tdAllowed.style.minWidth = '100px';
            tdAllowed.style.maxWidth = '100px';
            tdAllowed.innerHTML = `
                <div class="cell-input-wrapper" style="justify-content: center; height: 100%; display: flex; align-items: center;">
                    <input type="text" class="day-input allowed-days-input" value="${allowedVal}" placeholder="28" style="width: 80%; height: 40px; font-weight: bold; background: rgba(0,0,0,0.05); border-radius: 6px; color: var(--text-primary);" readonly title="Количество дней положенного отпуска (задается в Справочнике)">
                </div>
            `;
            tr.appendChild(tdAllowed);

            // Month cells
            for (let m = 0; m < 12; m++) {
                const td = document.createElement('td');
                td.className = 'month-cell';
                td.dataset.month = m;
                td.innerHTML = `
                    <div class="cell-input-wrapper">
                        <div class="inputs-row">
                            <input type="text" class="day-input c-input" data-month="${m}">
                            <input type="text" class="day-input po-input" data-month="${m}">
                        </div>
                        <div class="day-result"></div>
                    </div>
                `;
                tr.appendChild(td);
            }

            tableBody.appendChild(tr);

            // Populate existing vacations
            (employee.vacations || []).forEach(vac => {
                if (!vac || !vac.start || !vac.end) return;
                const start = new Date(vac.start);
                const end = new Date(vac.end);
                if (isNaN(start.getTime()) || isNaN(end.getTime())) return;
                
                const startM = start.getMonth();
                const startD = start.getDate();
                const endM = end.getMonth();
                const endD = end.getDate();

                const cInput = tr.querySelector(`.c-input[data-month="${startM}"]`);
                if (cInput) cInput.value = startD;

                const poInput = tr.querySelector(`.po-input[data-month="${endM}"]`);
                if (poInput) poInput.value = endD;
            });

            // Calculate and draw row
            calculateRow(tr);

            // Attach listeners to all inputs in this row
            const inputs = tr.querySelectorAll('.day-input');
            inputs.forEach(input => {
                input.addEventListener('input', () => calculateRow(tr));
            });
        });
    }

    function calculateRow(tr) {
        // Clear all previous results, lines, and badges
        tr.querySelectorAll('.day-result').forEach(el => el.textContent = '');
        tr.querySelectorAll('.vacation-line').forEach(el => el.remove());
        tr.querySelectorAll('.total-days-badge').forEach(el => el.remove());

        let currentStart = null;
        let currentStartMonth = null;
        let vacations = [];

        for (let m = 0; m < 12; m++) {
            const cValStr = tr.querySelector(`.c-input[data-month="${m}"]`).value.trim();
            const poValStr = tr.querySelector(`.po-input[data-month="${m}"]`).value.trim();
            
            const c_val = parseInt(cValStr);
            const po_val = parseInt(poValStr);

            if (!isNaN(c_val) && !isNaN(po_val)) {
                if (currentStart !== null) {
                    vacations.push({ 
                        startMonth: currentStartMonth, 
                        startDay: currentStart, 
                        endMonth: currentStartMonth, 
                        endDay: calendarDaysInMonths[currentStartMonth] 
                    });
                }
                vacations.push({ startMonth: m, startDay: c_val, endMonth: m, endDay: po_val });
                currentStart = null;
                currentStartMonth = null;
            } else if (!isNaN(c_val)) {
                if (currentStart !== null) {
                    vacations.push({ 
                        startMonth: currentStartMonth, 
                        startDay: currentStart, 
                        endMonth: currentStartMonth, 
                        endDay: calendarDaysInMonths[currentStartMonth] 
                    });
                }
                currentStart = c_val;
                currentStartMonth = m;
            } else if (!isNaN(po_val)) {
                if (currentStart !== null) {
                    vacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: m, endDay: po_val });
                    currentStart = null;
                    currentStartMonth = null;
                }
            }
        }

        // Если ввели только начало, сразу считаем до конца этого месяца
        if (currentStart !== null) {
            vacations.push({ 
                startMonth: currentStartMonth, 
                startDay: currentStart, 
                endMonth: currentStartMonth, 
                endDay: calendarDaysInMonths[currentStartMonth] 
            });
        }

        let allowedStr = tr.querySelector('.allowed-days-input').value;
        let allowedDays = allowedStr ? parseInt(allowedStr) : Infinity;

        // Calculate grand total excluding holidays
        let grandTotalDays = 0;
        vacations.forEach(vac => {
            grandTotalDays += getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);
        });

        let overflow = grandTotalDays > allowedDays ? grandTotalDays - allowedDays : 0;
        let isMatch = (grandTotalDays === allowedDays && allowedDays > 0 && allowedDays !== Infinity);

        let allowedInput = tr.querySelector('.allowed-days-input');
        if (allowedInput) {
            if (overflow > 0) {
                allowedInput.style.color = '#ef4444';
                allowedInput.style.textShadow = '0 0 8px rgba(239,68,68,0.5)';
            } else if (isMatch) {
                allowedInput.style.color = '#10b981';
                allowedInput.style.textShadow = '0 0 8px rgba(16,185,129,0.5)';
            } else {
                allowedInput.style.color = '';
                allowedInput.style.textShadow = '';
            }
        }

        // Draw results
        vacations.forEach((vac, index) => {
            let totalDays = getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);

            // Draw line segments
            for (let m = vac.startMonth; m <= vac.endMonth; m++) {
                let daysInM = calendarDaysInMonths[m];
                let cellWrapper = tr.querySelector(`.month-cell[data-month="${m}"] .cell-input-wrapper`);

                if (vac.startMonth === vac.endMonth) {
                    let left = ((vac.startDay - 1) / daysInM) * 100;
                    let width = ((vac.endDay - vac.startDay + 1) / daysInM) * 100;
                    drawLine(cellWrapper, left, width);
                } else if (m === vac.startMonth) {
                    let left = ((vac.startDay - 1) / daysInM) * 100;
                    let width = 100 - left;
                    drawLine(cellWrapper, left, width);
                } else if (m === vac.endMonth) {
                    let width = (vac.endDay / daysInM) * 100;
                    drawLine(cellWrapper, 0, width);
                } else {
                    drawLine(cellWrapper, 0, 100);
                }
            }

            // Calculate center point across the cells
            let startPoint = vac.startMonth + (vac.startDay - 1) / calendarDaysInMonths[vac.startMonth];
            let endPoint = vac.endMonth + vac.endDay / calendarDaysInMonths[vac.endMonth];
            let centerPoint = (startPoint + endPoint) / 2;
            
            let centerM = Math.floor(centerPoint);
            let centerLeft = (centerPoint - centerM) * 100;

            let badgeText = totalDays;
            let overflowClass = '';
            if (overflow > 0) {
                overflowClass = 'badge-overflow';
                if (index === vacations.length - 1) {
                    badgeText = `${totalDays} (перебор +${overflow})`;
                }
            } else if (isMatch) {
                overflowClass = 'badge-success';
            }

            let centerCell = tr.querySelector(`.month-cell[data-month="${centerM}"] .cell-input-wrapper`);
            if (centerCell) {
                centerCell.insertAdjacentHTML('beforeend', `<div class="total-days-badge ${overflowClass}" style="left: ${centerLeft}%;">${badgeText}</div>`);
            }
        });
    }

    function drawLine(wrapper, leftPct, widthPct) {
        wrapper.insertAdjacentHTML('beforeend', `<div class="vacation-line" style="left: ${leftPct}%; width: ${widthPct}%;"></div>`);
    }

    // Save functionality
    saveBtn.addEventListener('click', () => {
        saveBtn.textContent = 'Сохранение...';
        
        const rows = document.querySelectorAll('#tableBody tr');
        rows.forEach(tr => {
            const empId = parseInt(tr.dataset.empId);
            const employee = allData.find(e => e.id === empId);
            
            if (employee) {
                // Save allowed days
                const allowedInput = tr.querySelector('.allowed-days-input');
                if (allowedInput) {
                    employee.allowedDays = parseInt(allowedInput.value) || 0;
                }

                // Re-parse vacations from row inputs
                let currentStart = null;
                let currentStartMonth = null;
                let parsedVacations = [];

                for (let m = 0; m < 12; m++) {
                    const c_val = parseInt(tr.querySelector(`.c-input[data-month="${m}"]`).value);
                    const po_val = parseInt(tr.querySelector(`.po-input[data-month="${m}"]`).value);

                    if (!isNaN(c_val) && !isNaN(po_val)) {
                        if (currentStart !== null) {
                            parsedVacations.push({ 
                                startMonth: currentStartMonth, 
                                startDay: currentStart, 
                                endMonth: currentStartMonth, 
                                endDay: calendarDaysInMonths[currentStartMonth] 
                            });
                        }
                        parsedVacations.push({ startMonth: m, startDay: c_val, endMonth: m, endDay: po_val });
                        currentStart = null;
                        currentStartMonth = null;
                    } else if (!isNaN(c_val)) {
                        if (currentStart !== null) {
                            parsedVacations.push({ 
                                startMonth: currentStartMonth, 
                                startDay: currentStart, 
                                endMonth: currentStartMonth, 
                                endDay: calendarDaysInMonths[currentStartMonth] 
                            });
                        }
                        currentStart = c_val;
                        currentStartMonth = m;
                    } else if (!isNaN(po_val)) {
                        if (currentStart !== null) {
                            parsedVacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: m, endDay: po_val });
                            currentStart = null;
                            currentStartMonth = null;
                        }
                    }
                }

                if (currentStart !== null) {
                    parsedVacations.push({ 
                        startMonth: currentStartMonth, 
                        startDay: currentStart, 
                        endMonth: currentStartMonth, 
                        endDay: calendarDaysInMonths[currentStartMonth] 
                    });
                }

                // Map back to absolute dates
                employee.vacations = parsedVacations.map(vac => {
                    let sDay = String(vac.startDay).padStart(2, '0');
                    let sMonth = String(vac.startMonth + 1).padStart(2, '0');
                    let start = `2026-${sMonth}-${sDay}`;

                    let eDay = String(vac.endDay).padStart(2, '0');
                    let eMonth = String(vac.endMonth + 1).padStart(2, '0');
                    let end = `2026-${eMonth}-${eDay}`;

                    let totalDays = getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);

                    return { start, end, days: totalDays };
                });
            }
        });

        fetch(`${APP_PREFIX}/api/vacations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(allData)
        })
        .then(res => res.json())
        .then(() => {
            saveBtn.textContent = '💾 Сохранено!';
            setTimeout(() => {
                saveBtn.textContent = '💾 Сохранить изменения';
            }, 2000);
        })
        .catch(err => {
            saveBtn.textContent = '❌ Ошибка';
            console.error(err);
        });
    });

    // Excel-like keyboard navigation
    tableBody.addEventListener('keydown', (e) => {
        if (!e.target.classList.contains('day-input')) return;

        const currentInput = e.target;
        const tr = currentInput.closest('tr');
        if (!tr) return;

        const inputsInRow = Array.from(tr.querySelectorAll('.day-input'));
        const colIndex = inputsInRow.indexOf(currentInput);
        
        const rows = Array.from(tableBody.querySelectorAll('tr'));
        const rowIndex = rows.indexOf(tr);

        let nextInput = null;

        if (e.key === 'ArrowRight') {
            if (colIndex < inputsInRow.length - 1) {
                nextInput = inputsInRow[colIndex + 1];
            }
        } else if (e.key === 'ArrowLeft') {
            if (colIndex > 0) {
                nextInput = inputsInRow[colIndex - 1];
            }
        } else if (e.key === 'ArrowDown') {
            if (rowIndex < rows.length - 1) {
                nextInput = rows[rowIndex + 1].querySelectorAll('.day-input')[colIndex];
            }
        } else if (e.key === 'ArrowUp') {
            if (rowIndex > 0) {
                nextInput = rows[rowIndex - 1].querySelectorAll('.day-input')[colIndex];
            }
        }

        if (nextInput) {
            e.preventDefault();
            nextInput.focus();
            nextInput.select();
        }
    });

    // Tabs Switcher & Archive Management
    const tabCurrentBtn = document.getElementById('tabCurrentBtn');
    const tabArchiveBtn = document.getElementById('tabArchiveBtn');
    const panelCurrent = document.getElementById('panelCurrent');
    const panelArchive = document.getElementById('panelArchive');
    const badgeToggleLabel = document.getElementById('badgeToggleLabel');

    let archiveData = [];
    let selectedArchiveIndex = -1;

    if (tabCurrentBtn && tabArchiveBtn) {
        tabCurrentBtn.addEventListener('click', () => {
            tabCurrentBtn.classList.add('active');
            tabArchiveBtn.classList.remove('active');
            panelCurrent.style.display = 'block';
            panelArchive.style.display = 'none';
            if (badgeToggleLabel) badgeToggleLabel.style.display = '';
            if (holidaysBtn) holidaysBtn.style.display = '';
            if (saveBtn) saveBtn.style.display = '';
        });

        tabArchiveBtn.addEventListener('click', () => {
            tabArchiveBtn.classList.add('active');
            tabCurrentBtn.classList.remove('active');
            panelCurrent.style.display = 'none';
            panelArchive.style.display = 'block';
            if (badgeToggleLabel) badgeToggleLabel.style.display = 'none';
            if (holidaysBtn) holidaysBtn.style.display = 'none';
            if (saveBtn) saveBtn.style.display = 'none';

            loadArchive();
        });
    }

    const archiveTableBody = document.getElementById('archiveTableBody');
    const addArchiveRowBtn = document.getElementById('addArchiveRowBtn');
    const deleteArchiveRowBtn = document.getElementById('deleteArchiveRowBtn');
    const saveArchiveBtn = document.getElementById('saveArchiveBtn');



    function loadArchive() {
        fetch(`${APP_PREFIX}/api/vacations/archive`)
            .then(res => res.json())
            .then(data => {
                archiveData = data;
                if (archiveData.length === 0) {
                    archiveData = [{
                        y: 2025,
                        tab_num: '',
                        name: '',
                        start_date: '',
                        end_date: '',
                        days: 14,
                        note: ''
                    }];
                }
                renderArchiveTable();
            })
            .catch(err => console.error('Error loading archive:', err));
    }

    function renderArchiveTable() {
        if (!archiveTableBody) return;
        archiveTableBody.innerHTML = '';

        const empOptions = allData.map(e => `<option value="${escapeHtml(e.name)}" data-tab="${escapeHtml(e.tab_num || '')}">${escapeHtml(e.name)}</option>`).join('');

        archiveData.forEach((row, index) => {
            const tr = document.createElement('tr');
            if (selectedArchiveIndex === index) {
                tr.classList.add('selected-row');
            }

            tr.addEventListener('click', () => {
                selectedArchiveIndex = index;
                renderArchiveTable();
            });

            tr.innerHTML = `
                <td style="text-align:center; font-weight:bold; color:var(--muted);">${index + 1}</td>
                <td><input type="number" class="archive-input archive-year" value="${row.y || 2025}" style="text-align:center;"></td>
                <td>
                    <input type="text" class="archive-input archive-name" value="${escapeHtml(row.name || '')}" list="archiveEmpList_${index}" placeholder="ФИО сотрудника">
                    <datalist id="archiveEmpList_${index}">
                        ${empOptions}
                    </datalist>
                </td>
                <td><input type="text" class="archive-input archive-tab" value="${escapeHtml(row.tab_num || '')}" placeholder="Таб. №"></td>
                <td><input type="date" class="archive-input archive-start" value="${row.start_date || ''}"></td>
                <td><input type="date" class="archive-input archive-end" value="${row.end_date || ''}"></td>
                <td><input type="number" class="archive-input archive-days" value="${row.days || 0}" style="text-align:center;"></td>
                <td><input type="text" class="archive-input archive-note" value="${escapeHtml(row.note || '')}" placeholder="Примечание"></td>
            `;

            const startInp = tr.querySelector('.archive-start');
            const endInp = tr.querySelector('.archive-end');
            const daysInp = tr.querySelector('.archive-days');
            const nameInp = tr.querySelector('.archive-name');
            const tabInp = tr.querySelector('.archive-tab');

            const calcDays = () => {
                if (startInp.value && endInp.value) {
                    const s = new Date(startInp.value);
                    const e = new Date(endInp.value);
                    if (s <= e) {
                        const diffTime = Math.abs(e - s);
                        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;
                        daysInp.value = diffDays;
                        row.days = diffDays;
                    }
                }
            };

            startInp.addEventListener('change', calcDays);
            endInp.addEventListener('change', calcDays);

            nameInp.addEventListener('change', (e) => {
                const val = e.target.value;
                const match = allData.find(x => x.name === val);
                if (match && match.tab_num) {
                    tabInp.value = match.tab_num;
                    row.tab_num = match.tab_num;
                }
            });

            archiveTableBody.appendChild(tr);
        });
    }

    function syncArchiveDataFromDOM() {
        if (!archiveTableBody) return;
        const rows = archiveTableBody.querySelectorAll('tr');
        archiveData = Array.from(rows).map(tr => {
            return {
                y: parseInt(tr.querySelector('.archive-year').value) || 2025,
                name: tr.querySelector('.archive-name').value.trim(),
                tab_num: tr.querySelector('.archive-tab').value.trim(),
                start_date: tr.querySelector('.archive-start').value,
                end_date: tr.querySelector('.archive-end').value,
                days: parseInt(tr.querySelector('.archive-days').value) || 0,
                note: tr.querySelector('.archive-note').value.trim()
            };
        });
    }

    if (addArchiveRowBtn) {
        addArchiveRowBtn.addEventListener('click', () => {
            syncArchiveDataFromDOM();
            archiveData.push({
                y: 2025,
                tab_num: '',
                name: '',
                start_date: '',
                end_date: '',
                days: 14,
                note: ''
            });
            selectedArchiveIndex = archiveData.length - 1;
            renderArchiveTable();
        });
    }

    if (deleteArchiveRowBtn) {
        deleteArchiveRowBtn.addEventListener('click', () => {
            syncArchiveDataFromDOM();
            if (selectedArchiveIndex >= 0 && selectedArchiveIndex < archiveData.length) {
                archiveData.splice(selectedArchiveIndex, 1);
                selectedArchiveIndex = -1;
                renderArchiveTable();
            } else if (archiveData.length > 0) {
                archiveData.pop();
                renderArchiveTable();
            }
        });
    }

    if (saveArchiveBtn) {
        saveArchiveBtn.addEventListener('click', () => {
            syncArchiveDataFromDOM();
            saveArchiveBtn.textContent = 'Сохранение...';

            fetch(`${APP_PREFIX}/api/vacations/archive`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(archiveData)
            })
            .then(res => res.json())
            .then(() => {
                saveArchiveBtn.textContent = '💾 Архив сохранен!';
                setTimeout(() => {
                    saveArchiveBtn.textContent = '💾 Сохранить архив';
                }, 2000);
            })
            .catch(err => {
                saveArchiveBtn.textContent = '❌ Ошибка';
                console.error(err);
            });
        });
    }
});

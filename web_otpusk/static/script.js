document.addEventListener('DOMContentLoaded', () => {
    const APP_PREFIX = window.location.pathname.startsWith('/otpusk') ? '/otpusk' : '';
    
    const yearSelect = document.getElementById('yearSelect');
    let currentYear = yearSelect ? (parseInt(yearSelect.value) || 2026) : 2026;

    function getMonthsList(year) {
        return ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь', `Январь ${year + 1}`];
    }

    function getDaysInFeb(y) {
        return (y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) ? 29 : 28;
    }

    let months = getMonthsList(currentYear);
    let calendarDaysInMonths = [31, getDaysInFeb(currentYear), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31, 31];
    
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
            let datesStr = (holidaysData[m] && holidaysData[m].dates) ? holidaysData[m].dates : (m === 12 ? '1, 2, 3, 4, 5, 6, 7, 8' : '');
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
            th.innerHTML = `${m}<br><span style="font-weight:400; font-size:0.75rem;">${daysInMonths[i]} дн.</span>`;
            headerMonths.appendChild(th);

            const thSub = document.createElement('th');
            thSub.innerHTML = `<div style="display:flex; width: 100%;"><div style="flex:1;">с</div><div style="flex:1;">по</div></div>`;
            headerSub.appendChild(thSub);
        });
    }

    function updateDaysInMonths() {
        daysInMonths = months.map((m, i) => {
            const totalD = calendarDaysInMonths[i];
            const datesStr = (holidaysData[i] && holidaysData[i].dates) ? holidaysData[i].dates : (i === 12 ? '1, 2, 3, 4, 5, 6, 7, 8' : '');
            const hSet = parseHolidayDates(datesStr, totalD);
            return totalD - hSet.size;
        });
    }

    // Render Annual Calendar Grid (First 12 months of selected year)
    function renderAnnualCalendar(year) {
        const grid = document.getElementById('yearCalendarGrid');
        const yearTitle = document.getElementById('calendarYearTitle');
        if (!grid) return;
        if (yearTitle) yearTitle.textContent = year;

        grid.innerHTML = '';

        const baseMonthNames = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];

        baseMonthNames.forEach((monthName, mIndex) => {
            const card = document.createElement('div');
            card.className = 'month-card';

            const totalDaysInM = calendarDaysInMonths[mIndex];
            const datesStr = (holidaysData[mIndex] && holidaysData[mIndex].dates) ? holidaysData[mIndex].dates : '';
            const hSet = parseHolidayDates(datesStr, totalDaysInM);

            const firstDate = new Date(year, mIndex, 1);
            const firstDayIdx = (firstDate.getDay() + 6) % 7;

            let tableHtml = `
                <div class="month-card-title">${monthName}</div>
                <table class="month-calendar-table">
                    <thead>
                        <tr>
                            <th>Пн</th>
                            <th>Вт</th>
                            <th>Ср</th>
                            <th>Чт</th>
                            <th>Пт</th>
                            <th class="weekend-th">Сб</th>
                            <th class="weekend-th">Вс</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            let dayCounter = 1;
            let rowCount = Math.ceil((firstDayIdx + totalDaysInM) / 7);

            for (let r = 0; r < rowCount; r++) {
                tableHtml += '<tr>';
                for (let col = 0; col < 7; col++) {
                    const cellIdx = r * 7 + col;
                    if (cellIdx < firstDayIdx || dayCounter > totalDaysInM) {
                        tableHtml += '<td class="cal-empty"></td>';
                    } else {
                        const dayNum = dayCounter;
                        const isWeekend = (col === 5 || col === 6);
                        const isHoliday = hSet.has(dayNum);

                        let cellClass = 'cal-day';
                        if (isHoliday) {
                            cellClass = 'cal-holiday';
                        } else if (isWeekend) {
                            cellClass = 'cal-weekend';
                        }

                        tableHtml += `<td class="${cellClass}">${dayNum}</td>`;
                        dayCounter++;
                    }
                }
                tableHtml += '</tr>';
            }

            tableHtml += '</tbody></table>';
            card.innerHTML = tableHtml;
            grid.appendChild(card);
        });
    }

    // Load Data (holidays & vacations for selected year)
    function loadYearData(year) {
        Promise.all([
            fetch(`${APP_PREFIX}/api/holidays?year=${year}`).then(res => res.json()),
            fetch(`${APP_PREFIX}/api/vacations?year=${year}`).then(res => res.json())
        ]).then(([holidays, vacations]) => {
            holidaysData = holidays;
            updateDaysInMonths();
            renderHeaders();
            allData = vacations;
            renderTable(allData);
            renderAnnualCalendar(year);
        }).catch(err => console.error(err));
    }

    loadYearData(currentYear);

    if (yearSelect) {
        yearSelect.addEventListener('change', (e) => {
            currentYear = parseInt(e.target.value) || 2026;
            months = getMonthsList(currentYear);
            calendarDaysInMonths = [31, getDaysInFeb(currentYear), 31, 30, 31, 30, 31, 31, 30, 31, 30, 31, 31];
            
            const tabCurrentBtn = document.getElementById('tabCurrentBtn');
            if (tabCurrentBtn) {
                tabCurrentBtn.textContent = `📅 График отпусков ${currentYear}`;
            }
            const holidaysModalTitle = document.getElementById('holidaysModalTitle');
            if (holidaysModalTitle) {
                holidaysModalTitle.textContent = `📅 Праздничные дни по месяцах (${currentYear})`;
            }

            loadYearData(currentYear);
        });
    }

    // Modal Handlers
    function openHolidaysModal() {
        if (!holidaysTableBody) return;
        holidaysTableBody.innerHTML = '';
        holidaysData.forEach((item, index) => {
            const tr = document.createElement('tr');
            const totalD = calendarDaysInMonths[index] || 31;
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
                const totalD = calendarDaysInMonths[idx] || 31;
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
                if (holidaysData[idx]) {
                    holidaysData[idx].dates = input.value.trim();
                }
            });

            saveHolidaysBtn.textContent = 'Сохранение...';

            fetch(`${APP_PREFIX}/api/holidays?year=${currentYear}`, {
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
                renderAnnualCalendar(currentYear);
                document.querySelectorAll('#tableBody tr[data-emp-id]').forEach(tr => calculateRow(tr));
            })
            .catch(err => {
                saveHolidaysBtn.textContent = 'Ошибка';
                console.error(err);
            });
        });
    }

    // Versions Modal elements & handlers
    const versionsBtn = document.getElementById('versionsBtn');
    const versionsModal = document.getElementById('versionsModal');
    const closeVersionsModal = document.getElementById('closeVersionsModal');
    const cancelVersionsBtn = document.getElementById('cancelVersionsBtn');
    const versionModalYear = document.getElementById('versionModalYear');
    const newVersionNameInput = document.getElementById('newVersionNameInput');
    const createVersionBtn = document.getElementById('createVersionBtn');
    const versionsTableBody = document.getElementById('versionsTableBody');

    function openVersionsModal() {
        if (!versionsModal) return;
        if (versionModalYear) versionModalYear.textContent = currentYear;
        if (newVersionNameInput) newVersionNameInput.value = '';
        loadVersionsList();
        versionsModal.classList.add('active');
    }

    function closeVersionsModalFn() {
        if (versionsModal) versionsModal.classList.remove('active');
    }

    function loadVersionsList() {
        if (!versionsTableBody) return;
        versionsTableBody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:12px;">Загрузка версий...</td></tr>';

        fetch(`${APP_PREFIX}/api/versions?year=${currentYear}`)
            .then(res => res.json())
            .then(versions => {
                versionsTableBody.innerHTML = '';
                if (!Array.isArray(versions) || versions.length === 0) {
                    versionsTableBody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:12px; color:var(--muted);">Сохранённых версий пока нет. Вы можете сохранить текущую версию кнопкой выше.</td></tr>';
                    return;
                }

                versions.forEach((ver, idx) => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${idx + 1}</td>
                        <td><strong>${escapeHtml(ver.version_name)}</strong></td>
                        <td style="font-size: 12px; color: var(--muted);">${escapeHtml(ver.created_at)}</td>
                        <td style="text-align: center;">
                            <div style="display: flex; gap: 6px; justify-content: center;">
                                <button type="button" class="btn-load-version" data-id="${ver.id}" data-name="${escapeHtml(ver.version_name)}" style="padding: 4px 8px; font-size: 12px; background: #eaf1ff;">📥 Загрузить</button>
                                <button type="button" class="btn-delete-version" data-id="${ver.id}" data-name="${escapeHtml(ver.version_name)}" style="padding: 4px 8px; font-size: 12px; color: #ef4444; border-color: #fca5a5;">🗑️ Удалить</button>
                            </div>
                        </td>
                    `;
                    versionsTableBody.appendChild(tr);
                });

                // Attach click listeners to Load & Delete buttons
                versionsTableBody.querySelectorAll('.btn-load-version').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        const verId = e.target.dataset.id;
                        const verName = e.target.dataset.name;
                        if (!confirm(`Загрузить версию "${verName}" и сделать её активной?`)) return;

                        btn.textContent = 'Загрузка...';
                        fetch(`${APP_PREFIX}/api/versions/${verId}`)
                            .then(res => res.json())
                            .then(vData => {
                                if (vData && Array.isArray(vData.data)) {
                                    vData.data.forEach(savedEmp => {
                                        const emp = allData.find(e => String(e.tab_num || e.name) === String(savedEmp.tab_num || savedEmp.name));
                                        if (emp) {
                                            emp.vacations = savedEmp.vacations || [];
                                        }
                                    });

                                    fetch(`${APP_PREFIX}/api/vacations?year=${currentYear}`, {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify(allData)
                                    }).then(() => {
                                        renderTable(allData);
                                        closeVersionsModalFn();
                                    });
                                }
                            })
                            .catch(err => {
                                btn.textContent = 'Ошибка';
                                console.error(err);
                            });
                    });
                });

                versionsTableBody.querySelectorAll('.btn-delete-version').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        const verId = e.target.dataset.id;
                        const verName = e.target.dataset.name;
                        if (!confirm(`Удалить версию "${verName}"?`)) return;

                        btn.textContent = 'Удаление...';
                        fetch(`${APP_PREFIX}/api/versions/${verId}`, { method: 'DELETE' })
                            .then(res => res.json())
                            .then(() => loadVersionsList())
                            .catch(err => console.error(err));
                    });
                });
            })
            .catch(err => {
                versionsTableBody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:12px; color:#ef4444;">Ошибка при загрузке версий</td></tr>';
                console.error(err);
            });
    }

    if (versionsBtn) versionsBtn.addEventListener('click', openVersionsModal);
    if (closeVersionsModal) closeVersionsModal.addEventListener('click', closeVersionsModalFn);
    if (cancelVersionsBtn) cancelVersionsBtn.addEventListener('click', closeVersionsModalFn);

    if (createVersionBtn) {
        createVersionBtn.addEventListener('click', () => {
            const vName = newVersionNameInput ? newVersionNameInput.value.trim() : '';

            const rows = document.querySelectorAll('#tableBody tr[data-emp-id]');
            rows.forEach(tr => {
                const empId = parseInt(tr.dataset.empId);
                const employee = allData.find(e => e.id === empId);
                if (employee) {
                    const isCarriedOverJan = tr.dataset.carriedOverJan === "true";
                    const carriedStartD = parseInt(tr.dataset.carriedOverStartD);
                    const carriedEndD = parseInt(tr.dataset.carriedOverEndD);

                    let currentStart = null;
                    let currentStartMonth = null;
                    let parsedVacations = [];

                    for (let m = 0; m < 13; m++) {
                        const cInp = tr.querySelector(`.c-input[data-month="${m}"]`);
                        const poInp = tr.querySelector(`.po-input[data-month="${m}"]`);
                        if (!cInp || !poInp) continue;

                        const c_val = parseInt(cInp.value);
                        const po_val = parseInt(poInp.value);

                        if (!isNaN(c_val) && !isNaN(po_val)) {
                            if (currentStart !== null) {
                                parsedVacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
                            }
                            parsedVacations.push({ startMonth: m, startDay: c_val, endMonth: m, endDay: po_val });
                            currentStart = null;
                            currentStartMonth = null;
                        } else if (!isNaN(c_val)) {
                            if (currentStart !== null) {
                                parsedVacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
                            }
                            currentStart = c_val;
                            currentStartMonth = m;
                        } else if (!isNaN(po_val)) {
                            if (currentStart !== null) {
                                parsedVacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: m, endDay: po_val });
                                currentStart = null;
                                currentStartMonth = null;
                            } else {
                                parsedVacations.push({ startMonth: m, startDay: 1, endMonth: m, endDay: po_val });
                            }
                        }
                    }

                    if (currentStart !== null) {
                        parsedVacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
                    }

                    parsedVacations = parsedVacations.filter(vac => {
                        if (isCarriedOverJan && vac.startMonth === 0 && vac.endMonth === 0 && vac.startDay === carriedStartD && vac.endDay === carriedEndD) {
                            return false;
                        }
                        return true;
                    });

                    employee.vacations = parsedVacations.map(vac => {
                        let sYear = vac.startMonth === 12 ? (currentYear + 1) : currentYear;
                        let realSMonth = vac.startMonth === 12 ? 1 : (vac.startMonth + 1);
                        let sDay = String(vac.startDay).padStart(2, '0');
                        let sMonth = String(realSMonth).padStart(2, '0');
                        let start = `${sYear}-${sMonth}-${sDay}`;

                        let eYear = vac.endMonth === 12 ? (currentYear + 1) : currentYear;
                        let realEMonth = vac.endMonth === 12 ? 1 : (vac.endMonth + 1);
                        let eDay = String(vac.endDay).padStart(2, '0');
                        let eMonth = String(realEMonth).padStart(2, '0');
                        let end = `${eYear}-${eMonth}-${eDay}`;

                        let totalDays = getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);
                        return { start, end, days: totalDays };
                    });
                }
            });

            createVersionBtn.textContent = 'Сохранение версии...';
            fetch(`${APP_PREFIX}/api/versions?year=${currentYear}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ version_name: vName, data: allData })
            })
            .then(res => res.json())
            .then(() => {
                createVersionBtn.textContent = '➕ Сохранить текущую версию';
                if (newVersionNameInput) newVersionNameInput.value = '';
                loadVersionsList();
            })
            .catch(err => {
                createVersionBtn.textContent = 'Ошибка';
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

            // Month cells (13 months)
            for (let m = 0; m < 13; m++) {
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
                const sParts = String(vac.start).split('-');
                const eParts = String(vac.end).split('-');
                if (sParts.length < 3 || eParts.length < 3) return;

                const sYear = parseInt(sParts[0]);
                const sMonth = parseInt(sParts[1]) - 1;
                const startD = parseInt(sParts[2]);

                const eYear = parseInt(eParts[0]);
                const eMonth = parseInt(eParts[1]) - 1;
                const endD = parseInt(eParts[2]);

                let startM = (sYear === currentYear + 1 && sMonth === 0) ? 12 : sMonth;
                let endM = (eYear === currentYear + 1 && eMonth === 0) ? 12 : eMonth;

                const cInput = tr.querySelector(`.c-input[data-month="${startM}"]`);
                if (cInput) cInput.value = startD;

                const poInput = tr.querySelector(`.po-input[data-month="${endM}"]`);
                if (poInput) poInput.value = endD;
            });

            // Populate carried over vacations from previous year (January)
            (employee.carried_over_vacations || []).forEach(cov => {
                if (!cov || !cov.start || !cov.end) return;
                const sParts = String(cov.start).split('-');
                const eParts = String(cov.end).split('-');
                if (sParts.length < 3 || eParts.length < 3) return;

                const janPrefix = `${currentYear}-01-`;
                const covStartD = String(cov.start).startsWith(janPrefix) ? parseInt(sParts[2]) : 1;
                const covEndD = String(cov.end).startsWith(janPrefix) ? parseInt(eParts[2]) : calendarDaysInMonths[0];

                const cInput = tr.querySelector('.c-input[data-month="0"]');
                const poInput = tr.querySelector('.po-input[data-month="0"]');

                if (cInput && poInput && (!cInput.value || (parseInt(cInput.value) === covStartD && parseInt(poInput.value) === covEndD))) {
                    cInput.value = String(cov.start).startsWith(janPrefix) ? covStartD : '';
                    poInput.value = covEndD;
                    tr.dataset.carriedOverJan = "true";
                    tr.dataset.carriedOverStartD = covStartD;
                    tr.dataset.carriedOverEndD = covEndD;
                }
            });

            // Calculate and draw row
            calculateRow(tr);

            // Attach listeners to all inputs in this row
            const inputs = tr.querySelectorAll('.day-input');
            inputs.forEach(input => {
                input.addEventListener('input', () => calculateRow(tr));
            });
        });

        // Summary Row 1: Всего положено отпусков
        const trSumAllowed = document.createElement('tr');
        trSumAllowed.className = 'summary-row allowed-summary-row';
        trSumAllowed.innerHTML = `
            <td class="col-sticky-1 summary-label"><strong>Всего положено:</strong></td>
            <td class="col-sticky-2 summary-value"><strong id="grandAllowedSum">0</strong></td>
            ${Array.from({length: 13}, (_, m) => `<td class="month-cell summary-month-allowed" id="monthAllowedSum_${m}">0</td>`).join('')}
        `;
        tableBody.appendChild(trSumAllowed);

        // Summary Row 2: Всего занесено отпусков (факт)
        const trSumFact = document.createElement('tr');
        trSumFact.className = 'summary-row fact-summary-row';
        trSumFact.innerHTML = `
            <td class="col-sticky-1 summary-label"><strong>Занесено (факт):</strong></td>
            <td class="col-sticky-2 summary-value"><strong id="grandFactSum">0</strong></td>
            ${Array.from({length: 13}, (_, m) => `<td class="month-cell summary-month-fact" id="monthFactSum_${m}">0</td>`).join('')}
        `;
        tableBody.appendChild(trSumFact);

        // Summary Row 3: Отклонение / превышение / недобор (%)
        const trSumDiff = document.createElement('tr');
        trSumDiff.className = 'summary-row diff-summary-row';
        trSumDiff.innerHTML = `
            <td class="col-sticky-1 summary-label"><strong>Отклонение (%):</strong></td>
            <td class="col-sticky-2 summary-value"><strong id="grandDiffPct">0%</strong></td>
            ${Array.from({length: 13}, (_, m) => `<td class="month-cell summary-month-diff" id="monthDiffPct_${m}">0%</td>`).join('')}
        `;
        tableBody.appendChild(trSumDiff);

        updateTotals();
    }

    function calculateRow(tr) {
        if (!tr || !tr.dataset.empId) return;

        // Clear all previous results, lines, and badges
        tr.querySelectorAll('.day-result').forEach(el => el.textContent = '');
        tr.querySelectorAll('.vacation-line').forEach(el => el.remove());
        tr.querySelectorAll('.total-days-badge').forEach(el => el.remove());

        let currentStart = null;
        let currentStartMonth = null;
        let vacations = [];

        for (let m = 0; m < 13; m++) {
            const cInput = tr.querySelector(`.c-input[data-month="${m}"]`);
            const poInput = tr.querySelector(`.po-input[data-month="${m}"]`);
            if (!cInput || !poInput) continue;

            const cValStr = cInput.value.trim();
            const poValStr = poInput.value.trim();
            
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
                } else {
                    vacations.push({ startMonth: m, startDay: 1, endMonth: m, endDay: po_val });
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

        const isCarriedOverJan = tr.dataset.carriedOverJan === "true";
        const carriedStartD = parseInt(tr.dataset.carriedOverStartD);
        const carriedEndD = parseInt(tr.dataset.carriedOverEndD);

        vacations.forEach(vac => {
            if (isCarriedOverJan && vac.startMonth === 0 && vac.endMonth === 0 && vac.startDay === carriedStartD && vac.endDay === carriedEndD) {
                vac.is_carried_over = true;
            }
        });

        let allowedStr = tr.querySelector('.allowed-days-input') ? tr.querySelector('.allowed-days-input').value : '';
        let allowedDays = allowedStr ? parseInt(allowedStr) : Infinity;

        // Calculate grand total excluding holidays and carried over vacations
        let grandTotalDays = 0;
        vacations.forEach(vac => {
            if (!vac.is_carried_over) {
                grandTotalDays += getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);
            }
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

                if (!cellWrapper) continue;

                if (vac.startMonth === vac.endMonth) {
                    let left = ((vac.startDay - 1) / daysInM) * 100;
                    let width = ((vac.endDay - vac.startDay + 1) / daysInM) * 100;
                    drawLine(cellWrapper, left, width, vac.is_carried_over);
                } else if (m === vac.startMonth) {
                    let left = ((vac.startDay - 1) / daysInM) * 100;
                    let width = 100 - left;
                    drawLine(cellWrapper, left, width, vac.is_carried_over);
                } else if (m === vac.endMonth) {
                    let width = (vac.endDay / daysInM) * 100;
                    drawLine(cellWrapper, 0, width, vac.is_carried_over);
                } else {
                    drawLine(cellWrapper, 0, 100, vac.is_carried_over);
                }
            }

            // Calculate center point in the gap between dates
            let centerM, centerLeft;
            if (vac.startMonth === vac.endMonth) {
                centerM = vac.startMonth;
                centerLeft = 50;
            } else {
                let centerPoint = (vac.startMonth + vac.endMonth + 1) / 2;
                centerM = Math.floor(centerPoint);
                centerLeft = (centerPoint - centerM) * 100;
            }

            let badgeText = totalDays;
            let overflowClass = '';
            if (vac.is_carried_over) {
                overflowClass = 'badge-carried-over';
            } else if (overflow > 0) {
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

        const cInp0 = tr.querySelector('.c-input[data-month="0"]');
        const poInp0 = tr.querySelector('.po-input[data-month="0"]');
        const hasCarriedOver = vacations.some(v => v.is_carried_over);
        if (cInp0 && poInp0) {
            if (hasCarriedOver) {
                cInp0.classList.add('carried-over-input');
                poInp0.classList.add('carried-over-input');
            } else {
                cInp0.classList.remove('carried-over-input');
                poInp0.classList.remove('carried-over-input');
            }
        }

        updateTotals();
    }

    function updateTotals() {
        let allowedSum = 0;
        let factSum = 0;
        const monthFactSums = Array(13).fill(0);

        const empRows = tableBody.querySelectorAll('tr[data-emp-id]');
        empRows.forEach(tr => {
            const allowedInp = tr.querySelector('.allowed-days-input');
            if (allowedInp) {
                allowedSum += (parseInt(allowedInp.value) || 0);
            }

            const isCarriedOverJan = tr.dataset.carriedOverJan === "true";
            const carriedStartD = parseInt(tr.dataset.carriedOverStartD);
            const carriedEndD = parseInt(tr.dataset.carriedOverEndD);

            let currentStart = null;
            let currentStartMonth = null;
            let vacations = [];

            for (let m = 0; m < 13; m++) {
                const cInp = tr.querySelector(`.c-input[data-month="${m}"]`);
                const poInp = tr.querySelector(`.po-input[data-month="${m}"]`);
                if (!cInp || !poInp) continue;

                const c_val = parseInt(cInp.value);
                const po_val = parseInt(poInp.value);

                if (!isNaN(c_val) && !isNaN(po_val)) {
                    if (currentStart !== null) {
                        vacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
                    }
                    vacations.push({ startMonth: m, startDay: c_val, endMonth: m, endDay: po_val });
                    currentStart = null;
                    currentStartMonth = null;
                } else if (!isNaN(c_val)) {
                    if (currentStart !== null) {
                        vacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
                    }
                    currentStart = c_val;
                    currentStartMonth = m;
                } else if (!isNaN(po_val)) {
                    if (currentStart !== null) {
                        vacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: m, endDay: po_val });
                        currentStart = null;
                        currentStartMonth = null;
                    } else {
                        vacations.push({ startMonth: m, startDay: 1, endMonth: m, endDay: po_val });
                    }
                }
            }
            if (currentStart !== null) {
                vacations.push({ startMonth: currentStartMonth, startDay: currentStart, endMonth: currentStartMonth, endDay: calendarDaysInMonths[currentStartMonth] });
            }

            vacations.forEach(vac => {
                if (isCarriedOverJan && vac.startMonth === 0 && vac.endMonth === 0 && vac.startDay === carriedStartD && vac.endDay === carriedEndD) {
                    vac.is_carried_over = true;
                }

                // Count in fact totals regardless of carried_over status!
                let empVacDays = getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);
                factSum += empVacDays;

                for (let m = vac.startMonth; m <= vac.endMonth; m++) {
                    let s = (m === vac.startMonth) ? vac.startDay : 1;
                    let e = (m === vac.endMonth) ? vac.endDay : calendarDaysInMonths[m];
                    monthFactSums[m] += getWorkingVacationDays(m, s, m, e);
                }
            });
        });

        const allowedEl = document.getElementById('grandAllowedSum');
        if (allowedEl) allowedEl.textContent = allowedSum;

        const factEl = document.getElementById('grandFactSum');
        if (factEl) factEl.textContent = factSum;

        const grandDiffEl = document.getElementById('grandDiffPct');
        if (grandDiffEl) {
            const grandDiff = factSum - allowedSum;
            if (allowedSum > 0) {
                const grandPct = Math.round((grandDiff / allowedSum) * 100);
                const sign = grandPct > 0 ? '+' : '';
                grandDiffEl.textContent = `${sign}${grandPct}%`;
                grandDiffEl.className = grandPct > 0 ? 'diff-excess' : (grandPct < 0 ? 'diff-shortage' : 'diff-exact');
            } else {
                grandDiffEl.textContent = '0%';
                grandDiffEl.className = 'diff-exact';
            }
        }

        // Total working days in main year (first 12 months)
        const totalYearWorkingDays = daysInMonths.slice(0, 12).reduce((a, b) => a + b, 0) || 365;

        for (let m = 0; m < 13; m++) {
            const mWorkingDays = daysInMonths[m] || 30;
            const mAllowedCalc = Math.round((allowedSum / totalYearWorkingDays) * mWorkingDays);
            const mFact = monthFactSums[m];
            
            const mAllowedEl = document.getElementById(`monthAllowedSum_${m}`);
            if (mAllowedEl) mAllowedEl.textContent = mAllowedCalc;

            const mFactEl = document.getElementById(`monthFactSum_${m}`);
            if (mFactEl) mFactEl.textContent = mFact;

            const mDiffEl = document.getElementById(`monthDiffPct_${m}`);
            if (mDiffEl) {
                const mDiff = mFact - mAllowedCalc;
                if (mAllowedCalc > 0) {
                    const mPct = Math.round((mDiff / mAllowedCalc) * 100);
                    const sign = mPct > 0 ? '+' : '';
                    mDiffEl.textContent = `${sign}${mPct}%`;
                    mDiffEl.className = 'month-cell summary-month-diff ' + (mPct > 0 ? 'diff-excess' : (mPct < 0 ? 'diff-shortage' : 'diff-exact'));
                } else if (mFact > 0) {
                    mDiffEl.textContent = '+100%';
                    mDiffEl.className = 'month-cell summary-month-diff diff-excess';
                } else {
                    mDiffEl.textContent = '0%';
                    mDiffEl.className = 'month-cell summary-month-diff diff-exact';
                }
            }
        }
    }

    function drawLine(wrapper, leftPct, widthPct, isCarried = false) {
        const extraClass = isCarried ? ' vacation-line-carried' : '';
        wrapper.insertAdjacentHTML('beforeend', `<div class="vacation-line${extraClass}" style="left: ${leftPct}%; width: ${widthPct}%;"></div>`);
    }

    // Save functionality
    saveBtn.addEventListener('click', () => {
        saveBtn.textContent = 'Сохранение...';
        
        const rows = document.querySelectorAll('#tableBody tr[data-emp-id]');
        rows.forEach(tr => {
            const empId = parseInt(tr.dataset.empId);
            const employee = allData.find(e => e.id === empId);
            
            if (employee) {
                const allowedInput = tr.querySelector('.allowed-days-input');
                if (allowedInput) {
                    employee.allowedDays = parseInt(allowedInput.value) || 0;
                }

                let currentStart = null;
                let currentStartMonth = null;
                let parsedVacations = [];

                for (let m = 0; m < 13; m++) {
                    const cInp = tr.querySelector(`.c-input[data-month="${m}"]`);
                    const poInp = tr.querySelector(`.po-input[data-month="${m}"]`);
                    if (!cInp || !poInp) continue;

                    const c_val = parseInt(cInp.value);
                    const po_val = parseInt(poInp.value);

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
                        } else {
                            parsedVacations.push({ startMonth: m, startDay: 1, endMonth: m, endDay: po_val });
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

                // Map back to absolute dates, filtering out carried over vacations from previous year
                const isCarriedOverJan = tr.dataset.carriedOverJan === "true";
                const carriedStartD = parseInt(tr.dataset.carriedOverStartD);
                const carriedEndD = parseInt(tr.dataset.carriedOverEndD);

                parsedVacations = parsedVacations.filter(vac => {
                    if (isCarriedOverJan && vac.startMonth === 0 && vac.endMonth === 0 && vac.startDay === carriedStartD && vac.endDay === carriedEndD) {
                        return false;
                    }
                    return true;
                });

                employee.vacations = parsedVacations.map(vac => {
                    let sYear = vac.startMonth === 12 ? (currentYear + 1) : currentYear;
                    let realSMonth = vac.startMonth === 12 ? 1 : (vac.startMonth + 1);
                    let sDay = String(vac.startDay).padStart(2, '0');
                    let sMonth = String(realSMonth).padStart(2, '0');
                    let start = `${sYear}-${sMonth}-${sDay}`;

                    let eYear = vac.endMonth === 12 ? (currentYear + 1) : currentYear;
                    let realEMonth = vac.endMonth === 12 ? 1 : (vac.endMonth + 1);
                    let eDay = String(vac.endDay).padStart(2, '0');
                    let eMonth = String(realEMonth).padStart(2, '0');
                    let end = `${eYear}-${eMonth}-${eDay}`;

                    let totalDays = getWorkingVacationDays(vac.startMonth, vac.startDay, vac.endMonth, vac.endDay);

                    return { start, end, days: totalDays };
                });
            }
        });

        fetch(`${APP_PREFIX}/api/vacations?year=${currentYear}`, {
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
        
        const rows = Array.from(tableBody.querySelectorAll('tr[data-emp-id]'));
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
            if (rowIndex >= 0 && rowIndex < rows.length - 1) {
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

            // При переключении на годовой график перезагружаем данные из сервера
            if (typeof loadVacations === 'function' && typeof currentYear !== 'undefined') {
                loadVacations(currentYear);
            }
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
                // Перезагружаем годовой график после обновления архива
                if (typeof loadVacations === 'function' && typeof currentYear !== 'undefined') {
                    loadVacations(currentYear);
                }
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

    // Excel Import functionality for Archive
    const importArchiveBtn = document.getElementById('importArchiveBtn');
    const importArchiveFileInput = document.getElementById('importArchiveFileInput');

    if (importArchiveBtn && importArchiveFileInput) {
        importArchiveBtn.addEventListener('click', () => {
            importArchiveFileInput.click();
        });

        importArchiveFileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const modeChoice = confirm("Импорт записей из Excel:\n\n[Нажмите ОК] — Добавить новые записи к имеющемуся архиву\n[Нажмите Отмена] — Очистить архив и заменить файл всеми данными из Excel");
            const mode = modeChoice ? "append" : "replace";

            const formData = new FormData();
            formData.append('file', file);

            importArchiveBtn.textContent = 'Импорт...';
            fetch(`${APP_PREFIX}/api/vacations/archive/import?mode=${mode}`, {
                method: 'POST',
                body: formData
            })
            .then(res => {
                if (!res.ok) {
                    return res.json().then(err => { throw new Error(err.detail || 'Ошибка импорта'); });
                }
                return res.json();
            })
            .then(data => {
                importArchiveBtn.textContent = '📥 Импорт из Excel';
                importArchiveFileInput.value = '';
                alert(`Успешно импортировано записей: ${data.imported_count || 0}`);
                loadArchive();
                // Перезагружаем годовой график после импорта в архив
                if (typeof loadVacations === 'function' && typeof currentYear !== 'undefined') {
                    loadVacations(currentYear);
                }
            })
            .catch(err => {
                importArchiveBtn.textContent = '📥 Импорт из Excel';
                importArchiveFileInput.value = '';
                alert(`Ошибка при импорте: ${err.message}`);
                console.error(err);
            });
        });
    }

    // History Matrix Modal logic
    const historyMatrixBtn = document.getElementById('historyMatrixBtn');
    const historyModal = document.getElementById('historyModal');
    const closeHistoryModal = document.getElementById('closeHistoryModal');
    const cancelHistoryBtn = document.getElementById('cancelHistoryBtn');
    const historyHeaderRow = document.getElementById('historyHeaderRow');
    const historyTableBody = document.getElementById('historyTableBody');
    const historySearchInput = document.getElementById('historySearchInput');

    let historyMatrixCache = null;

    function openHistoryModal() {
        if (!historyModal) return;
        historyModal.style.display = 'flex';
        loadHistoryMatrix();
    }

    function closeHistoryModalFunc() {
        if (!historyModal) return;
        historyModal.style.display = 'none';
    }

    if (historyMatrixBtn) {
        historyMatrixBtn.addEventListener('click', openHistoryModal);
    }
    if (closeHistoryModal) {
        closeHistoryModal.addEventListener('click', closeHistoryModalFunc);
    }
    if (cancelHistoryBtn) {
        cancelHistoryBtn.addEventListener('click', closeHistoryModalFunc);
    }
    if (historyModal) {
        historyModal.addEventListener('click', (e) => {
            if (e.target === historyModal) closeHistoryModalFunc();
        });
    }

    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            if (historyMatrixCache) {
                renderHistoryMatrix(historyMatrixCache, historySearchInput.value.trim());
            }
        });
    }

    function loadHistoryMatrix() {
        if (!historyTableBody) return;
        historyTableBody.innerHTML = '<tr><td colspan="20" style="text-align:center; padding: 20px;">Загрузка истории отпусков...</td></tr>';

        fetch(`${APP_PREFIX}/api/vacations/history_matrix`)
            .then(res => res.json())
            .then(data => {
                historyMatrixCache = data;
                renderHistoryMatrix(data, historySearchInput ? historySearchInput.value.trim() : '');
            })
            .catch(err => {
                console.error('Error loading history matrix:', err);
                historyTableBody.innerHTML = '<tr><td colspan="20" style="text-align:center; color: red; padding: 20px;">Ошибка загрузки данных истории отпусков.</td></tr>';
            });
    }

    function renderHistoryMatrix(data, filterText = '') {
        if (!historyHeaderRow || !historyTableBody) return;

        const years = data.years || [];
        const employees = data.employees || [];

        // Generate Header Row
        let headerHtml = `
            <th class="col-sticky-1" style="width: 260px; min-width: 260px; position: sticky; left: 0; background: #f1f5f9; z-index: 11; border-right: 2px solid #cbd5e1; padding: 8px 12px; text-align: left;">Сотрудник</th>
            <th class="col-sticky-2" style="width: 100px; min-width: 100px; position: sticky; left: 260px; background: #f1f5f9; z-index: 11; border-right: 2px solid #cbd5e1; padding: 8px 6px; text-align: center;">Кол-во дней</th>
        `;

        years.forEach(y => {
            headerHtml += `<th style="min-width: 90px; padding: 8px 6px; text-align: center; background: #f1f5f9; border-bottom: 2px solid #cbd5e1; font-weight: 700;">${y}</th>`;
        });
        historyHeaderRow.innerHTML = headerHtml;

        // Filter employees if search query present
        const query = filterText.toLowerCase();
        const filteredEmployees = employees.filter(emp => {
            if (!query) return true;
            const name = (emp.name || '').toLowerCase();
            const full = (emp.full_name || '').toLowerCase();
            const pos = (emp.position || '').toLowerCase();
            const tab = (emp.tab_num || '').toLowerCase();
            return name.includes(query) || full.includes(query) || pos.includes(query) || tab.includes(query);
        });

        if (filteredEmployees.length === 0) {
            historyTableBody.innerHTML = `<tr><td colspan="${years.length + 2}" style="text-align:center; padding: 20px; color: #64748b;">Сотрудники не найдены</td></tr>`;
            return;
        }

        let bodyHtml = '';

        filteredEmployees.forEach(emp => {
            const empName = escapeHtml(emp.name || emp.full_name || '');
            const empPos = escapeHtml(emp.position || '');
            const vDays = emp.vacation_days || 52;
            const history = emp.history || {};

            bodyHtml += `<tr style="border-bottom: 1px solid #e2e8f0;">`;
            bodyHtml += `
                <td class="col-sticky-1" style="position: sticky; left: 0; background: #ffffff; z-index: 5; border-right: 2px solid #cbd5e1; padding: 8px 12px; font-weight: 500;">
                    <div style="font-weight: 600; color: #1e293b;">${empName}</div>
                    <div style="font-size: 0.78rem; color: #64748b;">${empPos}</div>
                </td>
                <td class="col-sticky-2" style="position: sticky; left: 260px; background: #ffffff; z-index: 5; border-right: 2px solid #cbd5e1; text-align: center; font-weight: 600; color: #334155;">
                    ${vDays}
                </td>
            `;

            years.forEach(y => {
                const yearItems = history[String(y)] || [];
                bodyHtml += `<td style="padding: 4px; text-align: center; vertical-align: middle; min-width: 90px; border-right: 1px solid #f1f5f9;">`;

                if (yearItems.length === 0) {
                    bodyHtml += `<span style="color: #cbd5e1; font-size: 0.8rem;">—</span>`;
                } else {
                    bodyHtml += `<div style="display: flex; flex-direction: column; gap: 3px; align-items: center; justify-content: center;">`;
                    yearItems.forEach(item => {
                        const mName = escapeHtml(item.month_name || 'отпуск');
                        const season = item.season;
                        const startDate = formatDateRu(item.start);
                        const endDate = formatDateRu(item.end);
                        const days = item.days ? `${item.days} дн.` : '';
                        const tooltip = `${startDate} — ${endDate} (${days})`.trim();

                        let badgeStyle = 'background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1;';
                        if (season === 'summer') {
                            badgeStyle = 'background: #d32f2f; color: #ffffff; font-weight: 700; border: 1px solid #b71c1c;';
                        } else if (season === 'winter') {
                            badgeStyle = 'background: #0288d1; color: #ffffff; font-weight: 600; border: 1px solid #0277bd;';
                        } else {
                            badgeStyle = 'background: #e8f5e9; color: #1b5e20; border: 1px solid #c8e6c9; font-weight: 500;';
                        }

                        bodyHtml += `
                            <span title="${tooltip}" style="display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.82rem; cursor: pointer; text-transform: lowercase; min-width: 52px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05); ${badgeStyle}">
                                ${mName}
                            </span>
                        `;
                    });
                    bodyHtml += `</div>`;
                }

                bodyHtml += `</td>`;
            });

            bodyHtml += `</tr>`;
        });

        historyTableBody.innerHTML = bodyHtml;
    }

    function formatDateRu(isoStr) {
        if (!isoStr) return '';
        const parts = isoStr.split('-');
        if (parts.length === 3) {
            return `${parts[2]}.${parts[1]}.${parts[0]}`;
        }
        return isoStr;
    }
});

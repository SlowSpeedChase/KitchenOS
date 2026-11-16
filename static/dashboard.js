/* KitchenOS dashboard: fills the three columns of `/`. See templates/home.html. */
(function () {
    'use strict';

    const MEALS = ['breakfast', 'lunch', 'snack', 'dinner'];

    // ---- dates (same arithmetic as templates/meal_calendar.html) ----
    function pad(n) { return String(n).padStart(2, '0'); }
    function iso(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
    function addDays(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); }
    function weekOf(d) {
        const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
        const dayNum = date.getUTCDay() || 7;
        date.setUTCDate(date.getUTCDate() + 4 - dayNum);
        const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
        return `${date.getUTCFullYear()}-W${pad(Math.ceil((((date - yearStart) / 86400000) + 1) / 7))}`;
    }
    function mondayOf(week) {
        const [y, w] = week.split('-W').map(Number);
        const jan4Dow = new Date(y, 0, 4).getDay() || 7;
        return new Date(y, 0, 4 - (jan4Dow - 1) + (w - 1) * 7);
    }

    const now = new Date();
    const todayISO = iso(now);
    const thisWeek = weekOf(now);
    const asked = new URLSearchParams(location.search).get('week') || '';
    const state = {
        view: 'week',
        week: /^\d{4}-W\d{2}$/.test(asked) ? asked : thisWeek,
        month: new Date(now.getFullYear(), now.getMonth(), 1),
    };
    window.koDash = { week: state.week };

    // ---- dom + http ----
    const $ = id => document.getElementById(id);
    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }
    async function request(url, options) {
        const resp = await fetch(url, options);
        let data = null;
        try { data = await resp.json(); } catch (err) { /* empty or non-JSON body */ }
        if (!resp.ok) {
            const error = new Error((data && data.error) || `HTTP ${resp.status}`);
            error.status = resp.status;
            throw error;
        }
        return data;
    }
    const getJSON = url => request(url);
    const postJSON = (url, body) => request(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    function failed(body, message, retry) {
        body.replaceChildren(el('p', 'note bad', message));
        const again = el('button', 'act', 'Try again');
        again.type = 'button';
        again.addEventListener('click', retry);
        body.appendChild(again);
    }

    // ---- labels ----
    const shortDay = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
    const longDay = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
    function weekLabel(week) {
        const monday = mondayOf(week);
        const range = `${shortDay.format(monday)} – ${shortDay.format(addDays(monday, 6))}`;
        if (week === thisWeek) return `This week · ${range}`;
        if (week === weekOf(addDays(now, 7))) return `Next week · ${range}`;
        if (week === weekOf(addDays(now, -7))) return `Last week · ${range}`;
        return range;
    }

    // ---- meals: week ----
    // A plate (bundle) is several cooks sharing bundle_id; show it once, by name.
    function mealsOn(planned, date) {
        const seen = new Set();
        const out = [];
        planned.filter(p => p.date === date)
            .sort((a, b) => MEALS.indexOf(a.meal) - MEALS.indexOf(b.meal))
            .forEach(p => {
                const key = (p.bundle_id ? `b:${p.bundle_id}` : `c:${p.cook_id}`) + `|${p.meal}`;
                if (seen.has(key)) return;
                seen.add(key);
                out.push(p);
            });
        return out;
    }

    async function move(p, date, body) {
        const url = p.bundle_id ? `/api/bundles/${encodeURIComponent(p.bundle_id)}/move`
                                : `/api/cooks/${p.cook_id}/move`;
        try {
            await postJSON(url, { date, meal: p.meal });
            refreshAll();
        } catch (err) {
            await loadMeals();
            $('meals-body').prepend(el('p', 'note bad', `Couldn’t move it. ${err.message}`));
        }
    }

    function mealRow(p, monday) {
        const row = el('details', 'meal');
        if (p.anchor) row.classList.add('anchor');  // only the cook itself moves; a leftover follows its placement
        row.planned = p;
        const summary = el('summary', null, p.bundle_name || p.recipe);
        const tags = [];
        if (p.meal !== 'dinner') tags.push(p.meal);
        if (!p.anchor) tags.push('leftover');
        if (tags.length) summary.appendChild(el('span', 'tag', tags.join(' · ')));
        row.appendChild(summary);

        const body = el('div', 'meal-body');
        if (!p.bundle_id) {
            const open = el('a', null, 'Open recipe');
            open.href = `/recipe/${encodeURIComponent(p.recipe)}`;
            body.appendChild(open);
        }
        if (p.anchor) {  // the same move as a drag, for keyboards and screen readers
            const pick = el('select');
            pick.setAttribute('aria-label', 'Move to another day');
            for (let i = 0; i < 7; i++) {
                const d = addDays(monday, i);
                const option = el('option', null, longDay.format(d));
                option.value = iso(d);
                option.selected = iso(d) === p.date;
                pick.appendChild(option);
            }
            pick.addEventListener('change', () => move(p, pick.value, body));
            body.appendChild(pick);
        }
        const edit = el('a', null, 'Edit in planner');
        edit.href = `/meal-planner?week=${state.week}`;
        body.appendChild(edit);
        row.appendChild(body);
        return row;
    }

    function renderWeek(board) {
        const monday = mondayOf(state.week);
        const dayName = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric' });
        const week = el('div', 'week');
        for (let i = 0; i < 7; i++) {
            const d = addDays(monday, i);
            const date = iso(d);
            const day = el('article', 'day');
            day.dataset.date = date;
            if (date === todayISO) day.classList.add('today');
            day.appendChild(el('div', 'day-name', date === todayISO ? 'Today' : dayName.format(d)));
            const slots = el('div', 'slots');
            const meals = mealsOn(board.planned_meals || [], date);
            meals.forEach(p => slots.appendChild(mealRow(p, monday)));
            day.appendChild(slots);
            const add = el('button', 'open', 'Add meal');
            add.type = 'button';
            add.addEventListener('click', () => openCook(date));
            day.appendChild(add);
            // Drag ends in the ledger move API and nothing else; the redraw that
            // follows is the source of truth, so a refused move snaps back.
            if (window.Sortable) {
                Sortable.create(slots, {
                    group: 'meals', draggable: 'details.meal.anchor', animation: 120,
                    delay: 150, delayOnTouchOnly: true,
                    onAdd: event => move(event.item.planned, date, event.item.querySelector('.meal-body')),
                });
            }
            week.appendChild(day);
        }
        $('meals-body').replaceChildren(week);
    }

    // ---- meals: month ----
    async function loadMonth() {
        const first = state.month;
        const label = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });
        $('meals-label').textContent = label.format(first);
        const start = mondayOf(weekOf(first));
        const last = new Date(first.getFullYear(), first.getMonth() + 1, 0);
        const weeks = [];
        for (let d = start; d <= last; d = addDays(d, 7)) weeks.push(weekOf(d));

        // One failed week must not blank the month: its days simply show no dish.
        const boards = await Promise.allSettled(weeks.map(w => getJSON(`/api/week-board/${w}`)));
        if (boards.every(b => b.status === 'rejected')) {
            failed($('meals-body'), 'Couldn’t load meals.', loadMeals);
            return;
        }
        const planned = boards.flatMap(b => b.status === 'fulfilled' ? (b.value.planned_meals || []) : []);

        const grid = el('div', 'month');
        ['M', 'T', 'W', 'T', 'F', 'S', 'S'].forEach(d => grid.appendChild(el('div', 'dow', d)));
        const spoken = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
        for (let i = 0; i < weeks.length * 7; i++) {
            const d = addDays(start, i);
            const date = iso(d);
            const cell = el('button', 'cell');
            cell.type = 'button';
            if (d.getMonth() !== first.getMonth()) cell.classList.add('out');
            if (date === todayISO) cell.classList.add('today');
            cell.appendChild(el('span', 'num', String(d.getDate())));
            const dinners = mealsOn(planned, date).filter(p => p.meal === 'dinner');
            dinners.forEach(p => cell.appendChild(el('span', 'dish', p.bundle_name || p.recipe)));
            cell.setAttribute('aria-label',
                `${spoken.format(d)}: ${dinners.map(p => p.bundle_name || p.recipe).join(', ') || 'open'}`);
            cell.addEventListener('click', () => {
                state.week = weekOf(d);
                window.koDash.week = state.week;
                setView('week');
            });
            grid.appendChild(cell);
        }
        $('meals-body').replaceChildren(grid);
    }

    async function loadMeals() {
        if (state.view === 'month') return loadMonth();
        $('meals-label').textContent = weekLabel(state.week);
        try {
            renderWeek(await getJSON(`/api/week-board/${state.week}`));
        } catch (err) {
            failed($('meals-body'), 'Couldn’t load meals.', loadMeals);
        }
    }

    function setView(view) {
        state.view = view;
        $('view-week').setAttribute('aria-pressed', String(view === 'week'));
        $('view-month').setAttribute('aria-pressed', String(view === 'month'));
        if (view === 'month') {
            const monday = mondayOf(state.week);
            state.month = new Date(monday.getFullYear(), monday.getMonth(), 1);
            loadMeals();  // grocery and inventory do not move
        } else {
            refreshAll();
        }
    }
    $('view-week').addEventListener('click', () => setView('week'));
    $('view-month').addEventListener('click', () => setView('month'));

    function shift(direction) {
        if (state.view === 'month') {
            state.month = new Date(state.month.getFullYear(), state.month.getMonth() + direction, 1);
            loadMeals();
            return;
        }
        state.week = weekOf(addDays(mondayOf(state.week), 7 * direction));
        window.koDash.week = state.week;
        refreshAll();
    }
    $('meals-prev').addEventListener('click', () => shift(-1));
    $('meals-next').addEventListener('click', () => shift(1));

    // ---- to buy ----
    // crypto.randomUUID needs a secure context; a plain-HTTP tailnet host is not one.
    function uuid() {
        if (crypto.randomUUID) return crypto.randomUUID();
        const b = crypto.getRandomValues(new Uint8Array(16));
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }

    function renderBuy(list) {
        const body = $('buy-body');
        const left = list.rows.filter(r => !r.completed).length;
        $('buy-label').textContent = `To buy · ${left}`;
        // Unticked first; a ticked item sinks rather than vanishing, so a mis-tap is visible.
        const rows = [...list.rows].sort((a, b) => Number(a.completed) - Number(b.completed));
        const nodes = rows.map(r => {
            const row = el('label', 'buy-row');
            if (r.completed) row.classList.add('done');
            if (r.id) {  // a row without an id predates row identity and cannot be ticked from here
                const box = el('input');
                box.type = 'checkbox';
                box.checked = r.completed;
                box.addEventListener('change', () => tick(list, r, box.checked));
                row.appendChild(box);
            }
            row.appendChild(el('span', null, r.text));
            return row;
        });
        if (!nodes.length) nodes.push(el('p', 'note', 'Nothing to buy this week.'));
        const foot = el('p', 'foot');
        const full = el('a', null, 'Full list');
        full.href = `/current/shopping-list?week=${list.week}`;
        foot.appendChild(full);
        body.replaceChildren(...nodes, foot);
    }

    async function tick(list, row, completed) {
        try {
            renderBuy(await postJSON(`/api/shopping-list/saved/${list.week}/completion`, {
                row_id: row.id, completed, expected_hash: list.content_hash, operation_id: uuid(),
            }));
        } catch (err) {
            await loadBuy();  // the list changed elsewhere, or the write failed: show the truth
            $('buy-body').prepend(el('p', 'note bad',
                err.status === 409 ? 'The list changed somewhere else. Tick it again.'
                                   : 'Couldn’t save that tick. Try again.'));
        }
    }

    async function buildList(week) {
        $('buy-body').replaceChildren(el('p', 'note', 'Building the list…'));
        try {
            await postJSON('/generate-shopping-list', { week });
            await loadBuy();
        } catch (err) {
            failed($('buy-body'), 'Couldn’t build the list.', () => buildList(week));
        }
    }

    async function loadBuy() {
        const week = state.week;
        try {
            renderBuy(await getJSON(`/api/shopping-list/saved/${week}`));
        } catch (err) {
            if (err.status !== 404) {
                failed($('buy-body'), 'Couldn’t load the list.', loadBuy);
                return;
            }
            $('buy-label').textContent = 'To buy';
            const build = el('button', 'act', 'Build this week’s list');
            build.type = 'button';
            build.addEventListener('click', () => buildList(week));
            $('buy-body').replaceChildren(el('p', 'note', 'No list for this week yet.'), build);
        }
    }

    // ---- on hand ----
    const PLACES = ['fridge', 'freezer', 'counter', 'pantry', 'other'];

    function amount(item) {
        // A row is a container, not a count: "1 ct" says nothing, so it is not shown.
        if (item.quantity === 1 && ['ct', 'ea', ''].includes(item.unit || '')) return '';
        const n = Number.isInteger(item.quantity) ? String(item.quantity) : item.quantity.toFixed(1);
        return `${n} ${item.unit || ''}`.trim();
    }
    function expiryWord(item) {
        if (item.expiry_status === 'expired') return 'expired';
        const days = Math.round((new Date(`${item.expires}T00:00`) - new Date(`${todayISO}T00:00`)) / 86400000);
        return days <= 0 ? 'today' : days === 1 ? '1 day' : `${days} days`;
    }
    function itemRow(item, note, cls) {
        const row = el('div', 'item');
        row.appendChild(el('span', null, item.name));
        if (note) row.appendChild(el('span', `qty ${cls || ''}`.trim(), note));
        return row;
    }
    const byName = (a, b) => a.name.localeCompare(b.name);

    function renderHand(items) {
        const nodes = [];
        const atRisk = items.filter(i => i.expiry_status === 'expired' || i.expiry_status === 'soon').length;
        $('hand-label').textContent = atRisk ? `On hand · ${atRisk} use soon` : 'On hand';
        const soon = items.filter(i => i.expiry_status === 'expired' || i.expiry_status === 'soon')
            .sort((a, b) => a.expires.localeCompare(b.expires));
        if (soon.length) {
            nodes.push(el('div', 'grp soon', 'Use soon'));
            soon.forEach(i => nodes.push(itemRow(i, expiryWord(i), i.expiry_status === 'expired' ? 'expired' : '')));
        }
        const rest = items.filter(i => !soon.includes(i));
        const stock = rest.filter(i => i.source !== 'staple');
        PLACES.forEach(place => {
            const here = stock.filter(i => i.location === place).sort(byName);
            if (!here.length) return;
            nodes.push(el('div', 'grp', place));
            here.forEach(i => nodes.push(itemRow(i, amount(i))));
        });
        const staples = rest.filter(i => i.source === 'staple').sort(byName);
        if (staples.length) {
            const fold = el('details', 'staples');
            fold.appendChild(el('summary', null, `Staples · ${staples.length}`));
            staples.forEach(i => fold.appendChild(itemRow(i, amount(i))));
            nodes.push(fold);
        }
        if (!nodes.length) nodes.push(el('p', 'note', 'Nothing in the inventory yet.'));
        const foot = el('p', 'foot');
        const review = el('a', null, 'Review inventory');
        review.href = '/review';
        foot.appendChild(review);
        $('hand-body').replaceChildren(...nodes, foot);
    }

    async function loadHand() {
        try {
            renderHand(await getJSON('/api/inventory'));
        } catch (err) {
            failed($('hand-body'), 'Couldn’t load the inventory.', loadHand);
        }
    }

    // ---- could make ----
    function fillCookDays(chosen) {
        const pick = $('cook-day');
        const monday = mondayOf(state.week);
        const inWeek = todayISO >= iso(monday) && todayISO <= iso(addDays(monday, 6));
        const want = chosen || (inWeek ? todayISO : iso(monday));
        pick.replaceChildren();
        for (let i = 0; i < 7; i++) {
            const d = addDays(monday, i);
            const option = el('option', null, iso(d) === todayISO ? 'Today' : longDay.format(d));
            option.value = iso(d);
            option.selected = iso(d) === want;
            pick.appendChild(option);
        }
    }

    function openCook(date) {
        fillCookDays(date);
        $('cook-pop').showPopover();
    }

    async function plan(recipe, button) {
        button.disabled = true;
        try {
            await postJSON('/api/cooks', {
                recipe: recipe.recipe, week: state.week, scale: 1.0,
                servings_produced: recipe.servings || 4,
                date: $('cook-day').value, meal: 'dinner', initial_placement_count: 1,
            });
            $('cook-pop').hidePopover();
            refreshAll();
        } catch (err) {
            button.disabled = false;
            button.closest('.make').after(el('p', 'note bad', `Couldn’t add it. ${err.message}`));
        }
    }

    function renderCook(data) {
        // Meals only: a dessert you could bake is not an answer to "what's for dinner".
        const recipes = (data.recipes || []).filter(r => r.meal_tier === 'meal')
            .sort((a, b) => b.score - a.score).slice(0, 12);
        const nodes = recipes.map(r => {
            const row = el('div', 'make');
            const what = el('div', 'what');
            const name = el('a', null, r.recipe);
            name.href = `/recipe/${encodeURIComponent(r.recipe)}`;
            what.appendChild(name);
            const need = r.total - r.have;
            const why = el('span', 'why', need > 0 ? `Have ${r.have} of ${r.total}` : 'Have everything');
            if (r.minutes) why.append(` · ${r.minutes} min`);
            if (r.at_risk) { why.append(' · '); why.appendChild(el('span', 'risk', 'uses what expires')); }
            what.appendChild(why);
            row.appendChild(what);
            const add = el('button', 'act', 'Add');
            add.type = 'button';
            add.setAttribute('aria-label', `Add ${r.recipe}`);
            add.addEventListener('click', () => plan(r, add));
            row.appendChild(add);
            return row;
        });
        if (!nodes.length) nodes.push(el('p', 'note', 'Nothing matches what you have right now.'));
        const foot = el('p', 'foot');
        const more = el('a', null, 'All of Cook Now');
        more.href = '/cook-now';
        foot.appendChild(more);
        $('cook-body').replaceChildren(...nodes, foot);
    }

    async function loadCook() {
        try {
            renderCook(await getJSON('/api/cook-now?limit=12'));
        } catch (err) {
            failed($('cook-body'), 'Couldn’t load what you could make.', loadCook);
        }
    }
    // Ranking the whole library is the slowest read on this page, so it waits
    // until the sheet is opened rather than taxing every load.
    $('cook-pop').addEventListener('toggle', event => {
        if (event.newState !== 'open') return;
        if (!$('cook-day').options.length) fillCookDays();
        $('cook-body').replaceChildren(el('p', 'note', 'Checking what you have…'));
        loadCook();
    });
    $('cook-open').addEventListener('click', () => fillCookDays());

    let lastRefresh = 0;
    function refreshAll() {
        lastRefresh = Date.now();
        loadMeals();
        loadBuy();
        loadHand();
    }

    // A command changed something: redraw in place instead of letting the bar reload the page.
    document.addEventListener('kitchenos:changed', event => {
        event.preventDefault();
        refreshAll();
    });

    // Picking the iPad back up should show the truth without a tap. Throttled so
    // flicking between apps does not hammer the server.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && Date.now() - lastRefresh > 30000) refreshAll();
    });

    refreshAll();
})();

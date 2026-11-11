/* Saved packet text enters the DOM only through createElement/textContent.
   Cook timing has one writer: POST /api/cooks/<id>/schedule. */
(() => {
  'use strict';
  const main = document.getElementById('packet-main');
  if (!main) return;
  const week = main.dataset.week;
  const base = `/api/cooking-packets/${encodeURIComponent(week)}`;
  const content = document.getElementById('packet-content');
  const status = document.getElementById('packet-status');
  const error = document.getElementById('packet-error');
  const conflictActions = document.getElementById('conflict-actions');
  const forms = new Set();
  let packet = null;
  let sequence = 0;
  let mutationQueue = Promise.resolve();
  let conflict = false;
  const phases = {prep_or_flavor_base: 'Prep or flavor base', cook: 'Cook', finish_and_taste: 'Finish and taste', freeze_and_store: 'Freeze and store', reheat: 'Reheat', instructions: 'Instructions'};
  const stages = {bag_now: 'Put in the freezer bag now', prep_then_bag: 'Prep first, then bag', freeze_separately: 'Freeze separately', add_at_cook_time: 'Add when starting the Instant Pot', finish_after_cooking: 'Stir in after pressure release', serve_separately: 'Serve separately', needs_review: 'Needs placement review — keep out of the bag'};
  const bagRule = 'Only items listed under Put in the freezer bag now or Prep first, then bag belong in this bag.';
  function placement(row) { return Object.hasOwn(stages, row.prep_stage) && row.needs_review === false ? row.prep_stage : 'needs_review'; }
  const rows = value => Array.isArray(value) ? value.filter(row => row && typeof row === 'object' && !Array.isArray(row)).slice(0, 2000) : [];
  function text(value) {
    if (value == null) return '';
    if (Array.isArray(value)) return value.slice(0, 100).map(text).join('; ');
    if (typeof value === 'object') return Object.entries(value).slice(0, 30).map(([key, child]) => `${key}: ${text(child)}`).join('; ');
    return String(value);
  }
  function node(tag, value, className) {
    const element = document.createElement(tag);
    if (value != null) element.textContent = text(value);
    if (className) element.className = className;
    return element;
  }
  function name(row) { return text(row.text || row.display_name || row.recipe || row.item || row.ingredient || 'Untitled task'); }
  function safeURL(value) {
    if (typeof value !== 'string' || /[\x00-\x1f\x7f]/.test(value) || !/^https?:\/\//i.test(value)) return null;
    try { const url = new URL(value); return url.hostname && !url.username && !url.password ? url.href : null; } catch (_) { return null; }
  }
  function source(parent, url) {
    const safe = safeURL(url);
    if (!safe) return;
    const link = node('a', 'View source');
    link.href = safe;
    link.rel = 'noopener noreferrer';
    const p = node('p', null, 'source-line');
    p.append(link); parent.append(p);
  }
  function durationLabel(value) {
    const labels = {cook_schedule: 'Scheduled', recipe: 'Recipe timing', estimate: 'Estimated', estimated: 'Estimated', user: 'Your value'};
    return Object.hasOwn(labels, value) ? labels[value] : text(value);
  }
  function detail(parent, label, value, className = 'packet-meta') {
    if (value != null && value !== '') parent.append(node('p', `${label}${text(value)}`, className));
  }
  function dateLabel(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return text(value) || 'Date not set';
    const day = new Date(`${value}T12:00:00Z`);
    return new Intl.DateTimeFormat('en-US', {month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'}).format(day);
  }
  function metadata() {
    document.getElementById('packet-range').textContent = packet.date_range ? `${dateLabel(packet.date_range.start)} - ${dateLabel(packet.date_range.end)}` : 'Dates not set';
    document.getElementById('packet-meta').textContent = `${packet.status === 'reviewed' ? 'Reviewed' : 'Draft'} · Revision ${text(packet.revision)} · Generated ${text(packet.generated_at) || 'not recorded'}`;
  }
  async function request(url, method = 'GET', body) {
    const response = await fetch(url, {method, credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    let data = {};
    try { data = await response.json(); } catch (_) { /* A failed proxy response may not be JSON. */ }
    if (!response.ok) {
      const failure = new Error(response.status === 401 ? 'This browser is not authorized. Open KitchenOS through your usual authenticated address, then retry.' : response.status === 409 ? 'This packet changed in another session. Your text is still here. Load the latest revision, review your changes, then retry Save.' : text(data.error || data.message) || `Request failed (${response.status}). Please retry.`);
      failure.httpStatus = response.status;
      throw failure;
    }
    return data.packet || data;
  }
  function showError(failure) {
    error.textContent = failure.message;
    if (failure.httpStatus === 409) { conflict = true; conflictActions.hidden = false; }
  }
  function enqueue(action) {
    const result = mutationQueue.then(action);
    mutationQueue = result.catch(() => {});
    return result;
  }
  async function patch(changes, extra = {}) {
    if (conflict) throw new Error('Load the latest revision before you retry Save. Your edits are still here.');
    const saved = await request(base, 'PATCH', {expected_revision: packet.revision, changes, ...extra});
    packet = saved; metadata();
    return saved;
  }
  function disclosure(label, open = false) {
    const section = node('details', null, 'packet-disclosure');
    section.open = open;
    section.dataset.section = label;
    const summary = node('summary'); summary.append(node('h2', label));
    const body = node('div', null, 'disclosure-body'); section.append(summary, body); content.append(section);
    return body;
  }
  function notes(parent, row) {
    for (const key of ['notes', 'warning', 'review_reason']) detail(parent, '', row[key], 'packet-note');
    if (row.needs_review) detail(parent, '', 'Needs review', 'review-flag');
  }
  function checkbox(parent, row, title) {
    if (!row.item_id) return;
    const label = node('label', null, 'check-label');
    const input = node('input'); input.type = 'checkbox'; input.checked = row.done === true;
    input.id = `packet-check-${++sequence}`;
    label.htmlFor = input.id; label.append(input, node('span', `Done: ${title}`)); parent.append(label);
    input.addEventListener('change', () => {
      const checked = input.checked;
      input.disabled = true;
      enqueue(async () => {
        try { await patch([{item_id: row.item_id, field: 'done', value: checked}]); row.done = checked; status.textContent = 'Saved checkbox.'; error.textContent = ''; }
        catch (failure) { input.checked = row.done === true; showError(failure); }
        finally { input.disabled = false; }
      });
    });
  }
  function field(grid, title, key, value, kind = 'text', options = {}) {
    const wrapper = node('div', null, `field${kind === 'textarea' ? ' field-wide' : ''}`);
    const input = node(kind === 'textarea' ? 'textarea' : kind === 'select' ? 'select' : 'input');
    if (!['textarea', 'select'].includes(kind)) input.type = kind;
    input.id = `packet-field-${++sequence}`; input.name = key;
    if (kind === 'select') {
      for (const choice of options.choices || []) { const opt = node('option', choice.label || choice); opt.value = choice.value || choice; input.append(opt); }
    }
    input.value = text(value); input.dataset.baseline = input.value;
    if (options.min != null) input.min = options.min;
    if (options.max != null) input.max = options.max;
    if (options.step != null) input.step = options.step;
    input.maxLength = 10000;
    if (kind === 'number') input.inputMode = 'decimal';
    const label = node('label', title); label.htmlFor = input.id;
    const issue = node('p', '', 'form-error'); issue.id = `${input.id}-error`; issue.setAttribute('role', 'alert');
    wrapper.append(label, input, issue); grid.append(wrapper);
    return input;
  }
  function validate(form) {
    let first = null;
    for (const control of form.querySelectorAll('input:not([type=checkbox]),textarea,select')) {
      const issue = document.getElementById(`${control.id}-error`);
      control.removeAttribute('aria-invalid'); control.removeAttribute('aria-describedby'); issue.textContent = '';
      control.setCustomValidity('');
      if (control.name === 'timezone' && control.value) {
        try { new Intl.DateTimeFormat('en-US', {timeZone: control.value}); }
        catch (_) { control.setCustomValidity('Enter a valid IANA timezone, such as America/Chicago.'); }
      }
      if (!control.checkValidity()) {
        control.setAttribute('aria-invalid', 'true'); control.setAttribute('aria-describedby', issue.id);
        issue.textContent = control.validationMessage || 'Check this value.';
        first ||= control;
      }
    }
    if (first) { first.focus(); return false; }
    return true;
  }
  function editRow(parent, row, {title = name(row), heading = true, fields = ['text', 'notes'], ledger = false} = {}) {
    const article = node('article', null, 'packet-row');
    if (heading) article.append(node('h3', title));
    notes(article, row);
    checkbox(article, row, title);
    if (!row.item_id) { parent.append(article); return article; }
    const form = node('form'); form.noValidate = true; form.dataset.itemId = row.item_id;
    forms.add(form);
    const grid = node('div', null, 'field-grid'); form.append(grid);
    const controls = new Map();
    for (const key of fields) {
      const labels = {text: 'Task text', notes: 'Notes', amount: 'Quantity', quantity: 'Quantity', unit: 'Unit', date: 'Date', time: 'Start time', start: 'Start timestamp', duration_minutes: 'Duration in minutes', timezone: 'Timezone', servings_to_eat: 'Servings to eat', meal: 'Meal', phase: 'Phase'};
      let value = row[key] ?? '';
      let kind = ['text', 'notes'].includes(key) ? 'textarea' : key === 'date' ? 'date' : key === 'time' ? 'time' : ['duration_minutes', 'servings_to_eat'].includes(key) ? 'number' : ['meal', 'phase'].includes(key) ? 'select' : 'text';
      const opts = {};
      if (key === 'duration_minutes') Object.assign(opts, {min: ledger ? 15 : 1, max: ledger ? 360 : 1440, step: ledger ? 15 : 1});
      if (key === 'servings_to_eat') Object.assign(opts, {min: .01, step: 'any'});
      if (key === 'time' && ledger) { value = (row.start || '').slice(11, 16); opts.step = 900; }
      if (key === 'meal') opts.choices = ['breakfast', 'lunch', 'dinner', 'snack'];
      if (key === 'phase') opts.choices = Object.entries(phases).map(([value, label]) => ({value, label}));
      const control = field(grid, `${labels[key]}: ${title}`, key, value, kind, opts);
      if (ledger) control.required = true;
      controls.set(key, control);
    }
    const save = node('button', `Save ${title}`); save.type = 'submit'; form.append(save);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!validate(form)) return;
      const changes = [];
      for (const [key, control] of controls) {
        if (control.value !== control.dataset.baseline) changes.push({item_id: row.item_id, field: key, value: ['duration_minutes', 'servings_to_eat'].includes(key) ? Number(control.value) : control.value});
      }
      if (!ledger && !changes.length) { status.textContent = 'No changes to save.'; return; }
      // Capture values before queuing so typing while another request finishes is retained.
      const submitted = Object.fromEntries([...controls].map(([key, control]) => [key, control.value]));
      enqueue(async () => {
        save.disabled = true; save.setAttribute('aria-busy', 'true');
        try {
          if (ledger) {
            const body = {date: submitted.date, meal: submitted.meal, start: zonedStart(submitted.date, submitted.time, submitted.timezone, row.start), timezone: submitted.timezone, duration_minutes: Number(submitted.duration_minutes), servings_to_eat: Number(submitted.servings_to_eat)};
            await request(`/api/cooks/${encodeURIComponent(row.cook_id)}/schedule`, 'POST', body);
            status.textContent = 'Saved cook schedule. Refresh from week to update the packet timeline.';
          } else { await patch(changes); status.textContent = 'Saved packet changes.'; }
          for (const [key, control] of controls) { control.dataset.baseline = submitted[key]; row[key] = ['duration_minutes', 'servings_to_eat'].includes(key) ? Number(submitted[key]) : submitted[key]; }
          error.textContent = '';
        } catch (failure) { showError(failure); }
        finally { save.disabled = false; save.removeAttribute('aria-busy'); }
      });
    });
    article.append(form); parent.append(article); return article;
  }
  function placementEditor(parent, row) {
    const entry = node('li', null, 'freezer-ingredient'); entry.dataset.ingredientId = text(row.item_id);
    entry.append(node('p', `${text(row.amount)} ${text(row.unit)} ${name(row)}`, 'ingredient-name'));
    detail(entry, '', row.stage_reason, 'packet-note'); notes(entry, row);
    if (!row.item_id) { detail(entry, '', 'Placement cannot be saved until this ingredient has a stable identity.', 'review-flag'); parent.append(entry); return; }
    const form = node('form', null, 'placement-form'); form.noValidate = true; form.dataset.itemId = row.item_id; forms.add(form);
    const grid = node('div', null, 'field-grid'); form.append(grid);
    const control = field(grid, `Prep stage: ${name(row)}`, 'prep_stage', Object.hasOwn(stages, row.prep_stage) ? row.prep_stage : 'needs_review', 'select', {choices: Object.entries(stages).map(([value, label]) => ({value, label}))});
    control.required = true;
    if (placement(row) === 'needs_review') form.append(node('p', 'Saving confirms your chosen placement. Suggested placement is not confirmed yet.', 'review-flag'));
    const save = node('button', 'Save placement'); save.type = 'submit'; form.append(save);
    form.addEventListener('submit', event => {
      event.preventDefault(); if (!validate(form)) return;
      // Always send this explicit confirmation, even when a model's suggested
      // value is unchanged. Only the repository can make placement confirmed.
      const value = control.value;
      enqueue(async () => {
        save.disabled = true; save.setAttribute('aria-busy', 'true');
        try {
          await patch([{item_id: row.item_id, field: 'prep_stage', value}]);
          control.dataset.baseline = value;
          render(packet, true);
          const replacement = [...forms].find(form => form.dataset.itemId === row.item_id)?.querySelector('select[name="prep_stage"]');
          if (replacement) replacement.focus({preventScroll: true});
          status.textContent = `Saved placement: ${stages[value]}.`; error.textContent = '';
        } catch (failure) { showError(failure); }
        finally { save.disabled = false; save.removeAttribute('aria-busy'); }
      });
    });
    entry.append(form); parent.append(entry);
  }
  function freezerPrep(parent, card) {
    const grouped = new Map(Object.keys(stages).map(stage => [stage, []]));
    for (const row of rows(card.ingredients)) grouped.get(placement(row)).push(row);
    const freezer = node('section', null, 'freezer-prep'); freezer.append(node('h4', 'Freezer prep'), node('p', bagRule, 'bag-rule'));
    function group(stage, target) {
      const ingredients = grouped.get(stage); if (!ingredients.length) return;
      const section = node('section', null, 'placement-group'); section.dataset.prepStage = stage;
      section.append(node('h5', stages[stage])); const list = node('ul', null, 'ingredient-list');
      for (const ingredient of ingredients) placementEditor(list, ingredient);
      section.append(list); target.append(section);
    }
    group('bag_now', freezer); group('prep_then_bag', freezer);
    if (!grouped.get('bag_now').length && !grouped.get('prep_then_bag').length) freezer.append(node('p', 'No ingredients are confirmed for this freezer bag yet.', 'review-flag'));
    parent.append(freezer);
    if ([...grouped].some(([stage, ingredients]) => !['bag_now', 'prep_then_bag'].includes(stage) && ingredients.length)) {
      const excluded = node('section', null, 'keep-out'); excluded.append(node('h4', 'Keep out of the freezer bag'));
      for (const stage of Object.keys(stages)) if (!['bag_now', 'prep_then_bag'].includes(stage)) group(stage, excluded);
      parent.append(excluded);
    }
  }
  function pullGroups() {
    const ingredients = new Map(rows(packet.recipe_cards).flatMap(card => rows(card.ingredients)).map(row => [row.item_id, row]));
    const grouped = new Map([['Pull for freezer prep', []], ['Keep for cook day', []]]); const seen = new Set();
    for (const row of [...rows(packet.pull_list), ...rows(packet.cook_day_pull)]) {
      const identity = text(row.item_id) || JSON.stringify(row); if (seen.has(identity)) continue; seen.add(identity);
      const mapped = Array.isArray(row.source_ingredient_ids) ? row.source_ingredient_ids.map(id => ingredients.get(id)) : [];
      const effective = new Set(mapped.filter(Boolean).map(placement));
      const review = !mapped.length || !mapped.every(Boolean) || effective.has('needs_review') || row.needs_review === true;
      const freezer = !review && [...effective].every(stage => ['bag_now', 'prep_then_bag', 'freeze_separately'].includes(stage));
      const destination = review ? stages.needs_review : Object.keys(stages).filter(stage => effective.has(stage)).map(stage => stages[stage]).join('; ');
      grouped.get(freezer ? 'Pull for freezer prep' : 'Keep for cook day').push({row, destination});
    }
    return grouped;
  }
  // Convert an explicit wall time in the selected IANA zone into the required
  // offset-aware ISO timestamp. Never use the browser's own timezone implicitly.
  function zonedStart(day, time, zone, previous) {
    const wall = `${day}T${time}:00`;
    const target = Date.parse(`${wall}Z`);
    const format = new Intl.DateTimeFormat('en-CA', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
    function offset(at) {
      const parts = Object.fromEntries(format.formatToParts(new Date(at)).map(part => [part.type, part.value]));
      return Date.parse(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}Z`) - at;
    }
    const candidates = [offset(target), offset(target - 86400000), offset(target + 86400000)];
    const prior = typeof previous === 'string' ? previous.match(/([+-])(\d\d):(\d\d)$/) : null;
    if (prior) candidates.unshift((prior[1] === '-' ? -1 : 1) * (Number(prior[2]) * 60 + Number(prior[3])) * 60000);
    for (const delta of [...new Set(candidates)]) {
      if (offset(target - delta) !== delta) continue;
      const minutes = Math.abs(delta / 60000);
      return `${wall}${delta < 0 ? '-' : '+'}${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
    }
    throw new Error('This start time does not exist in the selected timezone. Choose another time.');
  }
  function captureDrafts() {
    const drafts = new Map();
    for (const form of forms) {
      const values = {};
      for (const control of form.querySelectorAll('input,textarea,select')) if (control.value !== control.dataset.baseline) values[control.name] = control.value;
      if (Object.keys(values).length) drafts.set(form.dataset.itemId, values);
    }
    return drafts;
  }
  function render(saved, keepDrafts = false) {
    const drafts = keepDrafts ? captureDrafts() : new Map();
    const open = new Set([...content.querySelectorAll('details[open]')].map(section => section.dataset.section));
    packet = saved; metadata(); content.replaceChildren(); forms.clear();
    const schedule = disclosure('Weekly schedule', true);
    const scheduleRows = rows(packet.production_schedule);
    const scheduledIds = new Set(scheduleRows.filter(row => row.source === 'cook_schedule').map(row => row.cook_id));
    for (const cook of rows(packet.cooks)) {
      const cookId = cook.cook_id ?? cook.id;
      if (!scheduledIds.has(cookId) && !cook.cooked_at && !cook.bundle_id) scheduleRows.push({...cook, cook_id: cookId, source: 'cook', timezone: cook.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone, meal: cook.meal || 'dinner', done: false});
    }
    if (!scheduleRows.length) detail(schedule, '', 'No scheduled tasks. Add a cook time, then refresh from week.');
    const timeline = node('table', null, 'production-table');
    timeline.append(node('caption', 'Weekly production timeline', 'packet-visually-hidden'));
    const head = node('thead'); const headings = node('tr');
    for (const title of ['Day / start', 'Production task', 'Duration']) { const th = node('th', title); th.scope = 'col'; headings.append(th); }
    head.append(headings); timeline.append(head);
    const body = node('tbody');
    for (const row of scheduleRows) {
      const tr = node('tr'); const day = node('th', dateLabel(row.date)); day.scope = 'row';
      if (row.start || row.time) day.append(node('span', text(row.time || row.start?.slice(11, 16)), 'packet-meta'));
      const task = node('td', name(row)); task.append(node('span', ['cook', 'cook_schedule'].includes(row.source) ? 'Cook schedule' : 'Packet prep', 'packet-meta'));
      const duration = node('td', row.duration_minutes == null ? 'Unknown' : `${row.duration_minutes} min`, 'numeric');
      tr.append(day, task, duration); body.append(tr);
    }
    timeline.append(body); if (scheduleRows.length) schedule.append(timeline);
    const editor = node('details', null, 'packet-editor'); editor.dataset.section = 'Schedule editor';
    editor.append(node('summary', 'Edit schedule details')); schedule.append(editor);
    for (const row of scheduleRows) {
      const ledger = ['cook_schedule', 'cook'].includes(row.source) && Number.isInteger(row.cook_id);
      const title = name(row);
      const block = node('div');
      detail(block, '', `${dateLabel(row.date)} · ${row.duration_minutes == null ? 'Duration unknown' : `${row.duration_minutes} min`}`);
      detail(block, '', `${ledger ? 'Cook schedule' : 'Packet prep'}${row.duration_source ? ` · Duration: ${durationLabel(row.duration_source)}` : ''}`);
      if (ledger) {
        const cook = rows(packet.cooks).find(cook => cook.cook_id === row.cook_id || cook.id === row.cook_id);
        const count = rows(cook?.placements).filter(placement => placement.date === row.date && placement.meal === row.meal).reduce((total, placement) => total + Number(placement.count || 0), 0);
        editRow(block, {...row, servings_to_eat: row.servings_to_eat || count || 1}, {title, ledger: true, fields: ['date', 'meal', 'time', 'timezone', 'duration_minutes', 'servings_to_eat']});
      } else editRow(block, row, {title, fields: ['text', 'date', 'time', 'duration_minutes', 'notes']});
      editor.append(block);
    }
    for (const [title, pulls] of pullGroups()) {
      if (!pulls.length) continue;
      const home = disclosure(title);
      const groups = new Map();
      for (const pull of pulls) { const location = text(pull.row.location) || 'Location not recorded'; if (!groups.has(location)) groups.set(location, []); groups.get(location).push(pull); }
      for (const [location, items] of groups) {
        const group = node('section'); group.append(node('h3', location));
        for (const {row, destination} of items) {
          const block = node('article', null, 'packet-row');
          detail(block, '', name(row), 'ingredient-name');
          const requirement = rows(packet.shopping_list).find(line => line.item_id === row.line_id)?.needed;
          if (requirement) detail(block, 'Required: ', `${text(requirement.amount)} ${text(requirement.unit)}`);
          detail(block, '', `Credited from home: ${text(row.amount)} ${text(row.unit)}${row.location_uncertain ? ' · Location unsure' : ''}`);
          detail(block, 'Destination: ', destination, 'pull-destination'); detail(block, '', row.stage_reason, 'packet-note');
          // Pull destination follows its source ingredient; never edit it here.
          editRow(block, row, {fields: ['amount', 'unit', 'notes'], heading: false}); group.append(block);
        }
        home.append(group);
      }
    }
    const shopping = rows(packet.shopping_list).filter(row => row.to_buy);
    if (shopping.length) {
      const buy = disclosure('Shopping for the complete meal');
      detail(buy, '', 'Complete-meal shopping covers every ingredient stage; use Pull for freezer prep for today’s session.', 'packet-note');
      for (const row of shopping) {
        const editable = {...row, text: row.text ?? row.item, amount: row.amount ?? row.quantity ?? row.to_buy.amount, unit: row.unit ?? row.to_buy.unit};
        detail(buy, '', `${name(row)} · Buy ${text(editable.amount)} ${text(editable.unit)}`);
        // Sparse amount/unit/text overrides stay on the requirement item. The
        // derived nested to_buy document is never patched or independently keyed.
        editRow(buy, editable, {title: name(row), fields: ['text', 'amount', 'unit', 'notes'], heading: false});
      }
    }
    const snapshot = packet.store_snapshot || {};
    for (const [retailer, label] of [['heb', 'Buy at H-E-B'], ['costco', 'Consider at Costco']]) {
      const picks = rows(snapshot.recommendations).filter(row => row.retailer === retailer);
      if (!picks.length) continue;
      const store = disclosure(label);
      for (const pick of picks) {
        const block = node('article', null, 'packet-row');
        block.append(node('h3', pick.product_name || 'No verified product'));
        detail(block, 'For: ', pick.ingredient);
        detail(block, '', `${text(pick.brand)} · ${text(pick.package)}`);
        detail(block, '', pick.display_price || pick.price || 'Price unknown');
        detail(block, '', pick.status || 'Availability unverified');
        detail(block, '', pick.evidence || 'No comparison evidence');
        detail(block, 'Checked: ', pick.checked_at || 'time not recorded'); notes(block, pick); source(block, pick.url); store.append(block);
      }
    }
    const prep = rows(packet.shared_prep);
    if (prep.length) {
      const shared = disclosure('Shared prep');
      for (const row of prep) {
        detail(shared, 'For: ', row.recipes);
        for (const contribution of rows(row.contributions)) {
          const line = node('p', null, 'source-line'); const link = node('a', contribution.recipe);
          link.href = `/recipe/${encodeURIComponent(text(contribution.recipe))}`;
          line.append(link, node('span', `: ${text(contribution.amount)} ${text(contribution.unit)}`)); shared.append(line);
        }
        editRow(shared, row, {fields: ['text', 'amount', 'unit', 'notes']});
      }
    }
    const cards = rows(packet.recipe_cards);
    if (cards.length) {
      const recipes = disclosure('Recipe cards');
      for (const card of cards) {
        const section = node('section', null, 'packet-row'); section.append(node('h3', card.display_name || card.recipe));
        detail(section, 'Batch multiplier: ', card.scale); detail(section, 'Equipment: ', card.equipment); notes(section, card);
        freezerPrep(section, card);
        const directions = node('section', null, 'cook-day-directions'); directions.append(node('h4', 'Cook-day directions')); section.append(directions);
        const effectivePhases = {};
        for (const [original, instructions] of Object.entries(card.instruction_phases || {})) for (const instruction of rows(instructions)) {
          const phase = Object.hasOwn(phases, instruction.phase) ? instruction.phase : original;
          if (Object.hasOwn(phases, phase)) (effectivePhases[phase] ||= []).push(instruction);
        }
        for (const [phase, label] of Object.entries(phases)) {
          const instructions = effectivePhases[phase] || [];
          if (!instructions.length) continue;
          const block = node('section', null, 'recipe-phase'); block.append(node('h5', label));
          for (const instruction of instructions) editRow(block, {...instruction, phase: instruction.phase || phase}, {heading: false, fields: ['text', 'phase', 'notes']});
          directions.append(block);
        }
        source(section, card.source_url); recipes.append(section);
      }
    }
    const storage = rows(packet.freeze_reheat);
    if (storage.length) {
      const freeze = disclosure('Freeze and reheat');
      for (const row of storage) { detail(freeze, 'For: ', row.recipe); editRow(freeze, row); }
    }
    if (rows(packet.warnings).length || rows(packet.needs_review).length) {
      const review = disclosure('Needs review', true);
      for (const row of rows(packet.warnings)) { const block = node('article', null, 'packet-row utility'); detail(block, '', name(row)); notes(block, row); review.append(block); }
      for (const row of rows(packet.needs_review)) { const block = node('article', null, 'packet-row utility'); detail(block, '', row.reason || 'Source changed'); detail(block, '', `${text(row.item_id)} · ${text(row.field)}: ${text(row.value)}`); review.append(block); }
    }
    const retailers = snapshot.retailers;
    if (retailers && typeof retailers === 'object') {
      const locations = disclosure('Locations used');
      for (const [key, place] of Object.entries(retailers).slice(0, 20)) {
        if (!place || typeof place !== 'object') continue;
        const block = node('article', null, 'packet-row'); block.append(node('h3', place.display_name || place.display || key));
        detail(block, '', place.location || place.address); detail(block, '', `${place.stale ? 'Stale · ' : ''}Checked ${text(place.checked_at || place.timestamp) || 'time not recorded'}`);
        detail(block, '', place.error, 'review-flag'); notes(block, place); locations.append(block);
      }
    }
    for (const section of content.querySelectorAll('details')) if (open.has(section.dataset.section)) section.open = true;
    for (const form of forms) for (const [key, value] of Object.entries(drafts.get(form.dataset.itemId) || {})) {
      const control = [...form.elements].find(control => control.name === key); if (control) control.value = value;
    }
  }
  async function load(keepDrafts = false) {
    const saved = await request(base);
    if (!saved || !saved.version) throw new Error('No cooking packet saved yet. Select Refresh from week to build one.');
    render(saved, keepDrafts); conflict = false; conflictActions.hidden = true;
  }
  async function refresh(kind, button) {
    button.disabled = true; button.setAttribute('aria-busy', 'true');
    const path = kind === 'stores' ? `${base}/store-picks/refresh` : `${base}/refresh`;
    try {
      status.textContent = kind === 'stores' ? 'Refreshing store picks…' : 'Building cooking packet…';
      const started = await request(path, 'POST', {request_id: `${Date.now()}-${Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-')}`});
      const operation = started.operation_id || started.id;
      if (!operation) throw new Error('Refresh could not start. Please retry.');
      const deadline = Date.now() + 180000;
      while (Date.now() < deadline) {
        const progress = await request(`${path}/${encodeURIComponent(operation)}`);
        if (progress.status === 'complete' || progress.state === 'complete') { await load(true); status.textContent = 'Saved refreshed packet. Your unsaved text is still available.'; error.textContent = ''; return; }
        if (progress.status === 'failed' || progress.state === 'failed') throw new Error(text(progress.error) || 'Refresh failed. The previous saved packet is still available.');
        status.textContent = `${kind === 'stores' ? 'Refreshing store picks' : 'Building cooking packet'}…${progress.retailers ? ` ${text(progress.retailers)}` : ''}`;
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
      throw new Error('Refresh is taking longer than expected. Reload to check the saved packet or retry the refresh.');
    } catch (failure) { showError(failure); }
    finally { button.disabled = false; button.removeAttribute('aria-busy'); }
  }
  document.getElementById('refresh-week').addEventListener('click', event => { const button = event.currentTarget; enqueue(() => refresh('week', button)); });
  document.getElementById('refresh-stores').addEventListener('click', event => { const button = event.currentTarget; enqueue(() => refresh('stores', button)); });
  document.getElementById('mark-reviewed').addEventListener('click', event => {
    const button = event.currentTarget;
    enqueue(async () => {
      button.disabled = true; button.setAttribute('aria-busy', 'true');
      try { await patch([], {status: 'reviewed'}); status.textContent = 'Marked reviewed.'; error.textContent = ''; }
      catch (failure) { showError(failure); }
      finally { button.disabled = false; button.removeAttribute('aria-busy'); }
    });
  });
  document.getElementById('load-latest').addEventListener('click', () => enqueue(async () => {
    try { packet = await request(base); metadata(); conflict = false; conflictActions.hidden = true; error.textContent = ''; status.textContent = 'Latest revision loaded. Your text is still here; review it, then retry Save.'; }
    catch (failure) { showError(failure); }
  }));
  if (!/^\d{4}-W\d{2}$/.test(week || '')) { error.textContent = 'Choose a valid week from Plan your week.'; return; }
  load().catch(failure => { showError(failure); });
})();

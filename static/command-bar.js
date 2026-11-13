/* The "tell it" bar: say what you want, see it done, Undo.
 *
 * A thin client of POST /api/command (docs/API.md). It sends the sentence plus
 * whatever the page says is on screen (window.kitchenosContext), and draws the
 * four responses. It decides nothing, builds no URLs, and never uses innerHTML
 * for server text.
 */
(() => {
  if (document.getElementById('ko-tell-button')) return;

  const el = (tag, attrs = {}, text) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const button = (id, label, primary, cls) => {
    const b = el('button', {type: 'button', class: 'ko-tell-btn' + (primary ? ' primary' : '') + (cls ? ' ' + cls : '')}, label);
    if (id) b.id = id;
    return b;
  };

  const fab = el('button', {id: 'ko-tell-button', type: 'button', 'aria-label': 'Tell KitchenOS',
                            'aria-haspopup': 'dialog', 'aria-expanded': 'false'}, '🎙️');
  const backdrop = el('div', {id: 'ko-tell-backdrop', hidden: ''});
  const sheet = el('div', {id: 'ko-tell-sheet', role: 'dialog', 'aria-modal': 'true',
                           'aria-label': 'Tell KitchenOS', hidden: ''});
  const form = el('form', {class: 'ko-tell-row'});
  const input = el('input', {id: 'ko-tell-input', type: 'text', autocomplete: 'off',
                             enterkeyhint: 'send', 'aria-label': 'What do you want to do?',
                             placeholder: 'Put this on Wednesday…'});
  const send = button('ko-tell-send', 'Send', true);
  send.type = 'submit';
  const closeBtn = el('button', {id: 'ko-tell-close', type: 'button', class: 'ko-tell-btn',
                                 'aria-label': 'Close'}, '✕');
  const result = el('div', {id: 'ko-tell-result', 'aria-live': 'polite'});
  form.append(input, send, closeBtn);
  sheet.append(form, result);
  document.body.append(fab, backdrop, sheet);

  let busy = false;
  // Set when a change happened on a page that can't refresh itself. The reload
  // waits for the sheet to close so the Done card and its Undo stay visible.
  let reloadOnClose = false;
  // Bumped on every close, so a response that lands after its sheet closed is
  // recognised as late rather than drawn into a sheet the user dismissed.
  let generation = 0;

  const context = () => {
    try {
      const ctx = typeof window.kitchenosContext === 'function' ? window.kitchenosContext() : null;
      return ctx && typeof ctx === 'object' ? ctx : {screen: 'other'};
    } catch (_) {
      return {screen: 'other'};
    }
  };

  const setBusy = (on) => {
    busy = on;
    input.disabled = on;
    sheet.querySelectorAll('button:not(#ko-tell-close)').forEach(b => { b.disabled = on; });
    if (on) result.setAttribute('aria-busy', 'true');
    else result.removeAttribute('aria-busy');
  };

  const show = (...nodes) => { result.replaceChildren(...nodes); };
  const lines = (items, cls) => {
    const ul = el('ul');
    for (const line of items || []) ul.append(el('li', cls ? {class: cls} : {}, line));
    return ul;
  };
  // Focus something that survives the redraw: the first new action, else the field.
  const focusResult = () => { (result.querySelector('button') || input).focus(); };

  // Never rejects. `transport: true` marks failures where the server never
  // answered (network, 5xx, 401), as opposed to a reply that said no.
  async function call(path, body) {
    const unreachable = {status: 'failed', transport: true,
                         reason: "Couldn't reach KitchenOS — nothing was changed."};
    let resp;
    try {
      resp = await fetch(path, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    } catch (_) {
      return unreachable;
    }
    if (resp.status === 401) {
      return {status: 'failed', transport: true, reason: 'Session expired — reopen this page from the app.'};
    }
    let data = null;
    try { data = await resp.json(); } catch (_) { /* fall through */ }
    if (resp.status >= 500 || !data) return unreachable;
    if (data.error) return {status: 'failed', reason: data.error};
    return data;
  }

  // Cancelable: a page that refreshes itself in place calls preventDefault().
  const announce = (data) => window.dispatchEvent(
    new CustomEvent('kitchenos:changed', {detail: data, cancelable: true}));
  const isChange = (data) => data.status === 'done' || data.status === 'undone';

  function render(data) {
    if (data.status === 'done') {
      const nodes = [lines(data.lines)];
      if (data.warnings && data.warnings.length) nodes.push(lines(data.warnings.map(String), 'ko-tell-warning'));
      const actions = el('div', {class: 'ko-tell-actions'});
      if (data.undo) {
        const undo = button('ko-tell-undo', 'Undo');
        undo.addEventListener('click', () => runUndo(data.command_id));
        actions.append(undo);
      }
      nodes.push(actions);
      show(...nodes);
      input.value = '';
      const href = typeof data.href === 'string' ? data.href : null;
      if (href && href.startsWith('/') && !href.startsWith('//')) location.assign(href);
      else reloadOnClose = announce(data);  // true = nobody refreshed in place
      return;
    }
    if (data.status === 'undone') {
      show(el('p', {}, 'Undone.'));
      reloadOnClose = announce(data);
      return;
    }
    if (data.status === 'ask') {
      const actions = el('div', {class: 'ko-tell-actions'});
      for (const opt of data.options || []) {
        const b = button(null, opt.label, false, 'ko-tell-option');
        b.addEventListener('click', () => run(`/api/command/${data.command_id}/answer`, {option: opt.id}));
        actions.append(b);
      }
      show(el('p', {}, data.question), actions);
      return;
    }
    if (data.status === 'confirm') {
      const yes = button('ko-tell-confirm', 'Do it', true);
      const no = button('ko-tell-cancel', 'Cancel');
      yes.addEventListener('click', () => run(`/api/command/${data.command_id}/answer`, {confirm: true}));
      no.addEventListener('click', () => {
        if (busy) return;
        setBusy(true);
        closeSheet();
        call(`/api/command/${data.command_id}/answer`, {confirm: false});  // fire and forget
      });
      const actions = el('div', {class: 'ko-tell-actions'});
      actions.append(yes, no);
      show(lines(data.lines), actions);
      return;
    }
    // failed, refused, or anything unexpected: say why, keep the sentence.
    show(el('p', {}, data.reason || 'That didn’t work — nothing was changed.'));
  }

  // One request in flight. Returns the response, or null if the sheet closed
  // meanwhile — a late change still refreshes the page, anything else is dropped.
  async function request(path, body) {
    if (busy) return null;
    const mine = generation;
    setBusy(true);
    const data = await call(path, body);
    if (mine !== generation) {
      if (isChange(data) && announce(data)) location.reload();
      return null;
    }
    setBusy(false);
    return data;
  }

  async function run(path, body) {
    const data = await request(path, body);
    if (!data) return;
    render(data);
    focusResult();
  }

  // Undo keeps its Done card when the server never answered, so it can be retried.
  // A reply (refused, or nothing to undo) is final and replaces the card.
  async function runUndo(commandId) {
    const data = await request(`/api/command/${commandId}/undo`);
    if (!data) return;
    if (data.status === 'failed' && data.transport) {
      const old = result.querySelector('.ko-tell-error');
      if (old) old.remove();
      result.append(el('p', {class: 'ko-tell-warning ko-tell-error'}, data.reason));
    } else {
      render(data);
    }
    focusResult();
  }

  const onKeydown = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); closeSheet(); return; }
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll('input:not([disabled]), button:not([disabled])')];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    const inside = sheet.contains(document.activeElement);
    if (e.shiftKey && (!inside || document.activeElement === first)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (!inside || document.activeElement === last)) { e.preventDefault(); first.focus(); }
  };

  function open() {
    result.replaceChildren();
    sheet.hidden = false;
    backdrop.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    document.addEventListener('keydown', onKeydown);
    if (window.visualViewport) fit();
    input.focus();
    call('/api/command/warm');  // fire and forget
  }
  function closeSheet() {
    generation += 1;
    setBusy(false);
    document.removeEventListener('keydown', onKeydown);
    sheet.hidden = true;
    backdrop.hidden = true;
    result.replaceChildren();
    fab.setAttribute('aria-expanded', 'false');
    if (reloadOnClose) { reloadOnClose = false; location.reload(); return; }
    fab.focus();
  }

  fab.addEventListener('click', open);
  closeBtn.addEventListener('click', closeSheet);
  backdrop.addEventListener('click', closeSheet);
  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    run('/api/command', {text, context: context()});
  });

  // Keep the sheet above the on-screen keyboard and within what is still visible.
  function fit() {
    const vv = window.visualViewport;
    const gap = window.innerHeight - vv.height - vv.offsetTop;
    sheet.style.bottom = Math.max(0, gap) + 'px';
    sheet.style.maxHeight = Math.floor(vv.height * 0.9) + 'px';
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', fit);
    window.visualViewport.addEventListener('scroll', fit);
  }
})();

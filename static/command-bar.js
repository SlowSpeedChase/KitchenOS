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
  const close = button('ko-tell-close', 'Close');
  close.setAttribute('aria-label', 'Close');
  close.textContent = '✕';
  const result = el('div', {id: 'ko-tell-result', 'aria-live': 'polite'});
  form.append(input, send, close);
  sheet.append(form, result);
  document.body.append(fab, backdrop, sheet);

  let busy = false;
  // Set when a change happened on a page that can't refresh itself. The reload
  // waits for the sheet to close so the Done card and its Undo stay visible.
  let reloadOnClose = false;

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
    sheet.querySelectorAll('button:not(#ko-tell-close)').forEach(b => { b.disabled = on; });
  };

  const show = (...nodes) => { result.replaceChildren(...nodes); };
  const lines = (items, cls) => {
    const ul = el('ul');
    for (const line of items || []) ul.append(el('li', cls ? {class: cls} : {}, line));
    return ul;
  };

  async function call(path, body) {
    let resp;
    try {
      resp = await fetch(path, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    } catch (_) {
      return {status: 'failed', reason: "Couldn't reach KitchenOS — nothing was changed."};
    }
    if (resp.status === 401) return {status: 'failed', reason: 'Session expired — reopen this page from the app.'};
    let data = null;
    try { data = await resp.json(); } catch (_) { /* fall through */ }
    if (resp.status >= 500 || !data) return {status: 'failed', reason: "Couldn't reach KitchenOS — nothing was changed."};
    if (data.error) return {status: 'failed', reason: data.error};
    return data;
  }

  function changed(data) {
    const event = new CustomEvent('kitchenos:changed', {detail: data, cancelable: true});
    reloadOnClose = window.dispatchEvent(event);  // true = nobody refreshed in place
  }

  function render(data) {
    if (data.status === 'done') {
      const nodes = [lines(data.lines)];
      if (data.warnings && data.warnings.length) nodes.push(lines(data.warnings.map(String), 'ko-tell-warning'));
      const actions = el('div', {class: 'ko-tell-actions'});
      if (data.undo) {
        const undo = button('ko-tell-undo', 'Undo');
        undo.addEventListener('click', () => run(`/api/command/${data.command_id}/undo`));
        actions.append(undo);
      }
      nodes.push(actions);
      show(...nodes);
      input.value = '';
      const href = typeof data.href === 'string' ? data.href : null;
      if (href && href.startsWith('/') && !href.startsWith('//')) location.assign(href);
      else changed(data);
      return;
    }
    if (data.status === 'undone') {
      show(el('p', {}, 'Undone.'));
      changed(data);
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
      if (!(data.options || []).length) input.focus();
      return;
    }
    if (data.status === 'confirm') {
      const yes = button('ko-tell-confirm', 'Do it', true);
      const no = button('ko-tell-cancel', 'Cancel');
      yes.addEventListener('click', () => run(`/api/command/${data.command_id}/answer`, {confirm: true}));
      no.addEventListener('click', async () => {
        await call(`/api/command/${data.command_id}/answer`, {confirm: false});
        close_();
      });
      const actions = el('div', {class: 'ko-tell-actions'});
      actions.append(yes, no);
      show(lines(data.lines), actions);
      return;
    }
    // failed, refused, or anything unexpected: say why, keep the sentence.
    show(el('p', {}, data.reason || 'That didn’t work — nothing was changed.'));
    input.focus();
  }

  async function run(path, body) {
    if (busy) return;
    setBusy(true);
    const data = await call(path, body);
    setBusy(false);
    render(data);
  }

  function open() {
    sheet.hidden = false;
    backdrop.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    input.focus();
    call('/api/command/warm');  // fire and forget
  }
  function close_() {
    sheet.hidden = true;
    backdrop.hidden = true;
    result.replaceChildren();
    fab.setAttribute('aria-expanded', 'false');
    if (reloadOnClose) { reloadOnClose = false; location.reload(); return; }
    fab.focus();
  }

  fab.addEventListener('click', open);
  close.addEventListener('click', close_);
  backdrop.addEventListener('click', close_);
  sheet.addEventListener('keydown', e => { if (e.key === 'Escape') close_(); });
  form.addEventListener('submit', e => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    run('/api/command', {text, context: context()});
  });

  // Keep the sheet above the on-screen keyboard.
  if (window.visualViewport) {
    const fit = () => {
      const gap = window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop;
      sheet.style.bottom = Math.max(0, gap) + 'px';
    };
    window.visualViewport.addEventListener('resize', fit);
    window.visualViewport.addEventListener('scroll', fit);
  }
})();

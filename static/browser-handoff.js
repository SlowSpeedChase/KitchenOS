/* A handoff secret exists only long enough to exchange it at this origin. */
(() => {
  const fragment = location.hash;
  history.replaceState(null, '', location.pathname + location.search);
  const status = document.getElementById('handoff-status');
  const error = document.getElementById('handoff-error');
  const fail = () => {
    status.textContent = '';
    error.textContent = 'This link is missing or has expired. Ask Siri to open the page again.';
  };
  const params = new URLSearchParams(fragment.slice(1));
  const code = params.get('code');
  if (!code || params.size !== 1) { fail(); return; }
  fetch('/api/browser-handoffs/exchange', {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({code})
  }).then(async response => {
    if (!response.ok) throw new Error('exchange');
    const data = await response.json();
    const destination = new URL(data.redirect_path, location.origin);
    if (destination.origin !== location.origin || !/^\/(recipe\/|meal-planner(?:\?|$))/.test(data.redirect_path)) throw new Error('destination');
    location.replace(destination.href);
  }).catch(fail);
})();

/* Server-derived viewing access shared by the recipe and planner pages. */
(() => {
  const node = document.getElementById('browser-view-config');
  const config = node ? JSON.parse(node.textContent) : {state:'active', readOnly:false};
  let expired = config.state === 'expired';
  const readOnly = Boolean(config.readOnly);
  const nativeFetch = window.fetch.bind(window);
  let banner;
  const persistence = '#add-week-btn,#servings-save,#servings-input,#new-meal-btn,#meal-modal-save,#pantry-modal-confirm,.remove-btn,.scale-btn,.cooked-btn,.card-menu-btn,.servings-btn,.meal-edit-btn';
  function disableControls() {
    if (!readOnly) return;
    document.querySelectorAll(persistence).forEach(control => {
      control.disabled = true;
      control.setAttribute('aria-disabled','true');
      control.title = 'Viewing from Siri. Open KitchenOS to make changes.';
    });
  }
  function expire() {
    if (!readOnly) return;
    expired = true;
    document.body.classList.add('browser-view-expired');
    if (banner) { banner.textContent = 'This Siri viewing session has expired. Ask Siri to open the page again.'; banner.setAttribute('role','alert'); banner.tabIndex=-1;banner.focus(); }
    document.querySelectorAll('.app,.wrap,body > main,.container').forEach(node => { if (!node.contains(banner)) node.inert = true; });
    window.dispatchEvent(new Event('kitchenos:view-expired'));
  }
  window.KitchenBrowserView = {readOnly, get expired(){return expired;}, expire};
  window.fetch = async (resource, options = {}) => {
    const url = new URL(resource instanceof Request ? resource.url : resource, location.href);
    const method = (options.method || (resource instanceof Request ? resource.method : 'GET')).toUpperCase();
    if (readOnly && url.origin === location.origin && (expired || !['GET','HEAD'].includes(method))) {
      const error = new Error(expired ? 'Siri viewing session expired.' : 'Viewing from Siri. Open KitchenOS to make changes.');
      error.name = 'BrowserViewingError'; throw error;
    }
    const response = await nativeFetch(resource, options);
    if (readOnly && url.origin === location.origin && response.status === 401) expire();
    return response;
  };
  if (!readOnly) return;
  const style = document.createElement('style');
  style.textContent = '.browser-view-banner{position:fixed;inset:auto 12px 12px;z-index:99999;padding:10px 14px;border:1px solid currentColor;border-radius:8px;background:var(--card-bg,#fff);color:var(--text,#222);font:14px/1.4 system-ui;box-shadow:0 3px 16px #0002;pointer-events:none}.browser-view-expired .app,.browser-view-expired .wrap{visibility:hidden}.browser-view-expired .browser-view-banner{inset:20vh 16px auto;padding:24px;font-size:18px}.browser-view-read-only #board-help{display:none}.browser-view-read-only button:disabled{opacity:.5;cursor:default}';
  document.head.append(style);
  document.body.classList.add('browser-view-read-only');
  banner = document.createElement('p'); banner.className='browser-view-banner'; banner.setAttribute('role','status');
  banner.textContent='Viewing from Siri · Changes are unavailable'; document.body.append(banner);
  disableControls(); new MutationObserver(disableControls).observe(document.body,{childList:true,subtree:true});
  if (expired) expire();
  else if (config.expires_at) setTimeout(expire, Math.max(0, config.expires_at*1000-Date.now()));
})();

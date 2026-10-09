function installPlanningAuthorization(origin, token) {
  if (location.origin !== origin || !token) return;
  const originalFetch = window.fetch.bind(window);
  window.fetch = function(resource, options) {
    const request = new Request(resource, options);
    const url = new URL(request.url);
    if (url.origin !== origin || !url.pathname.startsWith('/api/')) return originalFetch(request);
    const headers = new Headers(request.headers);
    headers.set('Authorization', `Bearer ${token}`);
    // Do not let an authenticated API response redirect the request elsewhere.
    return originalFetch(new Request(request, {headers, redirect:'error'}));
  };
}

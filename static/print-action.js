// Print buttons open a server-built PDF of this page, on every device.
//
// window.print() is unreliable on iOS Safari, and the old iOS branch shared
// the page URL — nothing printable from a phone. Every print page has a
// sibling `<path>.pdf` route (api_server.py "Print → PDF") rendering the same
// print stylesheet, so the device's own PDF viewer, which always has Print,
// does the printing. A button may name its PDF with data-print-pdf; otherwise
// it is this page's path + ".pdf" with the same query (so ?recipes=1 carries).
(() => {
    function pdfHref(button) {
        const named = button.getAttribute('data-print-pdf');
        if (named) return new URL(named, location.href).toString();
        const url = new URL(location.href);
        url.pathname = url.pathname.replace(/\/+$/, '') + '.pdf';
        url.hash = '';
        return url.toString();
    }

    document.addEventListener('click', (event) => {
        const button = event.target.closest('[data-print-action]');
        if (!button || button.disabled) return;
        button.disabled = true;
        button.dataset.label = button.textContent;
        button.textContent = 'Building PDF…';
        // Same-tab navigation: iOS blocks window.open after an await, and
        // the PDF viewer's Back returns here. pageshow restores the button
        // when Safari brings this page back from its back/forward cache.
        location.assign(pdfHref(button));
    });

    window.addEventListener('pageshow', () => {
        document.querySelectorAll('[data-print-action][data-label]').forEach((b) => {
            b.disabled = false;
            b.textContent = b.dataset.label;
            delete b.dataset.label;
        });
    });
})();

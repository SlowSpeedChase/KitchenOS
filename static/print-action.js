(() => {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
        || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    async function printOrShare() {
        if (isIOS && navigator.share) {
            try {
                await navigator.share({ title: document.title, url: window.location.href });
                return;
            } catch (error) {
                if (error.name === 'AbortError') return;
            }
        }
        window.print();
    }

    document.addEventListener('click', (event) => {
        if (event.target.closest('[data-print-action]')) printOrShare();
    });
})();

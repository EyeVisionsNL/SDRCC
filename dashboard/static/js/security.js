(() => {
    const token = document.querySelector('meta[name="csrf-token"]');
    if (!token) return;
    const original = window.fetch.bind(window);
    window.fetch = async (input, options = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, location.href);
        if (url.origin === location.origin) {
            const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
            if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
                const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
                headers.set('X-CSRF-Token', token.content);
                options = {...options, headers};
            }
        }
        const response = await original(input, options);
        if (url.origin === location.origin && response.status === 401) location.assign('/login');
        return response;
    };
})();

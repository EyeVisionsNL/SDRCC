/* Keep root-relative API calls inside the authenticated radio viewer. */
(() => {
    const prefix = document.querySelector('meta[name="sdrcc-view-prefix"]').content;
    const upstreamPath = document.querySelector('meta[name="sdrcc-view-upstream-path"]').content;
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    function mapped(value) {
        const url = new URL(value, location.href);
        if (url.origin !== location.origin || url.pathname.startsWith(prefix)) return url.href;
        const path = upstreamPath !== '/' && url.pathname.startsWith(upstreamPath)
            ? url.pathname.slice(upstreamPath.length) : url.pathname.replace(/^\//, '');
        url.pathname = prefix + path;
        return url.href;
    }
    const fetchOriginal = window.fetch.bind(window);
    window.fetch = (input, options = {}) => {
        const originalUrl = input instanceof Request ? input.url : input;
        const target = mapped(originalUrl);
        const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        if (new URL(target).origin === location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
            const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
            if (csrf) headers.set('X-CSRF-Token', csrf);
            options = {...options, headers};
        }
        if (input instanceof Request) input = new Request(target, input);
        else input = target;
        return fetchOriginal(input, options);
    };
    const open = XMLHttpRequest.prototype.open;
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        const target = mapped(url);
        this.sdrccCsrf = new URL(target).origin === location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase());
        return open.call(this, method, target, ...args);
    };
    XMLHttpRequest.prototype.send = function(body) {
        if (this.sdrccCsrf && csrf) this.setRequestHeader('X-CSRF-Token', csrf);
        return send.call(this, body);
    };
    if (window.EventSource) {
        const Source = window.EventSource;
        window.EventSource = class extends Source {
            constructor(url, options) { super(mapped(url), options); }
        };
    }
})();

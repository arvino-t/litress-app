// Встраивается в страницы litres.ru. Запоминает служебные заголовки
// (app-id, session-id и т.п.), которые сайт сам добавляет к запросам в свой API,
// и передаёт их приложению — без них API отвечает 403.
// Пароль и содержимое форм сюда не попадают.
(() => {
    if (window.__litreaderHook) return
    window.__litreaderHook = true

    const API = 'api.litres.ru/foundation/api/'
    const post = (headers, url) => {
        try {
            window.webkit.messageHandlers.litres.postMessage(
                JSON.stringify({ type: 'headers', url, headers }))
        } catch (_) {}
    }
    const norm = h => {
        const out = {}
        if (!h) return out
        if (h instanceof Headers) h.forEach((v, k) => { out[k.toLowerCase()] = v })
        else if (Array.isArray(h)) h.forEach(([k, v]) => { out[String(k).toLowerCase()] = String(v) })
        else for (const k of Object.keys(h)) out[k.toLowerCase()] = String(h[k])
        return out
    }

    const origFetch = window.fetch
    window.__litreaderFetch = origFetch.bind(window)
    window.fetch = function (input, init) {
        try {
            const url = typeof input === 'string' ? input
                : input instanceof URL ? input.href : input?.url
            if (url && url.includes(API))
                post({ ...(input instanceof Request ? norm(input.headers) : {}), ...norm(init?.headers) }, url)
        } catch (_) {}
        return origFetch.apply(this, arguments)
    }

    const { open, setRequestHeader, send } = XMLHttpRequest.prototype
    XMLHttpRequest.prototype.open = function (method, url) {
        this.__lrUrl = String(url)
        this.__lrHeaders = {}
        return open.apply(this, arguments)
    }
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
        if (this.__lrHeaders) this.__lrHeaders[String(k).toLowerCase()] = String(v)
        return setRequestHeader.apply(this, arguments)
    }
    XMLHttpRequest.prototype.send = function () {
        if (this.__lrUrl?.includes(API)) post(this.__lrHeaders, this.__lrUrl)
        return send.apply(this, arguments)
    }
})()

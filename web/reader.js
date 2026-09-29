// Читалка: открывает книгу через foliate-js и общается с Python-частью
// через window.webkit.messageHandlers.reader (туда) и window.reader (оттуда).
import './foliate/view.js'

const $ = s => document.querySelector(s)
const post = msg => window.webkit.messageHandlers.reader.postMessage(JSON.stringify(msg))

const THEMES = {
    light: { bg: '#ffffff', fg: '#1b1b1b', link: '#1a5fb4' },
    sepia: { bg: '#f4ecd8', fg: '#4b3a2a', link: '#8a4b08' },
    dark:  { bg: '#1e1e1e', fg: '#dadada', link: '#78aeed' },
    black: { bg: '#000000', fg: '#c4c4c4', link: '#78aeed' },
}

const FONTS = {
    book: null,
    serif: 'Georgia, "Noto Serif", "PT Serif", serif',
    sans: '"Inter Variable", Inter, "Noto Sans", sans-serif',
}

let view = null
let settings = null

const bookCSS = s => {
    const t = THEMES[s.theme] ?? THEMES.light
    const font = FONTS[s.font]
    return `
    html {
        color-scheme: ${s.theme === 'light' || s.theme === 'sepia' ? 'light' : 'dark'};
        font-size: ${s.fontSize}px !important;
        background: ${t.bg} !important;
        color: ${t.fg} !important;
    }
    body {
        background: transparent !important;
        color: inherit !important;
    }
    ${font ? `body, body * { font-family: ${font} !important; }` : ''}
    a:link, a:visited { color: ${t.link} !important; }
    p, li, blockquote, dd {
        line-height: ${s.lineHeight} !important;
        text-align: ${s.justify ? 'justify' : 'start'};
        -webkit-hyphens: ${s.hyphenate ? 'auto' : 'manual'};
        hyphens: ${s.hyphenate ? 'auto' : 'manual'};
        -webkit-hyphenate-limit-before: 3;
        -webkit-hyphenate-limit-after: 2;
        -webkit-hyphenate-limit-lines: 2;
        widows: 2;
        orphans: 2;
    }
    [align="left"] { text-align: left; }
    [align="right"] { text-align: right; }
    [align="center"] { text-align: center; }
    pre { white-space: pre-wrap !important; }
    img, svg { max-width: 100%; height: auto; }
    `
}

const applySettings = s => {
    settings = s
    const t = THEMES[s.theme] ?? THEMES.light
    document.documentElement.style.setProperty('--bg', t.bg)
    document.documentElement.style.setProperty('--fg', t.fg)
    const r = view?.renderer
    if (!r) return
    r.setAttribute('gap', `${s.margin}%`)
    r.setAttribute('margin', '36px')
    r.setAttribute('max-inline-size', `${s.lineWidth}px`)
    r.setAttribute('max-column-count', s.twoColumns ? '2' : '1')
    r.setStyles?.(bookCSS(s))
}

// Название и автор могут быть строкой, объектом {язык: строка} или массивом
const formatName = x => {
    if (!x) return ''
    if (typeof x === 'string') return x
    if (Array.isArray(x)) return x.map(formatName).filter(Boolean).join(', ')
    if (x.name) return formatName(x.name)
    return Object.values(x)[0] ?? ''
}

const flattenTOC = (items, depth = 0, out = []) => {
    for (const item of items ?? []) {
        out.push({ label: (item.label ?? '').trim(), href: item.href, depth })
        flattenTOC(item.subitems, depth + 1, out)
    }
    return out
}

const onKey = e => {
    const k = e.key
    if (k === 'ArrowLeft' || k === 'PageUp' || k === 'h') view?.goLeft()
    else if (k === 'ArrowRight' || k === 'PageDown' || k === ' ' || k === 'l') view?.goRight()
    else if (k === 'Home') view?.goToFraction(0)
    else if (k === 'Escape') post({ type: 'escape' })
    else return
    e.preventDefault()
}

// Касание: левая треть — назад, правая — вперёд, середина — показать/скрыть панели
const onClick = (doc, e) => {
    if (e.defaultPrevented || e.button !== 0) return
    if (e.target.closest?.('a[href]')) return
    const sel = doc.getSelection()
    if (sel && !sel.isCollapsed) return
    const frame = doc.defaultView.frameElement
    const x = (frame ? frame.getBoundingClientRect().left : 0) + e.clientX
    const w = window.innerWidth
    if (x < w * 0.3) view.goLeft()
    else if (x > w * 0.7) view.goRight()
    else post({ type: 'toggle-ui' })
}

const onRelocate = ({ detail }) => {
    const percent = Math.round((detail.fraction ?? 0) * 100)
    const chapter = detail.tocItem?.label?.trim() ?? ''
    $('#percent').textContent = `${percent}%`
    $('#chapter').textContent = chapter
    post({ type: 'relocate', cfi: detail.cfi, fraction: detail.fraction ?? 0, chapter,
        atEnd: !!view?.renderer?.atEnd })
}

const open = async ({ url, name, cfi, settings: s }) => {
    try {
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(`Не удалось прочитать файл (${resp.status})`)
        const file = new File([await resp.blob()], name)

        view = document.createElement('foliate-view')
        document.body.append(view)
        await view.open(file)

        view.addEventListener('relocate', onRelocate)
        view.addEventListener('load', ({ detail: { doc } }) => {
            doc.addEventListener('keydown', onKey)
            doc.addEventListener('click', e => onClick(doc, e))
        })
        view.addEventListener('external-link', e => {
            e.preventDefault()
            post({ type: 'external-link', href: e.detail.href })
        })

        applySettings(s)
        const { metadata = {}, toc } = view.book
        post({
            type: 'opened',
            title: formatName(metadata.title),
            author: formatName(metadata.author),
            toc: flattenTOC(toc),
        })
        await view.init({ lastLocation: cfi || null, showTextStart: !cfi })
        $('#loading').remove()
    } catch (err) {
        console.error(err)
        $('#loading').textContent = `Не удалось открыть книгу: ${err.message ?? err}`
        $('#loading').classList.add('error')
        post({ type: 'error', message: String(err.message ?? err) })
    }
}

document.addEventListener('keydown', onKey)

window.reader = {
    open,
    applySettings,
    next: () => view?.goRight(),
    prev: () => view?.goLeft(),
    goTo: href => view?.goTo(href),
    goToFraction: f => view?.goToFraction(f),
}

post({ type: 'ready' })

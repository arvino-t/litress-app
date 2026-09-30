// Читалка: открывает книгу через foliate-js и общается с Python-частью
// через консоль с меткой (туда) и window.reader (оттуда).
import './foliate/view.js'

const $ = s => document.querySelector(s)
const post = msg => console.log('\u2063LITREADER:' + JSON.stringify(msg))

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
    ::highlight(tts) { background-color: rgba(255, 140, 0, 0.38); }
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

// --- жесты: смахивание вверх — оглавление, вниз — панели, щипок / Ctrl+колесо — размер шрифта
const gesture = { start: null, pinch: null, last: null }
const fingers = t => Math.hypot(t[0].screenX - t[1].screenX, t[0].screenY - t[1].screenY)
const attachGestures = target => {
    target.addEventListener('touchstart', e => {
        if (e.touches.length === 2) {
            gesture.pinch = fingers(e.touches)
            gesture.last = null
            gesture.start = null
        } else if (e.touches.length === 1 && !gesture.pinch) {
            const t = e.touches[0]
            gesture.start = { x: t.screenX, y: t.screenY, time: e.timeStamp }
        }
    }, { passive: true })
    target.addEventListener('touchmove', e => {
        if (e.touches.length === 2 && gesture.pinch) {
            e.preventDefault()
            gesture.last = fingers(e.touches)
        }
    }, { passive: false })
    target.addEventListener('touchend', e => {
        if (gesture.pinch) {
            if (e.touches.length === 0) {
                const ratio = gesture.last ? gesture.last / gesture.pinch : 1
                if (ratio > 1.12 || ratio < 0.89) post({ type: 'pinch', scale: ratio })
                gesture.pinch = gesture.last = null
            }
            return
        }
        const st = gesture.start
        gesture.start = null
        if (!st || e.changedTouches.length !== 1) return
        const t = e.changedTouches[0]
        const dx = t.screenX - st.x, dy = t.screenY - st.y
        if (Math.abs(dx) > 70 || e.timeStamp - st.time > 900) return
        if (dy < -110) post({ type: 'swipe-up' })
        else if (dy > 110) post({ type: 'swipe-down' })
    }, { passive: true })
    target.addEventListener('wheel', e => {
        if (!e.ctrlKey) return
        e.preventDefault()
        post({ type: 'pinch', scale: e.deltaY < 0 ? 1.15 : 0.87 })
    }, { passive: false })
}

// --- чтение вслух: текст предложениями с метками, подсветка читаемого
const ttsHighlight = range => {
    view.renderer.scrollToAnchor?.(range, true)
    try {
        const win = range.startContainer.ownerDocument.defaultView
        win.CSS.highlights.set('tts', new win.Highlight(range))
    } catch (_) {}
}
const ttsClear = () => {
    for (const { doc } of view?.renderer?.getContents?.() ?? [])
        try { doc.defaultView.CSS.highlights.delete('tts') } catch (_) {}
}
// SSML → [{mark, text}]: текст между метками <mark name="…"/>
const ssmlSegments = ssml => {
    if (!ssml) return null
    const doc = new DOMParser().parseFromString(ssml, 'application/xml')
    const segments = []
    let cur = { mark: null, text: '' }
    const walker = doc.createTreeWalker(doc.documentElement, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (n.nodeType === 1 && n.localName === 'mark') {
            if (cur.text.trim()) segments.push(cur)
            cur = { mark: n.getAttribute('name'), text: '' }
        } else if (n.nodeType === 3) cur.text += n.nodeValue
    }
    if (cur.text.trim()) segments.push(cur)
    return segments.map(x => ({ mark: x.mark, text: x.text.replace(/\s+/g, ' ').trim() }))
}
const ttsSend = segments => post({ type: 'tts', segments: segments ?? [] })
const ttsStart = async () => {
    await view.initTTS('sentence', ttsHighlight)
    const range = view.lastLocation?.range
    ttsSend(ssmlSegments(range ? view.tts.from(range) : view.tts.start()))
}
const ttsNext = async () => {
    let segs = ssmlSegments(view.tts?.next())
    // Раздел кончился — переходим к следующему (глава, файл книги), пока не найдём текст
    for (let guard = 0; (!segs || !segs.length) && guard < 10; guard++) {
        const index = view.renderer.getContents?.()[0]?.index
        if (index == null || index + 1 >= view.book.sections.length) break
        await view.renderer.goTo({ index: index + 1 })
        await view.initTTS('sentence', ttsHighlight)
        segs = ssmlSegments(view.tts.start())
    }
    if (!segs || !segs.length) post({ type: 'tts-end' })
    else ttsSend(segs)
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
            attachGestures(doc)
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
attachGestures(document)

window.reader = {
    open,
    applySettings,
    next: () => view?.goRight(),
    prev: () => view?.goLeft(),
    goTo: href => view?.goTo(href),
    goToFraction: f => view?.goToFraction(f),
    ttsStart, ttsNext,
    ttsMark: mark => view?.tts?.setMark(mark),
    ttsStop: ttsClear,
}

post({ type: 'ready' })

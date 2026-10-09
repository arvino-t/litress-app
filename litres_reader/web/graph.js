// Граф книг по тегам — как граф в Obsidian: книги и теги — узлы, связь «книга — тег» — ребро.
// Данные приходят из Python (window.graph.load), сообщения уходят через console.log с меткой.
'use strict'

const PREFIX = '⁣LITREADER:'
const post = msg => console.log(PREFIX + JSON.stringify(msg))
const $ = id => document.getElementById(id)
// Перевод строк: словарь {русский: перевод} приходит из Python вместе с данными графа
let I18N = {}
const T = (s, ...a) => (I18N[s] ?? s).replace(/\{(\d+)\}/g, (_, i) => a[i])
const translatePage = () => {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.dataset.i18nSrc ??= el.textContent.trim()
        el.textContent = T(el.dataset.i18nSrc)
    })
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.dataset.i18nSrc ??= el.placeholder
        el.placeholder = T(el.dataset.i18nSrc)
    })
}

const canvas = $('graph')
const ctx = canvas.getContext('2d')
let W = 0, H = 0, dpr = 1

let data = null                 // { nodes, links, kinds: [{id, label, color}], theme }
let nodes = [], links = [], byId = new Map(), adj = new Map()
let sim = null
const view = { x: 0, y: 0, k: 1 }   // сдвиг (в пикселях экрана) и масштаб
let hover = null, selected = null, query = ''
const state = { source: 'all', kinds: null, minDeg: 2, orphans: false }

const kindOf = id => id.slice(0, id.indexOf(':'))
const colorOfKind = kind => (data.kinds.find(k => k.id === kind) || {}).color || '#888'

// --- размеры

function resize() {
    dpr = window.devicePixelRatio || 1
    W = window.innerWidth
    H = window.innerHeight
    canvas.width = Math.round(W * dpr)
    canvas.height = Math.round(H * dpr)
    canvas.style.width = W + 'px'
    canvas.style.height = H + 'px'
    draw()
}
window.addEventListener('resize', resize)

// --- построение графа по фильтрам

const sourceOk = node => state.source === 'all' || node.src === state.source

function build(keepView) {
    const enabled = new Set(state.kinds)
    const bookById = new Map(data.nodes.filter(n => n.kind === 'book').map(n => [n.id, n]))
    // сколько подходящих книг у каждого тега
    const deg = new Map()
    for (const l of data.links) {
        const book = bookById.get(l.source)
        if (book && sourceOk(book) && enabled.has(kindOf(l.target)))
            deg.set(l.target, (deg.get(l.target) || 0) + 1)
    }
    const L = data.links.filter(l => {
        const book = bookById.get(l.source)
        return book && sourceOk(book) && enabled.has(kindOf(l.target)) && (deg.get(l.target) || 0) >= state.minDeg
    })
    const used = new Set()
    for (const l of L) { used.add(l.source); used.add(l.target) }
    const N = data.nodes.filter(n => n.kind === 'book'
        ? sourceOk(n) && (used.has(n.id) || state.orphans)
        : used.has(n.id))

    const old = byId
    nodes = N.map(n => {
        const prev = old.get(n.id)
        const node = prev ? Object.assign(prev, n) : { ...n }
        node.deg = 0
        node.fx = node.fy = null
        if (node.kind !== 'book') node.color = colorOfKind(node.kind)
        return node
    })
    byId = new Map(nodes.map(n => [n.id, n]))
    links = L.map(l => ({ source: byId.get(l.source), target: byId.get(l.target) }))
    adj = new Map(nodes.map(n => [n.id, new Set()]))
    for (const l of links) {
        l.source.deg++; l.target.deg++
        adj.get(l.source.id).add(l.target.id)
        adj.get(l.target.id).add(l.source.id)
    }
    for (const n of nodes)
        n.r = n.kind === 'book' ? 3.2 + Math.min(3, Math.sqrt(n.deg) * 0.8) : 4 + Math.sqrt(n.deg) * 2.2
    if (selected && !byId.has(selected.id)) selected = null
    if (hover && !byId.has(hover.id)) hover = null

    if (sim) sim.stop()
    sim = d3.forceSimulation(nodes).stop()
        .force('link', d3.forceLink(links).distance(l => 18 + l.target.r * 1.5).strength(0.35))
        .force('charge', d3.forceManyBody().strength(n => n.kind === 'book' ? -28 : -90 - n.deg * 2).distanceMax(700))
        .force('x', d3.forceX(0).strength(0.035))
        .force('y', d3.forceY(0).strength(0.035))
        .force('collide', d3.forceCollide(n => n.r + 1.5))
        .alphaDecay(0.025)
    runLayout(keepView)
    if (!keepView) setTimeout(fit, 600)
    progress.layout = nodes.length ? 0.01 : null
    showProgress()

    $('empty').hidden = nodes.length > 0
    const books = nodes.filter(n => n.kind === 'book').length
    $('stats').textContent = T('{0} книг · {1} тегов', books, nodes.length - books)
    for (const k of data.kinds) {
        const el = document.querySelector(`.kind[data-k="${k.id}"] .n`)
        if (el) el.textContent = [...deg.entries()].filter(([id, d]) => kindOf(id) === k.id && d >= state.minDeg).length
    }
}

// --- раскладка: свой цикл вместо таймера d3 — сколько успеем шагов за ~14 мс, потом один кадр.
// Встроенный таймер делает один шаг на кадр и каждый раз перерисовывает весь граф — на большом
// экране это десятки секунд; так раскладка занимает 1–3 секунды.
let layoutRun = 0, layoutActive = false
function runLayout(keepView) {
    const run = ++layoutRun
    layoutActive = true
    const frame = () => {
        if (run !== layoutRun) return            // начали новую раскладку
        const t0 = performance.now()
        do { sim.tick() } while (sim.alpha() > sim.alphaMin() && performance.now() - t0 < 14)
        draw()
        progress.layout = layoutFraction()
        showProgress()
        if (sim.alpha() > sim.alphaMin()) {
            requestAnimationFrame(frame)
        } else {
            layoutActive = false
            if (!keepView && !dragging()) fit()
            progress.layout = null
            showProgress()
            post({ type: 'layout-done' })
        }
    }
    requestAnimationFrame(frame)
}
// при перетаскивании узла «подогреваем» раскладку и ведём её своим циклом
function reheat() {
    if (sim.alpha() < 0.1) sim.alpha(0.3)
    if (layoutActive) return                     // раскладка и так идёт — её цикл всё отрисует
    const run = ++layoutRun
    const frame = () => {
        if (run !== layoutRun) return
        sim.tick()
        draw()
        if (sim.alpha() > sim.alphaMin() && (dragging() || sim.alpha() > 0.02)) requestAnimationFrame(frame)
    }
    requestAnimationFrame(frame)
}
const dragging = () => !!(drag && drag.node && drag.moved)

// --- отрисовка

const toWorld = (x, y) => [(x - W / 2 - view.x) / view.k, (y - H / 2 - view.y) / view.k]

function draw() {
    if (!data) return
    const th = data.theme
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = th.bg
    ctx.fillRect(0, 0, W, H)
    ctx.translate(W / 2 + view.x, H / 2 + view.y)
    ctx.scale(view.k, view.k)

    const focus = hover || selected
    const near = focus ? adj.get(focus.id) : null
    const q = query
    const matches = n => q && n.label.toLowerCase().includes(q)
    const lit = n => !focus || n === focus || near.has(n.id)

    ctx.lineWidth = 1 / view.k
    for (const l of links) {
        const on = focus && (l.source === focus || l.target === focus)
        ctx.globalAlpha = focus ? (on ? 0.9 : 0.06) : 0.35
        ctx.strokeStyle = on ? focus.color : th.link
        ctx.beginPath()
        ctx.moveTo(l.source.x, l.source.y)
        ctx.lineTo(l.target.x, l.target.y)
        ctx.stroke()
    }
    for (const n of nodes) {
        const dim = !lit(n) || (q && !matches(n))
        ctx.globalAlpha = dim ? 0.15 : 1
        ctx.fillStyle = n.color
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2)
        ctx.fill()
        if (n === selected || matches(n)) {
            ctx.lineWidth = 2 / view.k
            ctx.strokeStyle = th.text
            ctx.stroke()
            ctx.lineWidth = 1 / view.k
        }
    }
    // подписи: у тегов — при обычном масштабе, у книг — при приближении или в фокусе
    ctx.globalAlpha = 1
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = th.text
    const fs = 12 / view.k
    // Кандидаты на подпись по важности: фокус, соседи, найденные, крупные теги, книги.
    // Подписи, которые наезжают на уже выведенные, пропускаем (как в Obsidian).
    const rank = n => n === focus ? 4 : (focus && near.has(n.id)) ? 3 : matches(n) ? 2
        : n.kind !== 'book' ? 1 + Math.min(n.deg, 99) / 100 : 0.5
    const cands = nodes.filter(n => n === focus || (focus && near.has(n.id)) || matches(n)
        || (!focus && (n.kind !== 'book' ? view.k > 0.35 || n.deg >= 6 : view.k > 2.2)))
    cands.sort((a, b) => rank(b) - rank(a))
    const placed = []
    for (const n of cands) {
        const big = n.kind !== 'book'
        ctx.font = `${big ? 600 : 400} ${big ? fs * 1.05 : fs}px Inter, "Inter Variable", Cantarell, sans-serif`
        const text = n.label.length > 42 ? n.label.slice(0, 40) + '…' : n.label
        const w = ctx.measureText(text).width, h = fs * 1.25
        const box = { x0: n.x - w / 2, x1: n.x + w / 2, y0: n.y + n.r + 2 / view.k, y1: n.y + n.r + 2 / view.k + h }
        if (rank(n) < 2 && placed.some(p => box.x0 < p.x1 && box.x1 > p.x0 && box.y0 < p.y1 && box.y1 > p.y0)) continue
        placed.push(box)
        ctx.globalAlpha = !lit(n) ? 0.2 : 1
        ctx.fillText(text, n.x, box.y0)
    }
    ctx.globalAlpha = 1
}

function fit() {
    if (!nodes.length) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const n of nodes) {
        x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y)
    }
    const panel = W > 640 ? 260 : 0
    const k = Math.min(3, Math.max(0.08, Math.min((W - panel - 60) / (x1 - x0 || 1), (H - 60) / (y1 - y0 || 1))))
    view.k = k
    view.x = -((x0 + x1) / 2) * k + panel / 2
    view.y = -((y0 + y1) / 2) * k
    draw()
}

// --- указатель: мышь, тачпад, сенсорный экран

function nodeAt(x, y) {
    const [wx, wy] = toWorld(x, y)
    let best = null, bestD = Infinity
    for (const n of nodes) {
        const d = Math.hypot(n.x - wx, n.y - wy)
        if (d < n.r + 6 / view.k && d < bestD) { best = n; bestD = d }
    }
    return best
}

function showTip(n, x, y) {
    const tip = $('tip')
    if (!n) { tip.hidden = true; return }
    const kind = n.kind === 'book' ? '' : (data.kinds.find(k => k.id === n.kind) || {}).label
    tip.innerHTML = ''
    const t = document.createElement('div')
    t.textContent = n.label
    tip.append(t)
    const sub = n.kind === 'book' ? [n.sub, n.pct ? T('прочитано {0}%', n.pct) : ''].filter(Boolean).join(' · ')
                                  : T('{0} · книг: {1}', kind, n.deg)
    if (sub) {
        const s = document.createElement('div')
        s.className = 's'
        s.textContent = sub
        tip.append(s)
    }
    tip.hidden = false
    const r = tip.getBoundingClientRect()
    tip.style.left = Math.min(x + 14, W - r.width - 8) + 'px'
    tip.style.top = Math.min(y + 14, H - r.height - 8) + 'px'
}

const pointers = new Map()
let drag = null      // {node?, moved, startX, startY, lastX, lastY}
let pinch = null     // {dist, k, cx, cy}

canvas.addEventListener('pointerdown', e => {
    canvas.setPointerCapture(e.pointerId)
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.size === 2) {
        const [a, b] = [...pointers.values()]
        pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), k: view.k, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2,
                  vx: view.x, vy: view.y }
        if (drag && drag.node) { drag.node.fx = drag.node.fy = null }
        drag = null
        return
    }
    const node = nodeAt(e.clientX, e.clientY)
    drag = { node, moved: false, startX: e.clientX, startY: e.clientY, lastX: e.clientX, lastY: e.clientY }
    if (!node) canvas.classList.add('drag')
})

canvas.addEventListener('pointermove', e => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()]
        const k = Math.min(6, Math.max(0.05, pinch.k * Math.hypot(a.x - b.x, a.y - b.y) / pinch.dist))
        const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2
        // точка под пальцами остаётся на месте
        const wx = (pinch.cx - W / 2 - pinch.vx) / pinch.k, wy = (pinch.cy - H / 2 - pinch.vy) / pinch.k
        view.k = k
        view.x = cx - W / 2 - wx * k
        view.y = cy - H / 2 - wy * k
        draw()
        return
    }
    if (drag) {
        if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 4) drag.moved = true
        if (drag.node) {
            if (drag.moved) {
                const [wx, wy] = toWorld(e.clientX, e.clientY)
                drag.node.fx = wx; drag.node.fy = wy
                if (!drag.heated) { drag.heated = true; reheat() }
            }
        } else {
            view.x += e.clientX - drag.lastX
            view.y += e.clientY - drag.lastY
            draw()
        }
        drag.lastX = e.clientX; drag.lastY = e.clientY
        $('tip').hidden = true
        return
    }
    if (e.pointerType !== 'mouse') return
    const n = nodeAt(e.clientX, e.clientY)
    if (n !== hover) { hover = n; draw() }
    canvas.classList.toggle('node', !!n)
    showTip(n, e.clientX, e.clientY)
})

function endPointer(e) {
    pointers.delete(e.pointerId)
    if (pinch) { if (pointers.size < 2) pinch = null; return }
    canvas.classList.remove('drag')
    if (!drag) return
    const { node, moved } = drag
    drag = null
    if (node) {
        node.fx = node.fy = null
    }
    if (moved) return
    if (!node) {                       // щелчок по пустому месту — снять выделение
        selected = null; hover = null; draw(); $('tip').hidden = true
    } else if (node.kind === 'book') {
        if (e.pointerType !== 'mouse' && selected !== node) {
            selected = node; draw(); showTip(node, e.clientX, e.clientY)   // касание: сначала подсказка
        } else {
            post({ type: 'open', id: node.id })
        }
    } else {
        selected = selected === node ? null : node
        draw()
        showTip(selected, e.clientX, e.clientY)
    }
}
canvas.addEventListener('pointerup', endPointer)
canvas.addEventListener('pointercancel', endPointer)
canvas.addEventListener('pointerleave', e => {
    if (e.pointerType === 'mouse' && !drag) { hover = null; draw(); $('tip').hidden = true }
})

canvas.addEventListener('wheel', e => {
    e.preventDefault()
    const k = Math.min(6, Math.max(0.05, view.k * Math.exp(-e.deltaY * 0.0015)))
    const [wx, wy] = toWorld(e.clientX, e.clientY)
    view.k = k
    view.x = e.clientX - W / 2 - wx * k
    view.y = e.clientY - H / 2 - wy * k
    draw()
}, { passive: false })

// --- панель

function saveState() { post({ type: 'state', state }) }

function setupPanel() {
    const kinds = $('kinds')
    kinds.innerHTML = ''
    for (const k of data.kinds) {
        const row = document.createElement('label')
        row.className = 'kind'
        row.dataset.k = k.id
        const box = document.createElement('input')
        box.type = 'checkbox'
        box.checked = state.kinds.includes(k.id)
        box.addEventListener('change', () => {
            state.kinds = data.kinds.map(x => x.id).filter(id =>
                document.querySelector(`.kind[data-k="${id}"] input`).checked)
            build(); saveState()
        })
        const dot = document.createElement('span')
        dot.className = 'dot'
        dot.style.background = k.color
        const name = document.createElement('span')
        name.textContent = k.label
        const n = document.createElement('span')
        n.className = 'n'
        row.append(box, dot, name, n)
        kinds.append(row)
    }
    for (const b of document.querySelectorAll('#source button')) {
        b.classList.toggle('on', b.dataset.v === state.source)
        b.onclick = () => {
            state.source = b.dataset.v
            for (const x of document.querySelectorAll('#source button')) x.classList.toggle('on', x === b)
            build(); saveState()
        }
    }
    $('minDeg').value = state.minDeg
    $('minDegVal').textContent = state.minDeg
    $('minDeg').oninput = () => { $('minDegVal').textContent = $('minDeg').value }
    $('minDeg').onchange = () => { state.minDeg = +$('minDeg').value; build(true); saveState() }
    $('orphans').checked = state.orphans
    $('orphans').onchange = () => { state.orphans = $('orphans').checked; build(true); saveState() }
    $('fit').onclick = fit
    $('search').oninput = () => { query = $('search').value.trim().toLowerCase(); draw() }
    $('search').onkeydown = e => {
        if (e.key === 'Enter' && query) {
            const n = nodes.find(x => x.label.toLowerCase().includes(query))
            if (n) {
                selected = n
                view.k = Math.max(view.k, 1.6)
                view.x = -n.x * view.k
                view.y = -n.y * view.k
                draw()
            }
        } else if (e.key === 'Escape') {
            $('search').value = ''; query = ''; draw()
        }
    }
}

document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.activeElement !== $('search')) post({ type: 'escape' })
})

window.graph = {
    load(d, saved) {
        data = d
        // одна библиотека — переключатель «Все / ЛитРес / Мои» не нужен
        $('source').closest('section').hidden = !!d.single
        if (d.single) saved = { ...(saved || {}), source: 'all' }
        I18N = d.i18n || {}
        translatePage()
        document.documentElement.dataset.theme = d.theme.dark ? 'dark' : 'light'
        document.documentElement.style.setProperty('--accent', d.theme.accent)
        // у каждой библиотеки своё состояние — сначала исходное, потом сохранённое
        Object.assign(state, { source: 'all', kinds: null, minDeg: 2, orphans: false }, saved || {})
        const ids = d.kinds.map(k => k.id)
        state.kinds = (state.kinds || d.kinds.filter(k => k.on).map(k => k.id)).filter(id => ids.includes(id))
        setupPanel()
        resize()
        build()
    },
    // обновление данных (подгрузились жанры) без сброса масштаба
    update(d) {
        data = d
        build(true)
    },
    // ход подгрузки жанров с ЛитРес: text, fraction 0..1; null — закончено
    status(text, fraction) {
        progress.fetch = text ? { text, fraction } : null
        showProgress()
    },
}

// --- индикатор: раскладка графа и подгрузка жанров

const progress = {
    layout: null,     // доля раскладки 0..1 или null — готово
    fetch: null,      // { text, fraction } или null
}
function showProgress() {
    const box = $('progress')
    const layoutOn = progress.layout !== null
    $('pLayout').hidden = !layoutOn
    if (layoutOn) {
        const pct = Math.round(progress.layout * 100)
        $('pLayoutText').textContent = progress.layout > 0 ? T('Раскладка графа — {0}%', pct) : T('Строю граф…')
        $('pLayoutBar').classList.toggle('busy', progress.layout === 0)
        $('pLayoutBar').style.width = `${pct}%`
    }
    $('pFetch').hidden = !progress.fetch
    if (progress.fetch) {
        $('pFetchText').textContent = progress.fetch.text
        $('pFetchBar').style.width = `${Math.round(progress.fetch.fraction * 100)}%`
    }
    box.classList.toggle('done', !layoutOn && !progress.fetch)
}
// доля раскладки: alpha убывает экспоненциально от 1 до alphaMin
const layoutFraction = () => Math.min(1, Math.max(0.01, Math.log(sim.alpha()) / Math.log(sim.alphaMin())))

progress.layout = 0
showProgress()
resize()
post({ type: 'ready' })

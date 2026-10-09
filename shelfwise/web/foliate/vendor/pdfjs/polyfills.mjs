// Заменители новых функций JavaScript, которые использует pdf.js, а Chromium во встроенном
// QtWebEngine ещё не поддерживает. Определяются, только если функции нет.
for (const C of [Map, WeakMap]) {
    if (!C.prototype.getOrInsert) {
        C.prototype.getOrInsert = function (key, value) {
            if (!this.has(key)) this.set(key, value)
            return this.get(key)
        }
    }
    if (!C.prototype.getOrInsertComputed) {
        C.prototype.getOrInsertComputed = function (key, compute) {
            if (!this.has(key)) this.set(key, compute(key))
            return this.get(key)
        }
    }
}
if (!Math.sumPrecise) {
    // Сумма Ноймайера (компенсированная) — достаточно точна для координат и метрик pdf.js
    Math.sumPrecise = iterable => {
        let sum = 0, c = 0
        for (const x of iterable) {
            const t = sum + x
            c += Math.abs(sum) >= Math.abs(x) ? (sum - t) + x : (x - t) + sum
            sum = t
        }
        return sum + c
    }
}
if (!Uint8Array.fromBase64) {
    Uint8Array.fromBase64 = s => Uint8Array.from(atob(s.replace(/\s+/g, '')), ch => ch.charCodeAt(0))
}
if (!Uint8Array.prototype.toBase64) {
    Uint8Array.prototype.toBase64 = function () {
        let bin = ''
        for (let i = 0; i < this.length; i += 0x8000) bin += String.fromCharCode(...this.subarray(i, i + 0x8000))
        return btoa(bin)
    }
}
if (!Uint8Array.prototype.toHex) {
    Uint8Array.prototype.toHex = function () {
        return Array.from(this, b => b.toString(16).padStart(2, '0')).join('')
    }
}

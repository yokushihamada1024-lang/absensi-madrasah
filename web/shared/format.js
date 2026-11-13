// Format Rupiah & tanggal Indonesia tanpa bergantung locale OS/browser.
// WIB = UTC+7 (Indonesia tidak memakai DST).

export const BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
  "September", "Oktober", "November", "Desember"];
export const HARI = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"];
const WIB_OFFSET_MS = 7 * 3600 * 1000;

export function rupiah(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "-";
  const v = Math.round(Number(n));
  const s = String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return (v < 0 ? "-Rp " : "Rp ") + s;
}

/** Date/ISO → objek tanggal "dinding" WIB {y, m (1-12), d, hh, mm, dow}. */
export function wibParts(input) {
  const t = (input instanceof Date ? input : new Date(input)).getTime() + WIB_OFFSET_MS;
  const d = new Date(t);
  return { y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate(),
           hh: d.getUTCHours(), mm: d.getUTCMinutes(), ss: d.getUTCSeconds(), dow: d.getUTCDay() };
}

const pad = (n) => String(n).padStart(2, "0");

export function hhmm(iso) {
  const p = wibParts(iso);
  return `${pad(p.hh)}:${pad(p.mm)}`;
}

/** "2026-11-13" → "13 November 2026" (opsional diawali nama hari). */
export function tanggal(isoDate, withDay = false) {
  const [y, m, d] = String(isoDate).slice(0, 10).split("-").map(Number);
  const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  const s = `${d} ${BULAN[m - 1]} ${y}`;
  return withDay ? `${HARI[dow]}, ${s}` : s;
}

export function tanggalPendek(isoDate) {
  const [, m, d] = String(isoDate).slice(0, 10).split("-").map(Number);
  return `${d} ${BULAN[m - 1].slice(0, 3)}`;
}

/** "2026-11" → "November 2026". */
export function periode(p) {
  const [y, m] = p.split("-").map(Number);
  return `${BULAN[m - 1]} ${y}`;
}

/** Hari ini (WIB) sebagai "YYYY-MM-DD". */
export function todayWib() {
  const p = wibParts(new Date());
  return `${p.y}-${pad(p.m)}-${pad(p.d)}`;
}

export function periodNow() {
  return todayWib().slice(0, 7);
}

export function shiftPeriod(p, delta) {
  let [y, m] = p.split("-").map(Number);
  m += delta;
  while (m < 1) { m += 12; y -= 1; }
  while (m > 12) { m -= 12; y += 1; }
  return `${y}-${pad(m)}`;
}

export function statusText(status, lateMin) {
  return status === "late" ? `Terlambat ${lateMin} menit` : "Tepat waktu";
}

/** Helper DOM aman: el("div", {class: "x"}, "teks", child) — teks selalu jadi text node. */
export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (v === true) n.setAttribute(k, "");
    else n.setAttribute(k, String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

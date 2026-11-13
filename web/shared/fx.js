// Interaksi & gerak bersama: loader Bars, status sibuk tombol, riak sentuh, ikon SVG, layar pembuka.
// Semua DOM dibangun lewat API (tanpa HTML mentah); posisi/variabel lewat CSSOM agar lolos CSP.
import { el } from "./format.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const reduceMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Loader gelombang (port vanilla dari komponen Bars). */
export function bars(count = 4, { label = "Memuat", cls = "", status = true } = {}) {
  const s = el("span", { class: ("bars " + cls).trim(), role: status ? "status" : null });
  for (let i = 0; i < count; i++) s.append(el("span", { "aria-hidden": "true" }));
  if (label) s.append(el("span", { class: "sr-only" }, label));
  return s;
}

/** Blok pemuatan halaman/bagian. */
export function loadingBlock(text = "Memuat…") {
  return el("div", { class: "loading" }, bars(4, { label: "" }), el("span", {}, text));
}

/** Nyalakan/matikan status sibuk sebuah tombol (disabled + aria-busy + Bars di tengah). */
export function busy(btn, on) {
  if (!btn) return;
  if (on) {
    if (btn.getAttribute("aria-busy") === "true") return;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.append(el("span", { class: "btn-busy", "aria-hidden": "true" }, bars(4, { label: "", status: false })));
  } else {
    btn.removeAttribute("aria-busy");
    btn.querySelector(":scope > .btn-busy")?.remove();
    btn.disabled = false;
  }
}

/** Ikon garis sederhana (24×24, stroke currentColor). */
const ICONS = {
  qr: ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h2v2h-2z", "M18 14h2", "M14 18h2v2", "M18 18h2v2h-2z"],
  check: ["M5 12.5l4.2 4.2L19 7"],
  back: ["M15 5l-7 7 7 7"],
  next: ["M9 5l7 7-7 7"],
  logout: ["M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3", "M10 16l-4-4 4-4", "M6 12h10"],
  history: ["M4 12a8 8 0 1 0 2.4-5.7", "M4 4v4h4", "M12 8v4l3 2"],
  clock: ["M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v5l3 2"],
  pin: ["M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z", "M12 7.5a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"],
  camera: ["M4 8h3l2-3h6l2 3h3v11H4z", "M12 10a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"],
  download: ["M12 4v11", "M7 10l5 5 5-5", "M5 20h14"],
  alert: ["M12 4l9 16H3z", "M12 10v4", "M12 17.2v.1"],
  install: ["M12 3v12", "M7 10l5 5 5-5", "M4 17v3h16v-3"],
};

export function icon(name, cls = "ico") {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("fill", "none");
  s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.8");
  s.setAttribute("stroke-linecap", "round");
  s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", cls);
  for (const d of ICONS[name] || []) {
    const p = document.createElementNS(SVG_NS, "path");
    p.setAttribute("d", d);
    s.append(p);
  }
  return s;
}

/** Bintang delapan (khatam) — dua persegi bertumpuk, garis atau isi. */
export function khatam(cls = "khatam") {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 100 100");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", cls);
  for (const rot of [0, 45]) {
    const r = document.createElementNS(SVG_NS, "rect");
    for (const [k, v] of Object.entries({ x: 20, y: 20, width: 60, height: 60, rx: 6, transform: `rotate(${rot} 50 50)` })) {
      r.setAttribute(k, String(v));
    }
    s.append(r);
  }
  return s;
}

/** Angka naik dari 0 ke target (sekali, saat data tampil). */
export function countUp(node, to, fmt = (v) => String(Math.round(v)), ms = 700) {
  const target = Number(to) || 0;
  if (reduceMotion() || target === 0) { node.textContent = fmt(target); return; }
  const t0 = performance.now();
  const step = (t) => {
    const k = Math.min(1, (t - t0) / ms);
    const e = 1 - Math.pow(1 - k, 3);
    node.textContent = fmt(target * e);
    if (k < 1) requestAnimationFrame(step);
  };
  node.textContent = fmt(0);
  requestAnimationFrame(step);
}

/** Jalankan ulang animasi masuk pada node (dipakai saat ganti halaman). */
export function enter(node) {
  node.classList.remove("enter");
  void node.offsetWidth; // paksa reflow agar animasi bisa diulang
  node.classList.add("enter");
}

/** Getar singkat (Android) sebagai umpan balik sukses/galat. */
export function haptic(pattern = 30) {
  try { navigator.vibrate?.(pattern); } catch { /* tidak didukung */ }
}

/** Riak sentuh untuk semua tombol — satu listener terdelegasi. */
export function installRipple(selector = ".btn, .chip, .scan-cta") {
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || reduceMotion()) return;
    const host = e.target.closest?.(selector);
    if (!host || host.disabled || host.getAttribute("aria-busy") === "true") return;
    const r = host.getBoundingClientRect();
    const d = Math.max(r.width, r.height) * 2.2;
    const dot = document.createElement("span");
    dot.className = "ripple";
    dot.setAttribute("aria-hidden", "true");
    dot.style.setProperty("--x", `${e.clientX - r.left}px`);
    dot.style.setProperty("--y", `${e.clientY - r.top}px`);
    dot.style.setProperty("--d", `${d}px`);
    host.append(dot);
    dot.addEventListener("animationend", () => dot.remove(), { once: true });
    setTimeout(() => dot.remove(), 900);
  }, { passive: true });
}

/** Tutup layar pembuka (#boot) dengan fade; minimal tampil sebentar agar tidak berkedip. */
const bootStart = performance.now();
export function dismissBoot(minMs = 450) {
  const b = document.getElementById("boot");
  if (!b || b.classList.contains("done")) return;
  const wait = Math.max(0, minMs - (performance.now() - bootStart));
  setTimeout(() => {
    b.classList.add("done");
    b.setAttribute("aria-hidden", "true");
    setTimeout(() => b.remove(), 600);
  }, wait);
}

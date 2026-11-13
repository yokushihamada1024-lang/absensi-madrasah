// Admin Web — router hash + layout. Token disimpan di sessionStorage (8 jam).
import { api, clearToken, configureApi, getToken, newNavigation, setToken, warmUp } from "./shared/api.js";
import { alertBox, busy, clear, el, errMsg, field, input } from "./ui.js";
import { dismissBoot, enter, installRipple, khatam } from "./shared/fx.js";
import { pageDashboard } from "./pages/dashboard.js";
import { pageSesi } from "./pages/sesi.js";
import { pageGuru } from "./pages/guru.js";
import { pageAbsensi } from "./pages/absensi.js";
import { pagePenggajian } from "./pages/penggajian.js";
import { pagePengaturan } from "./pages/pengaturan.js";
import { pageLog } from "./pages/log.js";

const TOKEN_KEY = "absensi_admin_token";
const root = document.getElementById("app");
const nav = document.getElementById("nav");
const who = document.getElementById("who");
const slowBanner = document.getElementById("slow-banner");
const avatar = document.getElementById("avatar");

function initials(name) {
  return String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

export const ctx = { user: null, cleanup: [] };

configureApi({
  storage: {
    get: () => sessionStorage.getItem(TOKEN_KEY),
    set: (t) => sessionStorage.setItem(TOKEN_KEY, t),
    clear: () => sessionStorage.removeItem(TOKEN_KEY),
  },
  slow: (on) => { slowBanner.hidden = !on; },
  unauthorized: () => { clearToken(); ctx.user = null; go("/login"); },
  // Data dari cache sudah tampil; versi terbaru dari server berbeda → gambar ulang diam-diam.
  // Jangan ganggu admin yang sedang mengisi form/dialog — versi baru tampil saat halaman dibuka lagi.
  revalidated: () => {
    const f = document.activeElement;
    if (document.querySelector("dialog[open]") || (f && root.contains(f) && f.matches("input, select, textarea"))) return;
    render();
  },
});

export function go(path) {
  if (location.hash !== "#" + path) location.hash = "#" + path;
  else render();
}

export function onLeave(fn) {
  ctx.cleanup.push(fn);
}

function runCleanup() {
  for (const fn of ctx.cleanup.splice(0)) {
    try { fn(); } catch { /* abaikan */ }
  }
}

/** Render ulang halaman aktif (menjalankan cleanup halaman lama dulu). */
export function refresh() {
  return render();
}

/** Ganti isi halaman. */
export function mount(...children) {
  clear(root).append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  dismissBoot();
}

let lastPath = null;

function pageLogin() {
  nav.hidden = true;
  root.classList.add("bare");
  const u = input({ autocomplete: "username", autocapitalize: "none", spellcheck: "false" });
  const p = input({ type: "password", autocomplete: "current-password" });
  const msg = el("div", { "aria-live": "polite" });
  const btn = el("button", { class: "btn btn-lg", type: "submit" }, "Masuk");
  const form = el("form", { class: "login" }, el("h1", {}, "Masuk"),
    el("p", { class: "lead" }, "Panel admin untuk sesi QR, data guru, dan penggajian."),
    field("Username", u), field("PIN", p), msg, btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clear(msg);
    busy(btn, true);
    try {
      const r = await api("/api/auth/login", { method: "POST", auth: false, body: { username: u.value.trim(), pin: p.value } });
      if (r.user.role !== "admin") {
        msg.append(alertBox("err", "Akun ini bukan admin."));
        return;
      }
      setToken(r.token);
      ctx.user = r.user;
      go("/dashboard");
    } catch (err) {
      msg.append(alertBox("err", errMsg(err)));
    } finally {
      busy(btn, false);
    }
  });
  mount(el("div", { class: "login-shell" },
    el("section", { class: "login-art" },
      el("div", { class: "brand" }, khatam(), "Absensi Madrasah"),
      el("div", {}, khatam("khatam big"),
        el("h2", {}, "Kehadiran guru, tercatat rapi setiap sesi."),
        el("p", {}, "Buka sesi, tampilkan QR yang berganti otomatis, dan rekap gaji di akhir bulan.")),
      el("span")),
    el("section", { class: "login-pane" }, form)));
  enter(form);
  u.focus();
}

const ROUTES = {
  "/dashboard": pageDashboard, "/sesi": pageSesi, "/guru": pageGuru, "/absensi": pageAbsensi,
  "/penggajian": pagePenggajian, "/pengaturan": pagePengaturan, "/log": pageLog,
};

async function render() {
  runCleanup();
  newNavigation(); // GET halaman sebelumnya dibatalkan & dibuang — tidak bisa menimpa halaman ini
  const path = (location.hash.slice(1) || "/dashboard").split("?")[0];
  if (path === "/login" || !getToken()) {
    if (path !== "/login") { go("/login"); return; }
    if (getToken()) { go("/dashboard"); return; }
    pageLogin();
    return;
  }
  nav.hidden = false;
  root.classList.remove("bare");
  for (const a of nav.querySelectorAll("a[data-route]")) a.classList.toggle("active", a.dataset.route === path);
  nav.querySelector("a.active")?.scrollIntoView({ block: "nearest", inline: "nearest" }); // menu HP bergulir ke halaman aktif
  try {
    if (!ctx.user) {
      ctx.user = await api("/api/me");
      if (ctx.user.role !== "admin") { clearToken(); go("/login"); return; }
    }
    who.textContent = ctx.user.name;
    avatar.textContent = initials(ctx.user.name);
    const page = ROUTES[path] || pageDashboard;
    const changed = path !== lastPath;
    lastPath = path;
    await page();
    if (changed) enter(root); // animasi masuk hanya saat pindah halaman, bukan saat segar otomatis
  } catch (err) {
    lastPath = null;
    mount(alertBox("err", errMsg(err)), el("button", { class: "btn", onclick: () => render() }, "Coba lagi"));
  }
}

document.getElementById("logout").addEventListener("click", () => {
  api("/api/auth/logout", { method: "POST" }).catch(() => {});
  clearToken();
  ctx.user = null;
  go("/login");
});

window.addEventListener("hashchange", render);
installRipple(".btn");
warmUp();
render();

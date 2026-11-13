// Admin Web — router hash + layout. Token disimpan di sessionStorage (8 jam).
import { api, clearToken, configureApi, getToken, setToken, warmUp } from "./shared/api.js";
import { alertBox, clear, el, errMsg, field, input } from "./ui.js";
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

export const ctx = { user: null, cleanup: [] };

configureApi({
  storage: {
    get: () => sessionStorage.getItem(TOKEN_KEY),
    set: (t) => sessionStorage.setItem(TOKEN_KEY, t),
    clear: () => sessionStorage.removeItem(TOKEN_KEY),
  },
  slow: (on) => { slowBanner.hidden = !on; },
  unauthorized: () => { clearToken(); ctx.user = null; go("/login"); },
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
}

function pageLogin() {
  nav.hidden = true;
  const u = input({ autocomplete: "username", autocapitalize: "none", spellcheck: "false" });
  const p = input({ type: "password", autocomplete: "current-password" });
  const msg = el("div");
  const btn = el("button", { class: "btn", type: "submit" }, "Masuk");
  const form = el("form", { class: "card login" }, el("h1", {}, "Admin Absensi"),
    field("Username", u), field("PIN", p), msg, btn);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clear(msg);
    btn.disabled = true;
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
      btn.disabled = false;
    }
  });
  mount(form);
  u.focus();
}

const ROUTES = {
  "/dashboard": pageDashboard, "/sesi": pageSesi, "/guru": pageGuru, "/absensi": pageAbsensi,
  "/penggajian": pagePenggajian, "/pengaturan": pagePengaturan, "/log": pageLog,
};

async function render() {
  runCleanup();
  const path = (location.hash.slice(1) || "/dashboard").split("?")[0];
  if (path === "/login" || !getToken()) {
    if (path !== "/login") { go("/login"); return; }
    if (getToken()) { go("/dashboard"); return; }
    pageLogin();
    return;
  }
  nav.hidden = false;
  for (const a of nav.querySelectorAll("a[data-route]")) a.classList.toggle("active", a.dataset.route === path);
  try {
    if (!ctx.user) {
      ctx.user = await api("/api/me");
      if (ctx.user.role !== "admin") { clearToken(); go("/login"); return; }
    }
    who.textContent = ctx.user.name;
    const page = ROUTES[path] || pageDashboard;
    await page();
  } catch (err) {
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
warmUp();
render();

// PWA Guru — vanilla JS; DOM dibangun lewat el()/textContent (tidak ada HTML mentah).
import { api, ApiError, clearToken, configureApi, getToken, setToken, warmUp } from "./shared/api.js";
import { clear, el, hhmm, periode, periodNow, rupiah, shiftPeriod, statusText, tanggal, tanggalPendek, todayWib }
  from "./shared/format.js";
import { CameraError, geoErrorKind, getPosition, startScanner, watchPosition } from "./scanner.js";

const TOKEN_KEY = "absensi_guru_token";
const LAST_CHOICE_KEY = "absensi_guru_last";
const SCAN_KEY = "absensi_guru_scan";

const root = document.getElementById("app");
const slowBanner = document.getElementById("slow-banner");
const netBanner = document.getElementById("net-banner");

const state = { user: null, meta: null, scan: null, result: null, cleanup: [], devFake: null, installEvt: null };

configureApi({
  storage: {
    get: () => localStorage.getItem(TOKEN_KEY),
    set: (t) => localStorage.setItem(TOKEN_KEY, t),
    clear: () => localStorage.removeItem(TOKEN_KEY),
  },
  slow: (on) => { slowBanner.hidden = !on; },
  unauthorized: () => { clearToken(); state.user = null; go("/login"); },
});

// --- util ------------------------------------------------------------------

function go(path) {
  if (location.hash !== "#" + path) location.hash = "#" + path;
  else render();
}

function runCleanup() {
  for (const fn of state.cleanup.splice(0)) {
    try { fn(); } catch { /* abaikan */ }
  }
}

function view(...children) {
  runCleanup();
  clear(root).append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  window.scrollTo(0, 0);
}

function errorBox(err, extraChildren = []) {
  const msg = err instanceof ApiError ? err.message : "Terjadi kesalahan. Coba lagi.";
  return el("div", { class: "alert alert-err", role: "alert" }, msg, ...extraChildren);
}

function loading(text = "Memuat…") {
  return el("p", { class: "muted center pad" }, el("span", { class: "spinner" }), " ", text);
}

function topbar(showBack = false) {
  const left = showBack
    ? el("button", { class: "btn btn-link", onclick: () => go("/") }, "‹ Beranda")
    : el("div", {}, el("div", { class: "who" }, state.user ? state.user.name : ""),
      el("div", { class: "date" }, tanggal(todayWib(), true)));
  return el("header", { class: "topbar" }, left,
    showBack ? el("span") : el("button", { class: "btn btn-link", onclick: logout }, "Keluar"));
}

function updateOnline() { netBanner.hidden = navigator.onLine; }
window.addEventListener("online", updateOnline);
window.addEventListener("offline", updateOnline);

async function ensureUser() {
  if (!state.user) state.user = await api("/api/me");
  return state.user;
}

async function ensureMeta() {
  if (!state.meta) state.meta = await api("/api/meta");
  return state.meta;
}

function logout() {
  api("/api/auth/logout", { method: "POST" }).catch(() => {});
  clearToken();
  state.user = null;
  state.meta = null;
  sessionStorage.removeItem(SCAN_KEY);
  go("/login");
}

// --- halaman: Login ----------------------------------------------------------

function pageLogin() {
  const user = el("input", { type: "text", id: "username", autocomplete: "username", autocapitalize: "none",
    spellcheck: "false", required: true, inputmode: "text" });
  const pin = el("input", { type: "password", id: "pin", autocomplete: "current-password", inputmode: "numeric",
    required: true, minlength: "6" });
  const msg = el("div");
  const btn = el("button", { class: "btn", type: "submit" }, "Masuk");
  const form = el("form", { class: "card", novalidate: true },
    el("label", { for: "username" }, "Username"), user,
    el("label", { for: "pin" }, "PIN"), pin,
    msg, el("div", { class: "stack" }, btn));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clear(msg);
    if (!user.value.trim() || pin.value.length < 6) {
      msg.append(el("div", { class: "alert alert-err" }, "Isi username dan PIN (minimal 6 karakter)."));
      return;
    }
    btn.disabled = true;
    try {
      const r = await api("/api/auth/login", { method: "POST", auth: false,
        body: { username: user.value.trim(), pin: pin.value } });
      if (r.user.role !== "guru") {
        msg.append(el("div", { class: "alert alert-err" }, "Akun admin tidak bisa absen. Pakai halaman admin."));
        return;
      }
      setToken(r.token);
      state.user = r.user;
      go("/");
    } catch (err) {
      msg.append(errorBox(err));
    } finally {
      btn.disabled = false;
    }
  });
  view(el("div", { class: "login-wrap" },
    el("img", { class: "logo", src: "icons/icon-192.png", alt: "" }),
    el("h1", { class: "center" }, "Absensi Guru"),
    el("p", { class: "muted center" }, "Masuk dengan username & PIN dari admin."),
    form));
  user.focus();
}

// --- halaman: Beranda --------------------------------------------------------

function sessionRow(s) {
  let pill;
  if (s.attended) {
    pill = el("span", { class: "pill " + (s.status === "late" ? "pill-late" : "pill-ok") },
      `Hadir ${s.time_hhmm} · ${statusText(s.status, s.late_min)}`);
  } else if (s.is_open) {
    pill = el("span", { class: "pill pill-open" }, "Dibuka — silakan scan");
  } else {
    pill = el("span", { class: "pill pill-idle" }, "Belum hadir");
  }
  return el("div", { class: "sess" }, el("span", { class: "name" }, s.name), pill);
}

function installCard() {
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return null;
  if (state.installEvt) {
    return el("div", { class: "card" }, el("p", {}, "Pasang aplikasi ini di layar utama agar mudah dibuka."),
      el("button", { class: "btn btn-ghost", onclick: async () => {
        state.installEvt.prompt();
        await state.installEvt.userChoice.catch(() => {});
        state.installEvt = null;
        render();
      } }, "Pasang Aplikasi"));
  }
  if (isIos) {
    return el("p", { class: "muted small center" },
      "Tip iPhone: buka di Safari → tombol Bagikan → “Tambahkan ke Layar Utama”.");
  }
  return null;
}

async function pageHome() {
  view(topbar(), loading());
  try {
    await ensureUser();
    const s = await api("/api/me/summary");
    const rate = s.current_rate === null ? "Belum diatur" : rupiah(s.current_rate);
    view(
      topbar(),
      el("section", { class: "card" },
        el("div", { class: "card-title" }, "Absensi hari ini"),
        el("div", { class: "sessions" }, s.today.sessions.map(sessionRow))),
      el("button", { class: "btn btn-xl", onclick: () => go("/scan") }, "Scan Absen"),
      el("section", { class: "card" },
        el("div", { class: "card-title" }, `Bulan ${s.period_label}`),
        el("div", { class: "stats" },
          el("div", { class: "stat" }, el("div", { class: "k" }, "Pertemuan"), el("div", { class: "v" }, s.meetings)),
          el("div", { class: "stat" }, el("div", { class: "k" }, "Tarif/pertemuan"), el("div", { class: "v" }, rate)),
          el("div", { class: "stat wide" }, el("div", { class: "k" }, "Estimasi gaji saat ini"),
            el("div", { class: "v big" }, rupiah(s.estimated_gross)),
            el("div", { class: "muted small" },
              s.period_status === "final" ? "Periode sudah final." : "Estimasi, final setelah periode ditutup admin."))),
        el("div", { class: "k muted small" }, "Tanggal hadir:"),
        s.dates.length
          ? el("div", { class: "dates" }, s.dates.map((d) => el("span", { class: "date-chip" }, tanggalPendek(d))))
          : el("p", { class: "muted small" }, "Belum ada kehadiran bulan ini.")),
      el("button", { class: "btn btn-ghost", onclick: () => go("/riwayat") }, "Lihat Riwayat"),
      installCard(),
    );
  } catch (err) {
    view(topbar(), errorBox(err), el("button", { class: "btn", onclick: () => render() }, "Coba lagi"));
  }
}

// --- halaman: Scan -------------------------------------------------------------

const HELP = {
  cameraDenied: () => el("div", { class: "alert alert-err", role: "alert" },
    el("h3", {}, "Izin kamera ditolak"),
    el("p", {}, "Kamera dibutuhkan untuk membaca QR. Cara mengaktifkan:"),
    el("ul", {},
      el("li", {}, "Android (Chrome): ketuk ikon gembok/pengaturan di sebelah alamat → Izin → Kamera → Izinkan."),
      el("li", {}, "iPhone: Pengaturan → Safari → Kamera → Izinkan. Jika dipasang di layar utama, buka ulang aplikasinya."),
    ), el("p", {}, "Lalu tekan “Coba lagi”.")),
  geoDenied: () => el("div", { class: "alert alert-err", role: "alert" },
    el("h3", {}, "Izin lokasi ditolak"),
    el("p", {}, "Lokasi dibutuhkan untuk memastikan Anda berada di madrasah. Cara mengaktifkan:"),
    el("ul", {},
      el("li", {}, "Android: aktifkan Lokasi (GPS) di panel atas, lalu ikon gembok di sebelah alamat → Izin → Lokasi → Izinkan."),
      el("li", {}, "iPhone: Pengaturan → Privasi & Keamanan → Layanan Lokasi → aktif; lalu Safari (atau Situs Web Safari) → “Saat Digunakan” dan aktifkan “Lokasi Akurat”."),
      el("li", {}, "iPhone (aplikasi di layar utama) sering meminta izin ulang — pilih “Izinkan”."),
    )),
  geoWeak: (acc) => el("div", { class: "alert alert-warn" },
    el("h3", {}, "Sinyal GPS lemah"),
    el("p", {}, acc ? `Akurasi saat ini ±${Math.round(acc)} m.` : "Lokasi belum didapat."),
    el("ul", {}, el("li", {}, "Pindah ke dekat jendela atau ke halaman."),
      el("li", {}, "Pastikan mode lokasi “Akurasi tinggi”/“Lokasi Akurat” aktif."),
      el("li", {}, "Tunggu beberapa detik lalu coba lagi."))),
  insecure: () => el("div", { class: "alert alert-err" }, "Kamera & lokasi hanya bisa dipakai lewat HTTPS."),
};

function scanErrorView(err) {
  const code = err instanceof ApiError ? err.code : "";
  const x = err instanceof ApiError ? err.extra : {};
  if (code === "OUT_OF_RANGE") {
    return el("div", { class: "alert alert-err", role: "alert" }, el("h3", {}, "Di luar jangkauan madrasah"),
      el("p", {}, `Anda ±${Math.round(x.distance_m)} m dari madrasah (maksimal ${Math.round(x.radius_m)} m).`),
      el("p", { class: "small" }, "Pastikan Anda berada di madrasah. Jika sudah di lokasi, tunggu GPS stabil lalu coba lagi."));
  }
  if (code === "LOW_ACCURACY") return HELP.geoWeak(x.accuracy_m);
  if (code === "ALREADY_ATTENDED") return el("div", { class: "alert alert-ok" }, "Anda sudah absen di sesi ini.");
  if (code === "TOKEN_EXPIRED") return el("div", { class: "alert alert-err" }, "QR sudah basi. Arahkan kamera ke QR terbaru di layar admin.");
  if (code === "STALE_LOCATION") return el("div", { class: "alert alert-err" }, "Data lokasi kedaluwarsa. Coba scan lagi.");
  return errorBox(err);
}

async function pageScan() {
  if (!navigator.onLine) {
    view(topbar(true), el("div", { class: "alert alert-err" }, "Butuh koneksi internet untuk absen."));
    return;
  }
  const video = el("video", { playsinline: true, muted: true, "aria-label": "Kamera" });
  const geoDot = el("span", { class: "dot" });
  const geoText = el("span", {}, "Mencari lokasi…");
  const camDot = el("span", { class: "dot" });
  const camText = el("span", {}, "Membuka kamera…");
  const msg = el("div");
  const camMsg = el("div");
  const geoMsg = el("div");
  const retry = el("button", { class: "btn hidden", onclick: () => render() }, "Coba lagi");
  const scannerBox = el("div", { class: "scanner" }, video, el("div", { class: "frame" }));
  const devPanel = el("div");
  view(topbar(true),
    el("h1", {}, "Scan QR Absen"),
    el("p", { class: "muted" }, "Arahkan kamera ke QR di layar admin."),
    scannerBox,
    el("div", { class: "status-line" }, camDot, camText),
    el("div", { class: "status-line" }, geoDot, geoText),
    camMsg, geoMsg, msg, retry, devPanel);

  let lastPos = null;
  let busy = false;
  let alive = true;
  state.cleanup.push(() => { alive = false; });

  // Lokasi diminta saat halaman scan dibuka (dari tombol "Scan Absen").
  const stopGeo = watchPosition((p) => {
    lastPos = p;
    const acc = p.coords.accuracy;
    geoDot.className = "dot " + (acc <= 75 ? "ok" : "warn");
    geoText.textContent = `Lokasi didapat (akurasi ±${Math.round(acc)} m)`;
  }, (e) => {
    const kind = geoErrorKind(e);
    if (kind === "denied") {
      geoDot.className = "dot err";
      geoText.textContent = "Izin lokasi ditolak";
      clear(geoMsg).append(HELP.geoDenied());
      retry.classList.remove("hidden");
    } else if (!lastPos) {
      geoDot.className = "dot warn";
      geoText.textContent = kind === "timeout" ? "GPS lemah, masih mencari…" : "Lokasi belum tersedia, masih mencari…";
    }
  });
  state.cleanup.push(stopGeo);

  async function freshPosition() {
    if (lastPos && Date.now() - lastPos.timestamp < 20_000) return lastPos;
    geoText.textContent = "Memperbarui lokasi…";
    return await getPosition();
  }

  async function submitScan(token, coords) {
    busy = true;
    clear(msg).append(loading("Memverifikasi…"));
    try {
      const r = await api("/api/attendance/scan", { method: "POST", body: { token, ...coords, client_ts: Date.now() } });
      state.scan = r;
      sessionStorage.setItem(SCAN_KEY, JSON.stringify(r));
      go("/konfirmasi");
    } catch (err) {
      clear(msg).append(scanErrorView(err));
      if (err instanceof ApiError && err.code === "ALREADY_ATTENDED") {
        msg.append(el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
      } else {
        retry.classList.remove("hidden");
      }
    } finally {
      busy = false;
    }
  }

  async function onCode(text) {
    if (busy || !alive) return;
    stopCam?.();
    camDot.className = "dot ok";
    camText.textContent = "QR terbaca";
    scannerBox.classList.add("hidden");
    let pos;
    try {
      pos = await freshPosition();
    } catch (e) {
      const kind = geoErrorKind(e);
      clear(msg).append(kind === "denied" ? HELP.geoDenied() : HELP.geoWeak(null));
      retry.classList.remove("hidden");
      return;
    }
    await submitScan(text.trim(), {
      lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy_m: pos.coords.accuracy, position_ts: pos.timestamp,
    });
  }

  let stopCam = null;
  try {
    stopCam = await startScanner(video, onCode);
    if (!alive) { stopCam(); return; }
    state.cleanup.push(() => stopCam && stopCam());
    camDot.className = "dot ok";
    camText.textContent = "Kamera aktif — arahkan ke QR";
  } catch (e) {
    camDot.className = "dot err";
    scannerBox.classList.add("hidden");
    if (e instanceof CameraError && e.kind === "denied") {
      camText.textContent = "Izin kamera ditolak";
      clear(camMsg).append(HELP.cameraDenied());
    } else if (e instanceof CameraError && e.kind === "insecure") {
      camText.textContent = "Kamera tidak tersedia";
      clear(camMsg).append(HELP.insecure());
    } else {
      camText.textContent = e.message || "Kamera tidak bisa dibuka";
    }
    retry.classList.remove("hidden");
  }

  // Mode pengembangan: hanya di localhost DAN hanya jika server ENV=dev mengizinkan.
  if (state.devFake) {
    const lat = el("input", { type: "number", step: "any", value: String(state.devFake.lat ?? "") });
    const lng = el("input", { type: "number", step: "any", value: String(state.devFake.lng ?? "") });
    devPanel.append(el("section", { class: "card dev" },
      el("strong", {}, "MODE DEV — lokasi palsu"),
      el("p", { class: "small" }, "Hanya muncul di localhost dengan server ENV=dev."),
      el("div", { class: "row" }, el("div", {}, el("label", {}, "Lat"), lat), el("div", {}, el("label", {}, "Lng"), lng)),
      el("button", { class: "btn btn-ghost", onclick: async () => {
        stopCam?.();
        try {
          const t = await api("/api/dev/qr-token");
          if (!t.token) { clear(msg).append(el("div", { class: "alert alert-err" }, "Tidak ada sesi aktif.")); return; }
          await submitScan(t.token, { lat: Number(lat.value), lng: Number(lng.value), accuracy_m: 10,
            position_ts: Date.now() });
        } catch (err) {
          clear(msg).append(errorBox(err));
        }
      } }, "Absen pakai token QR aktif (DEV)")));
  }
}

// --- halaman: Konfirmasi (pilih kelas & mapel) -------------------------------

function chipGroup(items, selected, onPick) {
  const buttons = items.map((name) => el("button", {
    class: "chip", type: "button", "aria-pressed": String(name === selected),
    onclick: () => {
      for (const b of buttons) b.setAttribute("aria-pressed", String(b === btnMap.get(name)));
      onPick(name);
    },
  }, name));
  const btnMap = new Map(items.map((n, i) => [n, buttons[i]]));
  return el("div", { class: "chips", role: "group" }, buttons);
}

async function pageConfirm() {
  if (!state.scan) {
    try { state.scan = JSON.parse(sessionStorage.getItem(SCAN_KEY) || "null"); } catch { state.scan = null; }
  }
  const scan = state.scan;
  if (!scan || new Date(scan.expires_at).getTime() < Date.now()) {
    sessionStorage.removeItem(SCAN_KEY);
    view(topbar(true), el("div", { class: "alert alert-err" }, "Waktu memilih kelas habis. Silakan scan ulang."),
      el("button", { class: "btn", onclick: () => go("/scan") }, "Scan ulang"));
    return;
  }
  view(topbar(true), loading());
  let meta;
  try { meta = await ensureMeta(); } catch (err) { view(topbar(true), errorBox(err)); return; }
  let last = {};
  try { last = JSON.parse(localStorage.getItem(LAST_CHOICE_KEY) || "{}"); } catch { /* abaikan */ }
  let kelas = meta.kelas.includes(last.kelas) ? last.kelas : null;
  let mapel = meta.mapel.includes(last.mapel) ? last.mapel : null;
  const msg = el("div");
  const save = el("button", { class: "btn btn-xl", disabled: !(kelas && mapel) }, "Simpan Absen");
  const refresh = () => { save.disabled = !(kelas && mapel); };
  const countdown = el("span", {});
  const tick = () => {
    const left = Math.max(0, Math.floor((new Date(scan.expires_at).getTime() - Date.now()) / 1000));
    countdown.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
    if (left <= 0) render();
  };
  tick();
  const timer = setInterval(tick, 1000);
  const late = scan.status_preview === "late";
  view(topbar(true),
    el("section", { class: "alert " + (late ? "alert-warn" : "alert-ok") },
      el("h3", {}, `QR valid — ${scan.session.name}`),
      el("p", {}, `Jam hadir ${hhmm(scan.scanned_at)} WIB · ${statusText(scan.status_preview, scan.late_min_preview)}`),
      el("p", { class: "small" }, "Jam hadir dihitung saat scan, bukan saat menyimpan. Sisa waktu memilih: ", countdown)),
    el("h2", {}, "Kelas"), chipGroup(meta.kelas, kelas, (v) => { kelas = v; refresh(); }),
    el("h2", { class: "pad-top" }, "Mata pelajaran"), chipGroup(meta.mapel, mapel, (v) => { mapel = v; refresh(); }),
    msg, el("div", { class: "card" }, save));
  state.cleanup.push(() => clearInterval(timer));
  save.addEventListener("click", async () => {
    save.disabled = true;
    clear(msg);
    try {
      const r = await api("/api/attendance/submit", { method: "POST", body: { ticket: scan.ticket, kelas, mapel } });
      localStorage.setItem(LAST_CHOICE_KEY, JSON.stringify({ kelas, mapel }));
      sessionStorage.removeItem(SCAN_KEY);
      state.scan = null;
      state.result = r;
      go("/selesai");
    } catch (err) {
      msg.append(errorBox(err));
      if (err instanceof ApiError && ["TICKET_EXPIRED", "TICKET_INVALID"].includes(err.code)) {
        msg.append(el("button", { class: "btn", onclick: () => go("/scan") }, "Scan ulang"));
      } else if (err instanceof ApiError && err.code === "ALREADY_ATTENDED") {
        msg.append(el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
      } else {
        save.disabled = false;
      }
    }
  });
}

// --- halaman: Selesai ---------------------------------------------------------

function pageDone() {
  const r = state.result;
  if (!r) { go("/"); return; }
  const late = r.status === "late";
  view(topbar(true),
    el("div", { class: "result-icon" + (late ? " late" : ""), "aria-hidden": "true" }, late ? "!" : "✓"),
    el("h1", { class: "center" }, "Absensi tersimpan"),
    el("p", { class: "center muted" }, statusText(r.status, r.late_min)),
    el("section", { class: "card" }, el("dl", { class: "kv" },
      el("dt", {}, "Tanggal"), el("dd", {}, tanggal(r.date, true)),
      el("dt", {}, "Sesi"), el("dd", {}, r.session_name || r.code),
      el("dt", {}, "Jam hadir"), el("dd", {}, `${r.time_hhmm} WIB`),
      el("dt", {}, "Status"), el("dd", {}, statusText(r.status, r.late_min)),
      el("dt", {}, "Kelas"), el("dd", {}, r.kelas),
      el("dt", {}, "Mapel"), el("dd", {}, r.mapel))),
    el("button", { class: "btn", onclick: () => go("/") }, "Kembali ke Beranda"));
}

// --- halaman: Riwayat ---------------------------------------------------------

async function pageHistory() {
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  const month = /^\d{4}-\d{2}$/.test(p.get("m") || "") ? p.get("m") : periodNow();
  view(topbar(true), loading());
  try {
    const s = await api(`/api/me/summary?month=${encodeURIComponent(month)}`);
    const nav = el("div", { class: "month-nav" },
      el("button", { class: "btn btn-ghost", onclick: () => go(`/riwayat?m=${shiftPeriod(month, -1)}`) }, "‹"),
      el("h2", {}, periode(month)),
      el("button", { class: "btn btn-ghost", disabled: month >= periodNow(),
        onclick: () => go(`/riwayat?m=${shiftPeriod(month, 1)}`) }, "›"));
    const items = s.attendance.map((a) => el("li", {},
      el("div", {}, el("div", {}, `${tanggal(a.date, true)}`),
        el("div", { class: "sub" }, `${a.code} · ${a.time_hhmm} · ${a.kelas} · ${a.mapel}`)),
      el("div", { class: "center" },
        el("span", { class: "pill " + (a.status === "late" ? "pill-late" : "pill-ok") },
          a.status === "late" ? `Telat ${a.late_min}m` : "Tepat"),
        el("div", { class: "sub" }, rupiah(a.rate_snapshot)))));
    view(topbar(true), nav,
      el("section", { class: "card" }, el("div", { class: "stats" },
        el("div", { class: "stat" }, el("div", { class: "k" }, "Pertemuan"), el("div", { class: "v" }, s.meetings)),
        el("div", { class: "stat" }, el("div", { class: "k" }, s.period_status === "final" ? "Gaji (final)" : "Estimasi gaji"),
          el("div", { class: "v" }, rupiah(s.estimated_gross))))),
      el("section", { class: "card" }, items.length ? el("ul", { class: "list" }, items)
        : el("p", { class: "muted" }, "Tidak ada kehadiran pada bulan ini.")));
  } catch (err) {
    view(topbar(true), errorBox(err));
  }
}

// --- router ---------------------------------------------------------------------

const ROUTES = { "/login": pageLogin, "/": pageHome, "/scan": pageScan, "/konfirmasi": pageConfirm,
  "/selesai": pageDone, "/riwayat": pageHistory };

function render() {
  const path = (location.hash.slice(1) || "/").split("?")[0];
  if (!getToken() && path !== "/login") { go("/login"); return; }
  if (getToken() && path === "/login") { go("/"); return; }
  (ROUTES[path] || pageHome)();
}

window.addEventListener("hashchange", render);
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); state.installEvt = e; });

async function boot() {
  updateOnline();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  if (getToken()) warmUp(); // bangunkan API Render lebih awal
  if (["localhost", "127.0.0.1"].includes(location.hostname)) {
    try {
      const c = await api("/api/dev/config", { auth: false });
      if (c.fake_location) state.devFake = c;
    } catch { /* bukan server dev */ }
  }
  render();
}

boot();

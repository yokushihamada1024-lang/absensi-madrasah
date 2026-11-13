// PWA Guru — vanilla JS; DOM dibangun lewat el()/textContent (tidak ada HTML mentah).
import { api, ApiError, clearToken, configureApi, getToken, setToken, warmUp } from "./shared/api.js";
import { clear, el, hhmm, periode, periodNow, rupiah, shiftPeriod, statusText, tanggal, tanggalPendek, todayWib,
  wibParts } from "./shared/format.js";
import { bars, busy, countUp, dismissBoot, enter, haptic, icon, installRipple, khatam, loadingBlock } from "./shared/fx.js";
import { CameraError, geoErrorKind, getPosition, startScanner, watchPosition } from "./scanner.js";

const TOKEN_KEY = "absensi_guru_token";
const LAST_CHOICE_KEY = "absensi_guru_last";
const SCAN_KEY = "absensi_guru_scan";

const root = document.getElementById("app");
const slowBanner = document.getElementById("slow-banner");
const netBanner = document.getElementById("net-banner");

const state = { user: null, meta: null, scan: null, result: null, cleanup: [], devFake: null, installEvt: null,
  buttonCheckin: false };

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

/** Ganti isi halaman. animate=false untuk pembaruan di halaman yang sama (mis. loading → data). */
function view(...children) {
  let animate = true;
  if (children[0] && children[0].__noAnim) { children.shift(); animate = false; }
  runCleanup();
  clear(root).append(...children.filter((c) => c !== null && c !== undefined && c !== false));
  if (animate) { enter(root); window.scrollTo(0, 0); }
  dismissBoot();
}
const SAME = { __noAnim: true };

function errorBox(err, extraChildren = []) {
  const msg = err instanceof ApiError ? err.message : "Terjadi kesalahan. Coba lagi.";
  return el("div", { class: "alert alert-err", role: "alert" }, msg, ...extraChildren);
}

const loading = (text = "Memuat…") => loadingBlock(text);

function topbar(showBack = false) {
  const left = showBack
    ? el("button", { class: "btn btn-link", onclick: () => go("/") }, icon("back"), "Beranda")
    : el("div", {}, el("div", { class: "who" }, state.user ? state.user.name : ""),
      el("div", { class: "date" }, tanggal(todayWib(), true)));
  return el("header", { class: "topbar" }, left,
    showBack ? el("span") : el("button", { class: "btn btn-link", onclick: logout }, "Keluar"));
}

function emptyState(text) {
  return el("div", { class: "empty" }, khatam(), el("p", {}, text));
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
    spellcheck: "false", required: true, inputmode: "text", placeholder: "mis. ahmad" });
  const pin = el("input", { type: "password", id: "pin", autocomplete: "current-password", inputmode: "numeric",
    required: true, minlength: "6", placeholder: "••••••" });
  const reveal = el("button", { class: "btn btn-link", type: "button", "aria-controls": "pin", "aria-pressed": "false" }, "Lihat");
  reveal.addEventListener("click", () => {
    const show = pin.type === "password";
    pin.type = show ? "text" : "password";
    reveal.textContent = show ? "Sembunyi" : "Lihat";
    reveal.setAttribute("aria-pressed", String(show));
    pin.focus();
  });
  const msg = el("div", { "aria-live": "polite" });
  const btn = el("button", { class: "btn btn-lg", type: "submit" }, "Masuk");
  const form = el("form", { class: "card login-card", novalidate: true },
    el("label", { for: "username" }, "Username"), user,
    el("label", { for: "pin" }, "PIN"), el("div", { class: "pin-wrap" }, pin, reveal),
    msg, el("div", { class: "stack" }, btn));
  const invalid = (on) => {
    user.setAttribute("aria-invalid", String(on && !user.value.trim()));
    pin.setAttribute("aria-invalid", String(on && pin.value.length < 6));
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clear(msg);
    if (!user.value.trim() || pin.value.length < 6) {
      invalid(true);
      msg.append(el("div", { class: "alert alert-err" }, "Isi username dan PIN (minimal 6 angka)."));
      haptic([20, 40, 20]);
      return;
    }
    invalid(false);
    busy(btn, true);
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
      haptic([20, 40, 20]);
    } finally {
      busy(btn, false);
    }
  });
  view(
    el("div", { class: "login-hero" }, khatam("mark"),
      el("h1", {}, "Absensi Guru"),
      el("p", {}, "Masuk dengan username dan PIN dari admin.")),
    form);
  user.focus();
}

// --- halaman: Beranda --------------------------------------------------------

/** Jam:menit WIB sekarang ("HH:MM"), untuk dibandingkan dengan jam sesi. */
function nowHhmm() {
  const p = wibParts(new Date());
  return `${String(p.hh).padStart(2, "0")}:${String(p.mm).padStart(2, "0")}`;
}

function sessionItem(s) {
  let cls = "";
  let pill;
  let meta;
  if (s.attended) {
    cls = "done" + (s.status === "late" ? " late" : "");
    pill = el("span", { class: "pill " + (s.status === "late" ? "pill-late" : "pill-ok") }, statusText(s.status, s.late_min));
    meta = `Hadir ${s.time_hhmm} WIB`;
  } else if (s.is_open) {
    cls = "open";
    pill = el("span", { class: "pill pill-open" }, "Dibuka");
    meta = state.buttonCheckin ? "Silakan scan atau konfirmasi sekarang" : "Silakan scan sekarang";
  } else if (s.end_hhmm && s.end_hhmm < nowHhmm()) {
    pill = el("span", { class: "pill pill-idle" }, "Tidak hadir");
    meta = `Sesi sudah selesai (${s.end_hhmm} WIB)`;
  } else {
    pill = el("span", { class: "pill pill-idle" }, "Belum hadir");
    meta = "Menunggu sesi dibuka";
  }
  return el("li", { class: cls }, el("span", { class: "node", "aria-hidden": "true" }),
    el("div", {}, el("div", { class: "name" }, s.name), el("div", { class: "meta" }, meta)), pill);
}

function installCard() {
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return null;
  if (state.installEvt) {
    return el("div", { class: "card install" }, el("p", {}, "Pasang di layar utama agar sekali ketuk langsung terbuka."),
      el("button", { class: "btn btn-ghost btn-sm", onclick: async () => {
        state.installEvt.prompt();
        await state.installEvt.userChoice.catch(() => {});
        state.installEvt = null;
        render();
      } }, icon("install"), "Pasang"));
  }
  if (isIos) {
    return el("p", { class: "muted small center" },
      "Tip iPhone: buka di Safari, ketuk Bagikan, lalu “Tambahkan ke Layar Utama”.");
  }
  return null;
}

function greeting() {
  return "Assalamu’alaikum,";
}

function liveClock() {
  const time = el("span", { class: "time", role: "timer", "aria-label": "Jam sekarang (WIB)" });
  const day = el("span", { class: "day" });
  let last = "";
  const tick = () => {
    const p = wibParts(new Date());
    const hm = `${String(p.hh).padStart(2, "0")}:${String(p.mm).padStart(2, "0")}`;
    if (hm === last) return; // DOM hanya disentuh saat menit berganti
    last = hm;
    time.textContent = hm;
    day.textContent = tanggal(todayWib(), true);
  };
  tick();
  // Cek tiap detik agar pergantian menit tepat waktu; saat aplikasi kembali dibuka, langsung disegarkan.
  const t = setInterval(tick, 1000);
  document.addEventListener("visibilitychange", tick);
  state.cleanup.push(() => { clearInterval(t); document.removeEventListener("visibilitychange", tick); });
  return el("div", { class: "clock" }, time, el("span", { class: "tz" }, "WIB"), day);
}

function homeHero() {
  return el("header", { class: "hero" },
    el("div", { class: "hero-top" },
      el("div", {}, el("p", { class: "greet" }, greeting()),
        el("p", { class: "name" }, state.user ? state.user.name : "")),
      el("button", { class: "btn btn-link", onclick: logout }, icon("logout"), "Keluar")),
    liveClock());
}

function scanButton(hint, alt) {
  return el("div", { class: "scan-wrap" },
    el("button", { class: "scan-cta", onclick: () => { haptic(15); go("/scan"); } },
      khatam("halo"), khatam("khatam"),
      el("span", { class: "label" }, icon("qr"), "Scan Absen")),
    hint || null, alt || null);
}

/** Tautan ke fallback tanpa QR (hanya muncul bila admin mengizinkan). */
function checkinLink(text = "Konfirmasi kehadiran tanpa QR") {
  return el("button", { class: "btn btn-link alt-link", onclick: () => { haptic(10); go("/hadir"); } }, icon("pin"), text);
}

const HOME_REFRESH_MS = 20_000;

async function pageHome() {
  // Kerangka langsung tampil (jam & tombol scan); data menyusul dan disegarkan berkala (realtime).
  const body = el("div", {}, loading("Memuat ringkasan…"));
  const hint = el("p", { class: "scan-hint", "aria-live": "polite" });
  const alt = el("div", { class: "scan-alt" });
  const renderShell = () => view(homeHero(), scanButton(hint, alt), body);
  if (state.user) renderShell(); // saat pertama buka, layar pembuka tetap tampil sampai profil dimuat
  try {
    await ensureUser();
    if (!root.contains(body)) renderShell();
  } catch (err) {
    view(errorBox(err), el("button", { class: "btn", onclick: () => render() }, "Coba lagi"));
    return;
  }

  let first = true;
  let lastKey = "";
  let alive = true;
  let timer = null;
  let inflight = false;
  let dayDone = false;

  // Hemat jam server (Render Free): segarkan hanya saat aplikasi terlihat, dan berhenti bila semua sesi
  // hari ini sudah selesai/sudah diabsen. Membuka ulang aplikasi tetap langsung memuat data terbaru.
  const isDayDone = (s) => s.today.sessions.every((x) => x.attended || (!x.is_open && x.end_hhmm < nowHhmm()));
  const schedule = () => {
    clearTimeout(timer);
    timer = null;
    if (alive && !dayDone && document.visibilityState === "visible") timer = setTimeout(load, HOME_REFRESH_MS);
  };

  async function load() {
    if (inflight) return;
    inflight = true;
    clearTimeout(timer);
    try {
      const s = await api("/api/me/summary");
      if (!alive) return;
      dayDone = isDayDone(s);
      // Hanya gambar ulang bila data berubah, agar tidak berkedip tiap penyegaran.
      state.buttonCheckin = !!s.button_checkin;
      const key = JSON.stringify([s.today, s.meetings, s.estimated_gross, s.dates, s.period_status, s.current_rate,
        s.button_checkin]);
      if (key !== lastKey) {
        lastKey = key;
        drawSummary(s, first);
        first = false;
      }
    } catch (err) {
      if (!alive) return;
      if (first) body.replaceChildren(errorBox(err), el("button", { class: "btn", onclick: () => render() }, "Coba lagi"));
    } finally {
      inflight = false;
      schedule();
    }
  }

  function drawSummary(s, animate) {
    const rate = s.current_rate === null ? "Belum diatur" : rupiah(s.current_rate);
    const open = s.today.sessions.find((x) => x.is_open && !x.attended);
    hint.textContent = open ? `${open.name} sedang dibuka — silakan scan` : "";
    alt.replaceChildren(...(open && s.button_checkin ? [checkinLink()] : []));
    const earn = el("div", { class: "v" }, rupiah(s.estimated_gross));
    const meetings = el("div", { class: "v" }, String(s.meetings));
    const enterCls = animate ? " enter" : "";
    body.replaceChildren(...[
      el("section", { class: "card" + enterCls },
        el("div", { class: "card-title" }, "Hari ini", el("span", { class: "sub" }, tanggalPendek(todayWib()))),
        s.today.sessions.length
          ? el("ol", { class: "timeline" }, s.today.sessions.map(sessionItem))
          : emptyState("Tidak ada sesi hari ini.")),
      el("section", { class: "card" + enterCls },
        el("div", { class: "card-title" }, `Bulan ${s.period_label}`,
          el("span", { class: "sub" }, s.period_status === "final" ? "Final" : "Berjalan")),
        el("div", { class: "earn" }, el("span", { class: "k" }, "Estimasi gaji saat ini"), earn,
          el("span", { class: "note" },
            s.period_status === "final" ? "Periode sudah ditutup admin." : "Angka final setelah admin menutup periode.")),
        el("div", { class: "stats" },
          el("div", { class: "stat" }, el("div", { class: "k" }, "Pertemuan"), meetings),
          el("div", { class: "stat" }, el("div", { class: "k" }, "Tarif per pertemuan"), el("div", { class: "v" }, rate))),
        el("div", { class: "dates-k" }, "Tanggal hadir"),
        s.dates.length
          ? el("div", { class: "dates" }, s.dates.map((d) => el("span", { class: "date-chip" }, tanggalPendek(d))))
          : el("p", { class: "muted small" }, "Belum ada kehadiran bulan ini.")),
      el("button", { class: "btn btn-ghost", onclick: () => go("/riwayat") }, icon("history"), "Lihat riwayat"),
      installCard(),
    ].filter(Boolean)); // replaceChildren mengubah null jadi teks "null"
    if (animate) {
      countUp(earn, s.estimated_gross, rupiah);
      countUp(meetings, s.meetings);
    }
  }

  // Segarkan segera saat aplikasi kembali dibuka / koneksi pulih; berhenti saat aplikasi ditinggal.
  const wake = () => {
    if (document.visibilityState !== "visible") { clearTimeout(timer); timer = null; return; }
    if (navigator.onLine) load();
  };
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
  state.cleanup.push(() => {
    alive = false;
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", wake);
    window.removeEventListener("online", wake);
  });
  await load();
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
    view(topbar(true), el("div", { class: "alert alert-err" }, "Tidak ada internet. Sambungkan dulu, lalu scan."));
    return;
  }
  const video = el("video", { playsinline: true, muted: true, "aria-label": "Kamera" });
  const geoDot = el("span", { class: "dot wait" });
  const geoText = el("span", {}, "Mencari lokasi…");
  const camDot = el("span", { class: "dot wait" });
  const camText = el("span", {}, "Membuka kamera…");
  const msg = el("div");
  const camMsg = el("div");
  const geoMsg = el("div");
  const retry = el("button", { class: "btn hidden", onclick: () => render() }, "Coba lagi");
  const scannerBox = el("div", { class: "scanner idle" }, video,
    el("div", { class: "frame" }, el("i"), el("i"), el("i"), el("i")), el("div", { class: "beam" }));
  const devPanel = el("div");
  view(topbar(true),
    el("div", { class: "page-head" }, el("h1", {}, "Scan QR absen"),
      el("p", {}, "Arahkan kamera ke QR di layar admin. Absen tercatat otomatis.")),
    scannerBox,
    el("div", { class: "status-list" },
      el("div", { class: "status-line" }, camDot, camText),
      el("div", { class: "status-line" }, geoDot, geoText)),
    camMsg, geoMsg, msg, retry,
    state.buttonCheckin ? el("div", { class: "alt-wrap" }, checkinLink("Kamera bermasalah? Konfirmasi tanpa QR")) : null,
    devPanel);

  let lastPos = null;
  let busyScan = false;
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
    busyScan = true;
    clear(msg).append(el("div", { class: "verify", role: "status" }, bars(5, { label: "" }),
      el("strong", {}, "Memverifikasi QR & lokasi…"), el("span", { class: "small" }, "Jangan tutup halaman ini.")));
    try {
      const r = await api("/api/attendance/scan", { method: "POST", body: { token, ...coords, client_ts: Date.now() } });
      state.scan = r;
      sessionStorage.setItem(SCAN_KEY, JSON.stringify(r));
      haptic(30);
      go("/konfirmasi");
    } catch (err) {
      haptic([20, 40, 20]);
      clear(msg).append(scanErrorView(err));
      if (err instanceof ApiError && err.code === "ALREADY_ATTENDED") {
        msg.append(el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
      } else {
        retry.classList.remove("hidden");
      }
    } finally {
      busyScan = false;
    }
  }

  async function onCode(text) {
    if (busyScan || !alive) return;
    stopCam?.();
    haptic(15);
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
    scannerBox.classList.remove("idle");
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
      el("strong", {}, "Mode dev — lokasi palsu"),
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
      } }, "Absen pakai token QR aktif (dev)")));
  }
}

// --- halaman: Konfirmasi kehadiran tanpa QR (fallback, bila diizinkan admin) ---------

async function pageCheckin() {
  if (!navigator.onLine) {
    view(topbar(true), el("div", { class: "alert alert-err" }, "Tidak ada internet. Sambungkan dulu, lalu coba lagi."));
    return;
  }
  view(topbar(true), loading("Memeriksa sesi…"));
  let summary;
  let active;
  try {
    [summary, active] = await Promise.all([api("/api/me/summary"), api("/api/sessions/active")]);
  } catch (err) {
    view(SAME, topbar(true), errorBox(err), el("button", { class: "btn", onclick: () => render() }, "Coba lagi"));
    return;
  }
  state.buttonCheckin = !!summary.button_checkin;
  const head = el("div", { class: "page-head" }, el("h1", {}, "Konfirmasi kehadiran"),
    el("p", {}, "Tanpa scan QR. Lokasi Anda tetap diperiksa dan harus berada di dalam radius madrasah."));
  const toScan = () => el("div", { class: "alt-wrap" },
    el("button", { class: "btn btn-link alt-link", onclick: () => go("/scan") }, icon("qr"), "Scan QR saja"));
  if (!summary.button_checkin) {
    view(SAME, topbar(true), head,
      el("div", { class: "alert alert-warn", role: "alert" }, "Absen tanpa QR sedang dinonaktifkan admin. Silakan scan QR."),
      el("button", { class: "btn", onclick: () => go("/scan") }, icon("qr"), "Scan QR"));
    return;
  }
  const attended = new Set(summary.today.sessions.filter((x) => x.attended).map((x) => x.code));
  const open = active.filter((x) => !attended.has(x.code));
  if (!open.length) {
    view(SAME, topbar(true), head,
      active.length
        ? el("div", { class: "alert alert-ok" }, "Anda sudah absen di sesi yang sedang dibuka.")
        : emptyState("Belum ada sesi yang dibuka admin."),
      el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
    return;
  }

  let picked = open[0];
  const geoDot = el("span", { class: "dot wait" });
  const geoText = el("span", {}, "Mencari lokasi…");
  const geoMsg = el("div");
  const msg = el("div");
  const confirmBtn = el("button", { class: "btn btn-xl" }, icon("check"), "Konfirmasi hadir");
  const sessionPick = open.length > 1
    ? [el("h2", { class: "section-h" }, "Sesi", el("span", { class: "sub" }, "Pilih satu")),
      chipGroup("Sesi", open.map((x) => x.name), picked.name, (v) => { picked = open.find((x) => x.name === v); })]
    : [el("section", { class: "card" }, el("div", { class: "card-title" }, picked.name,
      el("span", { class: "sub" }, `${picked.start_hhmm}–${picked.end_hhmm} WIB`)),
      el("p", { class: "muted small" }, "Sesi ini sedang dibuka. Jam hadir dihitung saat Anda menekan konfirmasi."))];

  let lastPos = null;
  let sending = false;
  const devPanel = el("div");
  if (state.devFake) {
    // Mode pengembangan: hanya di localhost DAN hanya jika server ENV=dev mengizinkan.
    const lat = el("input", { type: "number", step: "any", value: String(state.devFake.lat ?? "") });
    const lng = el("input", { type: "number", step: "any", value: String(state.devFake.lng ?? "") });
    devPanel.append(el("section", { class: "card dev" },
      el("strong", {}, "Mode dev — lokasi palsu"),
      el("div", { class: "row" }, el("div", {}, el("label", {}, "Lat"), lat), el("div", {}, el("label", {}, "Lng"), lng)),
      el("button", { class: "btn btn-ghost", onclick: () => {
        lastPos = { timestamp: Date.now(), coords: { latitude: Number(lat.value), longitude: Number(lng.value), accuracy: 10 } };
        geoDot.className = "dot ok";
        geoText.textContent = "Lokasi palsu (dev) dipakai";
        clear(geoMsg);
      } }, "Pakai lokasi palsu (dev)")));
  }

  view(SAME, topbar(true), head, ...sessionPick,
    el("div", { class: "status-list" }, el("div", { class: "status-line" }, geoDot, geoText)),
    geoMsg, msg, devPanel, toScan(), el("div", { class: "save-bar" }, confirmBtn));

  const stopGeo = watchPosition((p) => {
    lastPos = p;
    const acc = p.coords.accuracy;
    geoDot.className = "dot " + (acc <= 75 ? "ok" : "warn");
    geoText.textContent = `Lokasi didapat (akurasi ±${Math.round(acc)} m)`;
    clear(geoMsg);
  }, (e) => {
    const kind = geoErrorKind(e);
    if (kind === "denied") {
      geoDot.className = "dot err";
      geoText.textContent = "Izin lokasi ditolak";
      clear(geoMsg).append(HELP.geoDenied());
    } else if (!lastPos) {
      geoDot.className = "dot warn";
      geoText.textContent = kind === "timeout" ? "GPS lemah, masih mencari…" : "Lokasi belum tersedia, masih mencari…";
    }
  });
  state.cleanup.push(stopGeo);

  confirmBtn.addEventListener("click", async () => {
    if (sending) return;
    sending = true;
    busy(confirmBtn, true);
    clear(msg);
    try {
      let pos = lastPos;
      if (!pos || Date.now() - pos.timestamp >= 20_000) {
        geoText.textContent = "Memperbarui lokasi…";
        try {
          pos = await getPosition();
        } catch (e) {
          clear(msg).append(geoErrorKind(e) === "denied" ? HELP.geoDenied() : HELP.geoWeak(null));
          haptic([20, 40, 20]);
          return;
        }
      }
      clear(msg).append(el("div", { class: "verify", role: "status" }, bars(5, { label: "" }),
        el("strong", {}, "Memverifikasi lokasi…"), el("span", { class: "small" }, "Jangan tutup halaman ini.")));
      const r = await api("/api/attendance/confirm", { method: "POST", body: {
        session_id: picked.session_id, lat: pos.coords.latitude, lng: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy, position_ts: pos.timestamp, client_ts: Date.now() } });
      state.scan = r;
      sessionStorage.setItem(SCAN_KEY, JSON.stringify(r));
      haptic(30);
      go("/konfirmasi");
    } catch (err) {
      haptic([20, 40, 20]);
      clear(msg).append(scanErrorView(err));
      if (err instanceof ApiError && err.code === "ALREADY_ATTENDED") {
        msg.append(el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
      }
    } finally {
      sending = false;
      busy(confirmBtn, false);
    }
  });
}

// --- halaman: Konfirmasi (pilih kelas & mapel) -------------------------------

function chipGroup(label, items, selected, onPick) {
  const buttons = items.map((name) => el("button", {
    class: "chip", type: "button", "aria-pressed": String(name === selected),
    onclick: () => {
      for (const b of buttons) b.setAttribute("aria-pressed", String(b === btnMap.get(name)));
      haptic(8);
      onPick(name);
    },
  }, name));
  const btnMap = new Map(items.map((n, i) => [n, buttons[i]]));
  return el("div", { class: "chips", role: "group", "aria-label": label }, buttons);
}

async function pageConfirm() {
  if (!state.scan) {
    try { state.scan = JSON.parse(sessionStorage.getItem(SCAN_KEY) || "null"); } catch { state.scan = null; }
  }
  const scan = state.scan;
  const viaButton = !!scan && scan.method === "button";
  const again = () => (viaButton
    ? el("button", { class: "btn", onclick: () => go("/hadir") }, icon("pin"), "Konfirmasi ulang")
    : el("button", { class: "btn", onclick: () => go("/scan") }, icon("qr"), "Scan ulang"));
  if (!scan || new Date(scan.expires_at).getTime() < Date.now()) {
    sessionStorage.removeItem(SCAN_KEY);
    view(topbar(true), el("div", { class: "alert alert-err" },
      `Waktu memilih kelas habis. Silakan ${viaButton ? "konfirmasi" : "scan"} ulang.`), again());
    return;
  }
  view(topbar(true), loading());
  let meta;
  try { meta = await ensureMeta(); } catch (err) { view(SAME, topbar(true), errorBox(err)); return; }
  let last = {};
  try { last = JSON.parse(localStorage.getItem(LAST_CHOICE_KEY) || "{}"); } catch { /* abaikan */ }
  let kelas = meta.kelas.includes(last.kelas) ? last.kelas : null;
  let mapel = meta.mapel.includes(last.mapel) ? last.mapel : null;
  const msg = el("div");
  const save = el("button", { class: "btn btn-xl", disabled: !(kelas && mapel) }, icon("check"), "Simpan absen");
  const refresh = () => { save.disabled = !(kelas && mapel); };
  const countdown = el("span", {});
  const timerPill = el("span", { class: "timer" }, icon("clock"), countdown);
  const tick = () => {
    const left = Math.max(0, Math.floor((new Date(scan.expires_at).getTime() - Date.now()) / 1000));
    countdown.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} tersisa`;
    timerPill.classList.toggle("low", left <= 30);
    if (left <= 0) render();
  };
  tick();
  const timer = setInterval(tick, 1000);
  const late = scan.status_preview === "late";
  view(SAME, topbar(true),
    el("section", { class: "ticket" + (late ? " late" : "") },
      el("h3", {}, `${viaButton ? "Lokasi valid" : "QR valid"} · ${scan.session.name}`),
      el("p", {}, `Jam hadir ${hhmm(scan.scanned_at)} WIB — ${statusText(scan.status_preview, scan.late_min_preview)}`),
      el("p", { class: "small" }, `Jam hadir dihitung saat ${viaButton ? "konfirmasi" : "scan"}, bukan saat menyimpan.`),
      timerPill),
    el("h2", { class: "section-h" }, "Kelas", el("span", { class: "sub" }, "Pilih satu")),
    chipGroup("Kelas", meta.kelas, kelas, (v) => { kelas = v; refresh(); }),
    el("h2", { class: "section-h" }, "Mata pelajaran", el("span", { class: "sub" }, "Pilih satu")),
    chipGroup("Mata pelajaran", meta.mapel, mapel, (v) => { mapel = v; refresh(); }),
    msg, el("div", { class: "save-bar" }, save));
  state.cleanup.push(() => clearInterval(timer));
  save.addEventListener("click", async () => {
    busy(save, true);
    clear(msg);
    try {
      const r = await api("/api/attendance/submit", { method: "POST", body: { ticket: scan.ticket, kelas, mapel } });
      localStorage.setItem(LAST_CHOICE_KEY, JSON.stringify({ kelas, mapel }));
      sessionStorage.removeItem(SCAN_KEY);
      state.scan = null;
      state.result = r;
      haptic([30, 60, 30]);
      go("/selesai");
    } catch (err) {
      busy(save, false);
      haptic([20, 40, 20]);
      msg.append(errorBox(err));
      if (err instanceof ApiError && ["TICKET_EXPIRED", "TICKET_INVALID"].includes(err.code)) {
        save.disabled = true;
        msg.append(again());
      } else if (err instanceof ApiError && err.code === "ALREADY_ATTENDED") {
        save.disabled = true;
        msg.append(el("button", { class: "btn", onclick: () => go("/") }, "Ke Beranda"));
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
    el("div", { class: "done" },
      el("div", { class: "badge" + (late ? " late" : ""), "aria-hidden": "true" },
        el("span", { class: "ring" }), khatam(),
        late ? el("span", { class: "bang" }, "!") : icon("check", "mark")),
      el("h1", {}, "Absensi tersimpan"),
      el("p", { class: "status" }, `${statusText(r.status, r.late_min)} · ${r.time_hhmm} WIB`)),
    el("section", { class: "card receipt" }, el("dl", { class: "kv" },
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
  const nav = el("div", { class: "month-nav" },
    el("button", { class: "btn btn-ghost", "aria-label": "Bulan sebelumnya",
      onclick: () => go(`/riwayat?m=${shiftPeriod(month, -1)}`) }, icon("back")),
    el("h2", {}, periode(month)),
    el("button", { class: "btn btn-ghost", "aria-label": "Bulan berikutnya", disabled: month >= periodNow(),
      onclick: () => go(`/riwayat?m=${shiftPeriod(month, 1)}`) }, icon("next")));
  view(topbar(true), nav, loading());
  try {
    const s = await api(`/api/me/summary?month=${encodeURIComponent(month)}`);
    const items = s.attendance.map((a) => el("li", {},
      el("div", {}, el("div", { class: "when" }, tanggal(a.date, true)),
        el("div", { class: "sub" }, `${a.code} · ${a.time_hhmm} · ${a.kelas} · ${a.mapel}`)),
      el("div", { class: "end" },
        el("span", { class: "pill " + (a.status === "late" ? "pill-late" : "pill-ok") },
          a.status === "late" ? `Telat ${a.late_min}m` : "Tepat"),
        el("span", { class: "amt" }, rupiah(a.rate_snapshot)))));
    const gross = el("div", { class: "v" }, rupiah(0));
    view(SAME, topbar(true), nav,
      el("section", { class: "card enter" }, el("div", { class: "stats" },
        el("div", { class: "stat" }, el("div", { class: "k" }, "Pertemuan"), el("div", { class: "v" }, s.meetings)),
        el("div", { class: "stat" }, el("div", { class: "k" }, s.period_status === "final" ? "Gaji (final)" : "Estimasi gaji"),
          gross))),
      el("section", { class: "card enter" }, items.length ? el("ul", { class: "list" }, items)
        : emptyState("Tidak ada kehadiran pada bulan ini.")));
    countUp(gross, s.estimated_gross, rupiah);
  } catch (err) {
    view(SAME, topbar(true), nav, errorBox(err));
  }
}

// --- router ---------------------------------------------------------------------

const ROUTES = { "/login": pageLogin, "/": pageHome, "/scan": pageScan, "/hadir": pageCheckin, "/konfirmasi": pageConfirm,
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
  installRipple(".btn, .chip");
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

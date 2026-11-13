// Sesi & QR: buka/tutup sesi, QR besar yang berputar, countdown, indikator koneksi, Wake Lock.
import { api } from "../shared/api.js";
import { hhmm, tanggal, todayWib } from "../shared/format.js";
import { mount, onLeave, refresh } from "../app.js";
import { alertBox, confirmDialog, el, loading, statusPill, table, toast, toastErr } from "../ui.js";

export async function pageSesi() {
  mount(el("h1", {}, "Sesi & QR"), loading());
  const data = await api("/api/admin/sessions/today");
  const open = data.sessions.find((s) => s.session?.is_open);
  if (open) return showQr(open);

  const rows = data.sessions.map((s) => {
    const btn = el("button", { class: "btn btn-lg", disabled: !data.location_set }, `Mulai ${s.name}`);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        await api("/api/admin/sessions/open", { method: "POST", body: { code: s.code } });
        toast(`${s.name} dibuka.`);
        refresh();
      } catch (err) {
        toastErr(err);
        btn.disabled = false;
      }
    });
    const info = s.session ? `Ditutup ${s.session.closed_at ? hhmm(s.session.closed_at) : ""} · ${s.attended} hadir` : "Belum dibuka";
    return el("div", { class: "card" }, el("h2", {}, `${s.name} — ${s.start_hhmm}–${s.end_hhmm} WIB`),
      el("p", { class: "muted" }, info), btn);
  });
  mount(
    el("h1", {}, "Sesi & QR"),
    el("p", { class: "muted" }, `${tanggal(todayWib(), true)} · Buka sesi ≥5 menit sebelum jam mulai. Halaman QR harus tetap terbuka selama sesi.`),
    data.location_set ? null : alertBox("warn", "Isi koordinat madrasah di ", el("a", { href: "#/pengaturan" }, "Pengaturan"),
      " sebelum membuka sesi."),
    el("div", { class: "grid grid-2" }, rows),
  );
}

function showQr(item) {
  const s = item.session;
  const img = el("img", { alt: "QR absensi", width: "600", height: "600" });
  const box = el("div", { class: "qr-box" }, el("div", { class: "big-title" }, `${item.name} · ${s.start_hhmm}–${s.end_hhmm} WIB`), img);
  const countdown = el("span", { class: "countdown" }, "–");
  const conn = el("span", { class: "conn" }, "Menghubungkan…");
  const wake = el("span", { class: "muted small" }, "");
  box.append(el("div", { class: "qr-meta" }, el("span", {}, "QR berganti dalam ", countdown), conn));
  const listWrap = el("div", {}, loading());
  const closeBtn = el("button", { class: "btn btn-danger" }, "Tutup Sesi");
  const fsBtn = el("button", { class: "btn btn-ghost" }, "Layar penuh");
  mount(
    el("h1", {}, "Sesi & QR"),
    el("div", { class: "qr-stage" },
      el("div", {}, box, el("div", { class: "toolbar" }, fsBtn, closeBtn, wake)),
      el("div", { class: "card" }, el("h2", {}, "Baru absen"), listWrap)),
  );

  let alive = true;
  let timer = null;
  let expiresAt = 0; // ms, jam server
  let offset = 0; // server - lokal
  let lastUrl = null;
  let failing = false;

  const setConn = (ok, text) => {
    conn.className = "conn " + (ok ? "ok" : "err");
    conn.textContent = text;
    box.classList.toggle("stale", !ok);
  };

  async function poll() {
    if (!alive) return;
    try {
      const q = await api(`/api/admin/sessions/${s.session_id}/qr`);
      if (!alive) return;
      offset = new Date(q.server_time).getTime() - Date.now();
      expiresAt = new Date(q.expires_at).getTime();
      const url = URL.createObjectURL(new Blob([q.svg], { type: "image/svg+xml" }));
      img.src = url;
      if (lastUrl) URL.revokeObjectURL(lastUrl);
      lastUrl = url;
      failing = false;
      setConn(true, "Terhubung");
      const wait = Math.max(500, expiresAt - (Date.now() + offset) + 300);
      timer = setTimeout(poll, wait);
    } catch (err) {
      if (!alive) return;
      if (err.code === "SESSION_CLOSED") { refresh(); return; }
      failing = true;
      setConn(false, "Koneksi terputus — QR mungkin basi");
      timer = setTimeout(poll, 5000);
    }
  }

  const clock = setInterval(() => {
    if (!expiresAt) return;
    const left = Math.max(0, Math.ceil((expiresAt - (Date.now() + offset)) / 1000));
    countdown.textContent = `${left} dtk`;
    // Watchdog: QR di layar sudah lewat masa berlakunya tapi belum ada yang baru.
    if (Date.now() + offset > expiresAt + 3000 && !failing) setConn(false, "Koneksi terputus — QR mungkin basi");
  }, 250);

  async function refreshList() {
    try {
      const rows = (await api(`/api/admin/attendance?date=${todayWib()}&include_voided=false`))
        .filter((a) => a.session_id === s.session_id)
        .sort((a, b) => b.scanned_at.localeCompare(a.scanned_at));
      if (!alive) return;
      listWrap.replaceChildren(el("p", { class: "muted" }, `${rows.length} guru hadir`), table([
        { label: "Jam", render: (a) => a.time_hhmm },
        { label: "Guru", render: (a) => a.teacher_name },
        { label: "Status", render: (a) => statusPill(a.status, a.late_min) },
      ], rows, { empty: "Belum ada." }));
    } catch { /* indikator koneksi sudah ditangani polling QR */ }
  }
  const listTimer = setInterval(refreshList, 15_000);

  // Wake Lock: layar tidak boleh mati selama sesi.
  let lock = null;
  async function acquireWake() {
    try {
      if ("wakeLock" in navigator && document.visibilityState === "visible") {
        lock = await navigator.wakeLock.request("screen");
        wake.textContent = "Layar dijaga tetap menyala.";
      } else if (!("wakeLock" in navigator)) {
        wake.textContent = "Browser tidak mendukung penjaga layar — matikan sleep/screensaver secara manual.";
      }
    } catch {
      wake.textContent = "Penjaga layar tidak aktif — matikan sleep/screensaver secara manual.";
    }
  }
  const onVis = () => { if (document.visibilityState === "visible") { acquireWake(); if (!timer) poll(); } };
  document.addEventListener("visibilitychange", onVis);

  fsBtn.addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else box.requestFullscreen?.().catch(() => {});
  });
  closeBtn.addEventListener("click", async () => {
    if (!(await confirmDialog("Tutup sesi?", `Guru tidak bisa lagi absen di ${item.name} setelah sesi ditutup.`, "Tutup Sesi"))) return;
    try {
      await api(`/api/admin/sessions/${s.session_id}/close`, { method: "POST" });
      toast(`${item.name} ditutup.`);
      refresh();
    } catch (err) {
      toastErr(err);
    }
  });

  onLeave(() => {
    alive = false;
    clearTimeout(timer);
    clearInterval(clock);
    clearInterval(listTimer);
    document.removeEventListener("visibilitychange", onVis);
    if (lock) lock.release().catch(() => {});
    if (lastUrl) URL.revokeObjectURL(lastUrl);
  });

  poll();
  refreshList();
  acquireWake();
}

import { api } from "../shared/api.js";
import { tanggal, todayWib } from "../shared/format.js";
import { go, mount, onLeave, refresh } from "../app.js";
import { alertBox, el, loading, statusPill, table } from "../ui.js";

export async function pageDashboard() {
  mount(el("h1", {}, "Dashboard Hari Ini"), loading());
  const today = todayWib();
  const [sess, att, attempts] = await Promise.all([
    api("/api/admin/sessions/today"),
    api(`/api/admin/attendance?date=${today}&include_voided=false`),
    api(`/api/admin/attempts?date=${today}`),
  ]);
  const cards = sess.sessions.map((s) => {
    const open = s.session?.is_open;
    const state = !s.session ? el("span", { class: "pill pill-idle" }, "Belum dibuka")
      : open ? el("span", { class: "pill pill-info" }, "Terbuka") : el("span", { class: "pill pill-idle" }, "Ditutup");
    return el("div", { class: "card stat" },
      el("div", { class: "k" }, `${s.name} (${s.start_hhmm}–${s.end_hhmm})`),
      el("div", { class: "v" }, `${s.attended} hadir`), state);
  });
  mount(
    el("h1", {}, "Dashboard Hari Ini"),
    el("p", { class: "muted" }, tanggal(today, true)),
    sess.location_set ? null : alertBox("warn", "Koordinat madrasah belum diisi — sesi tidak bisa dibuka. ",
      el("a", { href: "#/pengaturan" }, "Buka Pengaturan")),
    el("div", { class: "grid grid-3" }, ...cards,
      el("div", { class: "card stat" }, el("div", { class: "k" }, "Percobaan gagal hari ini"),
        el("div", { class: "v" }, attempts.length),
        el("a", { href: "#/log" }, "Lihat log"))),
    el("div", { class: "toolbar" }, el("button", { class: "btn btn-lg", onclick: () => go("/sesi") }, "Buka layar Sesi & QR")),
    el("h2", {}, "Sudah absen hari ini"),
    table([
      { label: "Jam", render: (a) => a.time_hhmm },
      { label: "Guru", render: (a) => a.teacher_name },
      { label: "Sesi", render: (a) => a.session_name },
      { label: "Kelas", render: (a) => a.kelas },
      { label: "Mapel", render: (a) => a.mapel },
      { label: "Status", render: (a) => statusPill(a.status, a.late_min) },
      { label: "Sumber", render: (a) => (a.source === "manual" ? "Manual" : "Scan") },
    ], att.slice().sort((x, y) => x.scanned_at.localeCompare(y.scanned_at)), { empty: "Belum ada yang absen." }),
  );
  // Segarkan tiap 60 dtk; refresh() menjalankan cleanup sehingga timer tidak menumpuk.
  const t = setTimeout(() => refresh(), 60_000);
  onLeave(() => clearTimeout(t));
}

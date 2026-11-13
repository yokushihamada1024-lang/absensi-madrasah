import { api } from "../shared/api.js";
import { tanggal, todayWib } from "../shared/format.js";
import { go, mount, onLeave, refresh } from "../app.js";
import { act, alertBox, el, icon, loading, statusPill, table } from "../ui.js";
import { countUp } from "../shared/fx.js";

// Angka hanya dianimasikan saat nilainya berubah — segar otomatis tiap menit tidak membuatnya berkedip.
const shown = new Map();
function counter(key, n, suffix = "") {
  const v = el("div", { class: "v" });
  const fmt = (x) => `${Math.round(x)}${suffix}`;
  if (shown.get(key) === n) v.textContent = fmt(n);
  else countUp(v, n, fmt);
  shown.set(key, n);
  return v;
}

export async function pageDashboard() {
  mount(el("h1", {}, "Hari ini"), loading());
  const today = todayWib();
  const [sess, att, attempts] = await Promise.all([
    api("/api/admin/sessions/today"),
    api(`/api/admin/attendance?date=${today}&include_voided=false`),
    api(`/api/admin/attempts?date=${today}`),
  ]);
  const cards = sess.sessions.map((s) => {
    const open = s.session?.is_open;
    const state = !s.session ? el("span", { class: "pill pill-idle" }, "Belum dibuka")
      : open ? el("span", { class: "pill pill-info live" }, "Terbuka") : el("span", { class: "pill pill-idle" }, "Ditutup");
    return el("div", { class: "card stat" + (open ? " is-live" : "") },
      el("div", { class: "stat-top" }, el("span", { class: "stat-ico" }, icon("clock")),
        el("div", { class: "grow" }, el("div", { class: "k" }, s.name), el("div", { class: "muted small" }, `${s.start_hhmm}–${s.end_hhmm} WIB`)),
        state),
      counter(s.code, s.attended, " hadir"));
  });
  const failed = attempts.length;
  const failCard = el("div", { class: "card stat " + (failed ? "tone-warn" : "tone-ok") },
    el("div", { class: "stat-top" }, el("span", { class: "stat-ico" }, icon(failed ? "alert" : "shield")),
      el("div", { class: "grow" }, el("div", { class: "k" }, "Percobaan gagal"),
        el("div", { class: "muted small" }, failed ? "Periksa alasannya di log" : "Belum ada masalah hari ini"))),
    el("div", { class: "stat-bottom" }, counter("_attempts", failed),
      act("arrow", "Lihat log", { size: "sm", variant: failed ? "danger" : "soft", onclick: () => go("/log") })));
  mount(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Hari ini"), el("p", { class: "muted" }, tanggal(today, true))),
      act("qr", "Buka layar Sesi & QR", { variant: "primary", size: "lg", onclick: () => go("/sesi") })),
    sess.location_set ? null : alertBox("warn", "Koordinat madrasah belum diisi — sesi tidak bisa dibuka. ",
      el("a", { href: "#/pengaturan" }, "Buka Pengaturan")),
    el("div", { class: "grid grid-3" }, ...cards, failCard),
    el("h2", {}, "Sudah absen hari ini"),
    table([
      { label: "Jam", render: (a) => a.time_hhmm },
      { label: "Guru", render: (a) => a.teacher_name },
      { label: "Sesi", render: (a) => a.session_name },
      { label: "Kelas", render: (a) => a.kelas },
      { label: "Mapel", render: (a) => a.mapel },
      { label: "Status", render: (a) => statusPill(a.status, a.late_min) },
      { label: "Sumber", render: (a) => ({ manual: "Manual", button: "Tombol" }[a.source] || "Scan") },
    ], att.slice().sort((x, y) => x.scanned_at.localeCompare(y.scanned_at)), { empty: "Belum ada yang absen." }),
  );
  // Segarkan tiap 60 dtk; refresh() menjalankan cleanup sehingga timer tidak menumpuk.
  const t = setTimeout(() => refresh(), 60_000);
  onLeave(() => clearTimeout(t));
}

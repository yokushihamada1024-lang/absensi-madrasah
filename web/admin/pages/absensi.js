// Absensi: filter, input manual, void dengan alasan.
import { api } from "../shared/api.js";
import { rupiah, tanggal, todayWib } from "../shared/format.js";
import { mount, refresh } from "../app.js";
import { askReason, el, field, input, loading, modal, select, statusPill, table, toast, toastErr } from "../ui.js";

function readFilters() {
  const p = new URLSearchParams(location.hash.split("?")[1] || "");
  const today = todayWib();
  return { from: p.get("from") || today, to: p.get("to") || today, user_id: p.get("user_id") || "" };
}

async function manualEntry(gurus, meta) {
  const user = select([["", "— pilih guru —"], ...gurus.map((g) => [g.user_id, g.name])], "");
  const date = input({ type: "date", value: todayWib(), max: todayWib() });
  const code = select(meta.session_defs.map((d) => [d.code, `${d.name} (${d.start_hhmm}–${d.end_hhmm})`]), meta.session_defs[0]?.code);
  const kelas = select(meta.kelas, meta.kelas[0]);
  const mapel = select(meta.mapel, meta.mapel[0]);
  const time = input({ type: "time" });
  const reason = el("textarea", { maxlength: "500" });
  const body = await modal({
    title: "Input absensi manual",
    build: (b) => b.append(
      field("Guru", user), el("div", { class: "inline" }, field("Tanggal", date), field("Sesi", code)),
      el("div", { class: "inline" }, field("Kelas", kelas), field("Mata pelajaran", mapel)),
      field("Jam hadir (opsional)", time, "Kosongkan = jam mulai sesi (tepat waktu). Status telat dihitung otomatis."),
      field("Alasan (wajib)", reason)),
    collect: () => {
      if (!user.value) throw new Error("Pilih guru.");
      if (!reason.value.trim()) throw new Error("Alasan wajib diisi.");
      return { user_id: user.value, date: date.value, code: code.value, kelas: kelas.value, mapel: mapel.value,
        time: time.value || null, reason: reason.value.trim() };
    },
  });
  if (!body) return;
  try {
    await api("/api/admin/attendance/manual", { method: "POST", body });
    toast("Absensi manual disimpan.");
    refresh();
  } catch (err) { toastErr(err); }
}

async function voidRow(a) {
  const reason = await askReason("Void absensi?",
    `${a.teacher_name} · ${tanggal(a.date)} · ${a.session_name} · ${a.kelas}/${a.mapel}. Baris tidak dihapus, hanya ditandai batal.`, "Void");
  if (!reason) return;
  try {
    await api(`/api/admin/attendance/${a.attendance_id}/void`, { method: "POST", body: { reason } });
    toast("Absensi di-void.");
    refresh();
  } catch (err) { toastErr(err); }
}

export async function pageAbsensi() {
  mount(el("h1", {}, "Absensi"), loading());
  const f = readFilters();
  const [users, meta, rows] = await Promise.all([
    api("/api/admin/users"),
    api("/api/meta"),
    api(`/api/admin/attendance?from=${f.from}&to=${f.to}${f.user_id ? `&user_id=${encodeURIComponent(f.user_id)}` : ""}`),
  ]);
  const gurus = users.filter((u) => u.role === "guru").sort((a, b) => a.name.localeCompare(b.name));
  const from = input({ type: "date", value: f.from });
  const to = input({ type: "date", value: f.to });
  const who = select([["", "Semua guru"], ...gurus.map((g) => [g.user_id, g.name])], f.user_id);
  const apply = () => {
    const q = new URLSearchParams({ from: from.value, to: to.value || from.value });
    if (who.value) q.set("user_id", who.value);
    location.hash = `#/absensi?${q}`;
  };
  const valid = rows.filter((a) => !a.voided);
  mount(
    el("h1", {}, "Absensi"),
    el("div", { class: "toolbar" },
      field("Dari", from), field("Sampai", to), field("Guru", who),
      el("button", { class: "btn", onclick: apply }, "Tampilkan"),
      el("span", { class: "grow" }),
      el("button", { class: "btn btn-ghost", onclick: () => manualEntry(gurus, meta) }, "+ Input manual")),
    el("p", { class: "muted" }, `${valid.length} absensi valid, ${rows.length - valid.length} di-void.`),
    table([
      { label: "Tanggal", class: "nowrap", render: (a) => tanggal(a.date) },
      { label: "Sesi", render: (a) => a.session_name },
      { label: "Jam", render: (a) => a.time_hhmm },
      { label: "Guru", render: (a) => a.teacher_name },
      { label: "Kelas / Mapel", render: (a) => `${a.kelas} / ${a.mapel}` },
      { label: "Status", render: (a) => (a.voided ? el("span", { class: "pill pill-err" }, "Void") : statusPill(a.status, a.late_min)) },
      { label: "Tarif", class: "right", render: (a) => rupiah(a.rate_snapshot) },
      { label: "Sumber", render: (a) => (a.source === "manual" ? "Manual" : `Scan${a.distance_m !== null ? ` · ${Math.round(a.distance_m)} m` : ""}`) },
      { label: "Aksi", class: "actions", render: (a) => (a.voided
        ? el("span", { class: "muted small" }, `Alasan: ${a.void_reason}`)
        : el("button", { class: "btn btn-sm btn-danger", onclick: () => voidRow(a) }, "Void")) },
    ], rows, { rowClass: (a) => (a.voided ? "voided" : null), empty: "Tidak ada absensi pada rentang ini." }),
  );
}

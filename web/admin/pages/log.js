// Log: percobaan absen gagal & audit log.
import { api } from "../shared/api.js";
import { hhmm, tanggal, wibParts } from "../shared/format.js";
import { mount } from "../app.js";
import { el, loading, table } from "../ui.js";

const REASONS = {
  TOKEN_INVALID: "QR tidak dikenali", TOKEN_EXPIRED: "QR basi", SESSION_CLOSED: "Di luar jam sesi",
  OUT_OF_RANGE: "Di luar radius", LOW_ACCURACY: "GPS lemah", STALE_LOCATION: "Lokasi kedaluwarsa",
  ALREADY_ATTENDED: "Sudah absen", TICKET_EXPIRED: "Tiket habis", TICKET_INVALID: "Tiket tidak valid",
  INVALID_KELAS: "Kelas tidak valid", INVALID_MAPEL: "Mapel tidak valid", PERIOD_FINAL: "Periode final",
  LOCATION_NOT_SET: "Lokasi belum diatur", BUTTON_DISABLED: "Tombol nonaktif", SESSION_NOT_FOUND: "Sesi tidak ada",
};

function when(iso) {
  const p = wibParts(iso);
  const d = `${p.y}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}`;
  return `${tanggal(d)} ${hhmm(iso)}`;
}

function jsonCell(s) {
  if (!s) return "–";
  let txt = s;
  try { txt = JSON.stringify(JSON.parse(s), null, 1); } catch { /* biarkan */ }
  return el("pre", { class: "json" }, txt);
}

export async function pageLog() {
  const tab = new URLSearchParams(location.hash.split("?")[1] || "").get("t") === "audit" ? "audit" : "attempts";
  mount(el("h1", {}, "Log"), loading());
  const tabs = el("div", { class: "tabs", role: "tablist" },
    el("button", { class: "btn", role: "tab", "aria-selected": String(tab === "attempts"),
      onclick: () => { location.hash = "#/log?t=attempts"; } }, "Percobaan gagal"),
    el("button", { class: "btn", role: "tab", "aria-selected": String(tab === "audit"),
      onclick: () => { location.hash = "#/log?t=audit"; } }, "Audit"));
  if (tab === "attempts") {
    const rows = await api("/api/admin/attempts?limit=300", { cache: true });
    mount(el("h1", {}, "Log"), tabs,
      el("p", { class: "muted" }, "300 percobaan absen gagal terakhir. Pola berulang (mis. jarak jauh terus-menerus) patut dicek."),
      table([
        { label: "Waktu", class: "nowrap", render: (a) => when(a.ts) },
        { label: "Guru", render: (a) => a.teacher_name },
        { label: "Alasan", render: (a) => el("span", { class: "pill pill-err" }, REASONS[a.reason] || a.reason) },
        { label: "Jarak", class: "right", render: (a) => (a.distance_m === null ? "–" : `${Math.round(a.distance_m)} m`) },
        { label: "Akurasi", class: "right", render: (a) => (a.accuracy_m === null ? "–" : `±${Math.round(a.accuracy_m)} m`) },
        { label: "Detail", render: (a) => jsonCell(a.detail) },
      ], rows, { empty: "Belum ada percobaan gagal." }));
  } else {
    const rows = await api("/api/admin/audit?limit=300", { cache: true });
    mount(el("h1", {}, "Log"), tabs,
      el("p", { class: "muted" }, "300 perubahan terakhir oleh admin/sistem."),
      table([
        { label: "Waktu", class: "nowrap", render: (e) => when(e.ts) },
        { label: "Oleh", render: (e) => e.actor_name },
        { label: "Aksi", render: (e) => e.action },
        { label: "Alasan", render: (e) => e.reason || "–" },
        { label: "Sebelum", render: (e) => jsonCell(e.before_json) },
        { label: "Sesudah", render: (e) => jsonCell(e.after_json) },
      ], rows, { empty: "Belum ada entri audit." }));
  }
}

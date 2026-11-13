// Penggajian: rekap per guru, slip PDF, ZIP semua, finalisasi / buka kembali.
import { api, download } from "../shared/api.js";
import { periode, periodNow, rupiah, shiftPeriod } from "../shared/format.js";
import { mount, refresh } from "../app.js";
import { askReason, busy, confirmDialog, el, input, loading, table, toast, toastErr } from "../ui.js";

function currentPeriod() {
  const p = new URLSearchParams(location.hash.split("?")[1] || "").get("p");
  return /^\d{4}-\d{2}$/.test(p || "") ? p : periodNow();
}

async function dl(btn, path, filename) {
  busy(btn, true);
  try {
    await download(path, filename);
  } catch (err) {
    toastErr(err);
  } finally {
    busy(btn, false);
  }
}

export async function pagePenggajian() {
  const period = currentPeriod();
  mount(el("h1", {}, "Penggajian"), loading());
  const data = await api(`/api/admin/payroll?period=${period}`);
  const picker = input({ type: "month", value: period, max: periodNow() });
  picker.addEventListener("change", () => { if (picker.value) location.hash = `#/penggajian?p=${picker.value}`; });
  const zipBtn = el("button", { class: "btn btn-ghost" }, "Unduh semua slip (ZIP)");
  zipBtn.addEventListener("click", () => dl(zipBtn, `/api/admin/payroll/${period}/slips.zip`, `slip-gaji-${period}.zip`));

  const rateText = (ln) => (ln.rate_groups.length
    ? ln.rate_groups.map((g) => `${g.meetings} × ${rupiah(g.rate)}`).join(" + ")
    : ln.current_rate === null ? "–" : rupiah(ln.current_rate));

  const actions = (ln) => {
    const slip = el("button", { class: "btn btn-sm btn-ghost" }, "Slip PDF");
    slip.addEventListener("click", () => dl(slip, `/api/admin/payroll/${period}/${ln.user.user_id}/slip.pdf`,
      `slip-${period}-${ln.user.username}.pdf`));
    let act;
    if (ln.status === "final") {
      act = el("button", { class: "btn btn-sm btn-danger" }, "Buka kembali");
      act.addEventListener("click", async () => {
        const reason = await askReason("Buka kembali periode?", `${ln.user.name} · ${periode(period)}. Void & input manual akan diizinkan lagi.`, "Buka kembali");
        if (!reason) return;
        try {
          await api(`/api/admin/payroll/${period}/${ln.user.user_id}/reopen`, { method: "POST", body: { reason } });
          toast("Periode dibuka kembali.");
          refresh();
        } catch (err) { toastErr(err); }
      });
    } else {
      act = el("button", { class: "btn btn-sm" }, "Finalisasi");
      act.addEventListener("click", async () => {
        const ok = await confirmDialog("Finalisasi slip?",
          `${ln.user.name} · ${periode(period)} · ${ln.meetings} pertemuan · ${rupiah(ln.take_home)}. Setelah final, void/input manual untuk periode ini ditolak.`,
          "Finalisasi", false);
        if (!ok) return;
        try {
          await api(`/api/admin/payroll/${period}/${ln.user.user_id}/finalize`, { method: "POST" });
          toast("Slip difinalisasi.");
          refresh();
        } catch (err) { toastErr(err); }
      });
    }
    return el("div", { class: "btns" }, slip, act);
  };

  mount(
    el("h1", {}, "Penggajian"),
    el("div", { class: "toolbar" },
      el("button", { class: "btn btn-ghost", onclick: () => { location.hash = `#/penggajian?p=${shiftPeriod(period, -1)}`; } }, "‹"),
      picker,
      el("button", { class: "btn btn-ghost", disabled: period >= periodNow(),
        onclick: () => { location.hash = `#/penggajian?p=${shiftPeriod(period, 1)}`; } }, "›"),
      el("span", { class: "grow" }), zipBtn),
    el("p", { class: "muted" }, `Periode ${data.period_label}. Gaji = jumlah pertemuan × tarif yang berlaku saat absen.`),
    table([
      { label: "Guru", render: (ln) => el("div", {}, ln.user.name, ln.user.active ? null : el("div", { class: "muted small" }, "nonaktif")) },
      { label: "Pertemuan", class: "right", render: (ln) => String(ln.meetings) },
      { label: "Tarif", render: (ln) => el("div", {}, rateText(ln),
        ln.missing_rate ? el("div", {}, el("span", { class: "pill pill-err" }, "Ada absensi tanpa tarif")) : null) },
      { label: "Gaji (Take Home)", class: "right", render: (ln) => el("strong", {}, rupiah(ln.take_home)) },
      { label: "Status", render: (ln) => el("span", { class: "pill " + (ln.status === "final" ? "pill-ok" : "pill-idle") },
        ln.status === "final" ? "Final" : "Draft") },
      { label: "Aksi", class: "actions", render: actions },
    ], data.lines, {
      empty: "Belum ada guru.",
      foot: el("tr", {}, el("td", {}, "Total"), el("td", { class: "right" }, String(data.total_meetings)), el("td"),
        el("td", { class: "right" }, rupiah(data.total_take_home)), el("td"), el("td")),
    }),
  );
}

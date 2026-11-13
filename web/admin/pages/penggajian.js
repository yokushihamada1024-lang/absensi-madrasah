// Penggajian: rekap per guru, slip PDF, ZIP semua, finalisasi / buka kembali.
import { api, download } from "../shared/api.js";
import { periode, periodNow, rupiah, shiftPeriod } from "../shared/format.js";
import { mount, refresh } from "../app.js";
import { act, alertBox, askReason, busy, confirmDialog, el, icon, input, loading, table, toast, toastErr } from "../ui.js";
import { countUp } from "../shared/fx.js";

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

function initials(name) {
  return String(name || "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

function periodNav(period) {
  const goTo = (p) => { location.hash = `#/penggajian?p=${p}`; };
  const picker = input({ type: "month", value: period, max: periodNow(), "aria-label": "Pilih periode" });
  picker.addEventListener("change", () => { if (picker.value) goTo(picker.value); });
  return el("div", { class: "period-nav" },
    el("button", { class: "pn-btn", type: "button", "aria-label": "Bulan sebelumnya", onclick: () => goTo(shiftPeriod(period, -1)) }, icon("back")),
    el("label", { class: "pn-label" }, el("span", {}, periode(period)), picker),
    el("button", { class: "pn-btn", type: "button", "aria-label": "Bulan berikutnya", disabled: period >= periodNow(),
      onclick: () => goTo(shiftPeriod(period, 1)) }, icon("next")));
}

export async function pagePenggajian() {
  const period = currentPeriod();
  mount(el("h1", {}, "Penggajian"), loading());
  const data = await api(`/api/admin/payroll?period=${period}`, { cache: true });
  const zipBtn = act("download", "Unduh semua slip (ZIP)", { variant: "primary" });
  zipBtn.addEventListener("click", () => dl(zipBtn, `/api/admin/payroll/${period}/slips.zip`, `slip-gaji-${period}.zip`));

  const rateText = (ln) => (ln.rate_groups.length
    ? ln.rate_groups.map((g) => `${g.meetings} × ${rupiah(g.rate)}`).join(" + ")
    : ln.current_rate === null ? "–" : rupiah(ln.current_rate));

  const actions = (ln) => {
    const slip = act("file", "Slip", { size: "sm", title: "Unduh slip PDF" });
    slip.addEventListener("click", () => dl(slip, `/api/admin/payroll/${period}/${ln.user.user_id}/slip.pdf`,
      `slip-${period}-${ln.user.username}.pdf`));
    let next;
    if (ln.status === "final") {
      next = act("unlock", "Buka kembali", { size: "sm", variant: "danger" });
      next.addEventListener("click", async () => {
        const reason = await askReason("Buka kembali periode?", `${ln.user.name} · ${periode(period)}. Void & input manual akan diizinkan lagi.`, "Buka kembali");
        if (!reason) return;
        busy(next, true);
        try {
          await api(`/api/admin/payroll/${period}/${ln.user.user_id}/reopen`, { method: "POST", body: { reason } });
          toast("Periode dibuka kembali.");
          refresh();
        } catch (err) { toastErr(err); busy(next, false); }
      });
    } else {
      next = act("check", "Finalisasi", { size: "sm", variant: "primary" });
      next.addEventListener("click", async () => {
        const ok = await confirmDialog("Finalisasi slip?",
          `${ln.user.name} · ${periode(period)} · ${ln.meetings} pertemuan · ${rupiah(ln.take_home)}. Setelah final, void/input manual untuk periode ini ditolak.`,
          "Finalisasi", false);
        if (!ok) return;
        busy(next, true);
        try {
          await api(`/api/admin/payroll/${period}/${ln.user.user_id}/finalize`, { method: "POST" });
          toast("Slip difinalisasi.");
          refresh();
        } catch (err) { toastErr(err); busy(next, false); }
      });
    }
    return el("div", { class: "btns row-actions" }, slip, next);
  };

  const lines = data.lines;
  const maxMeet = Math.max(1, ...lines.map((l) => l.meetings));
  const finals = lines.filter((l) => l.status === "final").length;
  const total = el("span", { class: "sum-v" }, rupiah(0));
  const meetBar = (n) => {
    const fill = el("span");
    fill.style.setProperty("--w", String(n / maxMeet));
    return el("div", { class: "meet" }, el("span", { class: "meet-n" }, String(n)), el("span", { class: "meet-bar", "aria-hidden": "true" }, fill));
  };
  const prog = el("span");
  prog.style.setProperty("--w", String(lines.length ? finals / lines.length : 0));
  const missing = lines.filter((l) => l.missing_rate).length;

  mount(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Penggajian"),
        el("p", { class: "muted" }, "Gaji = jumlah pertemuan × tarif yang berlaku saat absen.")),
      el("div", { class: "btns" }, periodNav(period), zipBtn)),
    el("section", { class: "summary" },
      el("div", { class: "sum sum-main" }, el("span", { class: "sum-k" }, `Total take home · ${data.period_label}`), total),
      el("div", { class: "sum" }, el("span", { class: "sum-k" }, "Total pertemuan"), el("span", { class: "sum-v" }, String(data.total_meetings))),
      el("div", { class: "sum" }, el("span", { class: "sum-k" }, "Slip final"),
        el("span", { class: "sum-v" }, `${finals}`, el("small", {}, ` / ${lines.length}`)),
        el("span", { class: "sum-bar", "aria-hidden": "true" }, prog))),
    missing ? alertBox("warn", `${missing} guru punya absensi tanpa tarif. Atur tarifnya di halaman Guru sebelum finalisasi.`) : null,
    table([
      { label: "Guru", render: (ln) => el("div", { class: "person" },
        el("span", { class: "avatar-sm", "aria-hidden": "true" }, initials(ln.user.name)),
        el("div", {}, el("div", { class: "person-name" }, ln.user.name),
          el("div", { class: "muted small" }, ln.user.active ? `@${ln.user.username}` : "Nonaktif"))) },
      { label: "Pertemuan", render: (ln) => meetBar(ln.meetings) },
      { label: "Tarif", render: (ln) => el("div", {}, rateText(ln),
        ln.missing_rate ? el("div", {}, el("span", { class: "pill pill-err" }, "Ada absensi tanpa tarif")) : null) },
      { label: "Take home", class: "right", render: (ln) => el("strong", { class: "money-v" }, rupiah(ln.take_home)) },
      { label: "Status", render: (ln) => el("span", { class: "pill " + (ln.status === "final" ? "pill-ok" : "pill-idle") },
        ln.status === "final" ? "Final" : "Draft") },
      { label: "Aksi", class: "actions", render: actions },
    ], lines, {
      empty: "Belum ada guru.",
      foot: el("tr", {}, el("td", {}, "Total"), el("td", {}, String(data.total_meetings)), el("td"),
        el("td", { class: "right" }, rupiah(data.total_take_home)), el("td"), el("td")),
    }),
  );
  countUp(total, data.total_take_home, rupiah);
}

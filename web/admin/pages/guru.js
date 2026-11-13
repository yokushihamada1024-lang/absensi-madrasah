// Kelola guru: tambah, ubah nama, aktif/nonaktif, reset PIN, tarif + riwayat tarif.
import { api } from "../shared/api.js";
import { rupiah, tanggal, todayWib } from "../shared/format.js";
import { ctx, mount, refresh } from "../app.js";
import { act, confirmDialog, el, field, input, loading, modal, moneyInput, select, table, toast, toastErr } from "../ui.js";

function pinInput() {
  return input({ type: "password", autocomplete: "new-password", minlength: "6", maxlength: "64" });
}

function checkPin(v) {
  if (v.length < 6) throw new Error("PIN minimal 6 karakter.");
  return v;
}

async function addUser() {
  const username = input({ autocapitalize: "none", spellcheck: "false", maxlength: "32" });
  const name = input({ maxlength: "100" });
  const role = select([["guru", "Guru"], ["admin", "Admin"]], "guru");
  const pin = pinInput();
  const rate = moneyInput();
  const eff = input({ type: "date", value: `${todayWib().slice(0, 8)}01` });
  const rateFields = el("div", { class: "inline" }, field("Tarif per pertemuan", rate.wrap), field("Berlaku mulai", eff));
  role.addEventListener("change", () => rateFields.classList.toggle("hidden", role.value !== "guru"));
  const body = await modal({
    title: "Tambah pengguna",
    build: (b) => b.append(
      field("Username", username, "3–32 karakter: huruf kecil, angka, titik, minus, garis bawah."),
      field("Nama lengkap", name), field("Peran", role), field("PIN awal", pin, "Minimal 6 karakter. Sampaikan ke guru secara pribadi."),
      rateFields),
    collect: () => {
      const b = { username: username.value.trim().toLowerCase(), name: name.value.trim(), role: role.value, pin: checkPin(pin.value) };
      if (!b.username || !b.name) throw new Error("Username dan nama wajib diisi.");
      if (b.role === "guru") {
        if (rate.value === null) throw new Error("Tarif wajib diisi untuk guru.");
        b.rate_per_meeting = rate.value;
        b.effective_from = eff.value;
      }
      return b;
    },
  });
  if (!body) return;
  try {
    await api("/api/admin/users", { method: "POST", body });
    toast("Pengguna ditambahkan.");
    refresh();
  } catch (err) { toastErr(err); }
}

async function editName(u) {
  const name = input({ value: u.name, maxlength: "100" });
  const v = await modal({ title: "Ubah nama", build: (b) => b.append(field("Nama lengkap", name)),
    collect: () => { if (!name.value.trim()) throw new Error("Nama wajib diisi."); return name.value.trim(); } });
  if (!v) return;
  try {
    await api(`/api/admin/users/${u.user_id}`, { method: "PATCH", body: { name: v } });
    toast("Nama diperbarui.");
    refresh();
  } catch (err) { toastErr(err); }
}

async function toggleActive(u) {
  const to = !u.active;
  const ok = await confirmDialog(to ? "Aktifkan pengguna?" : "Nonaktifkan pengguna?",
    to ? `${u.name} bisa login kembali.` : `${u.name} tidak bisa login lagi dan sesi login-nya langsung berakhir. Data absensi tetap tersimpan.`,
    to ? "Aktifkan" : "Nonaktifkan", !to);
  if (!ok) return;
  try {
    await api(`/api/admin/users/${u.user_id}`, { method: "PATCH", body: { active: to } });
    toast(to ? "Pengguna diaktifkan." : "Pengguna dinonaktifkan.");
    refresh();
  } catch (err) { toastErr(err); }
}

async function resetPin(u) {
  const pin = pinInput();
  const v = await modal({ title: `Reset PIN — ${u.name}`, okText: "Reset PIN", danger: true,
    build: (b) => b.append(el("p", {}, "Login lama di semua perangkat akan langsung berakhir."), field("PIN baru", pin)),
    collect: () => checkPin(pin.value) });
  if (!v) return;
  try {
    await api(`/api/admin/users/${u.user_id}/reset-pin`, { method: "POST", body: { pin: v } });
    toast("PIN direset.");
  } catch (err) { toastErr(err); }
}

async function rates(u) {
  let hist = [];
  try { hist = await api(`/api/admin/users/${u.user_id}/rates`); } catch (err) { toastErr(err); return; }
  const amount = moneyInput();
  const eff = input({ type: "date", value: todayWib() });
  const v = await modal({
    title: `Tarif — ${u.name}`, okText: "Simpan tarif baru",
    build: (b) => b.append(
      el("p", { class: "muted small" }, "Tarif baru hanya berlaku untuk absensi pada/sesudah tanggal berlaku. Absensi lama tetap memakai tarif saat itu (snapshot)."),
      el("div", { class: "inline" }, field("Tarif baru", amount.wrap), field("Berlaku mulai", eff)),
      el("h3", {}, "Riwayat tarif"),
      table([
        { label: "Berlaku mulai", render: (r) => tanggal(r.effective_from) },
        { label: "Tarif", render: (r) => rupiah(r.rate_per_meeting), class: "right" },
      ], hist, { empty: "Belum ada tarif." })),
    collect: () => {
      if (amount.value === null) throw new Error("Isi tarif.");
      if (!eff.value) throw new Error("Isi tanggal berlaku.");
      return { rate_per_meeting: amount.value, effective_from: eff.value };
    },
  });
  if (!v) return;
  try {
    await api(`/api/admin/users/${u.user_id}/rate`, { method: "PUT", body: v });
    toast("Tarif disimpan.");
    refresh();
  } catch (err) { toastErr(err); }
}

export async function pageGuru() {
  mount(el("h1", {}, "Guru"), loading());
  const users = await api("/api/admin/users", { cache: true });
  users.sort((a, b) => (a.role === b.role ? a.name.localeCompare(b.name) : a.role === "guru" ? -1 : 1));
  mount(
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Guru & Pengguna"),
        el("p", { class: "muted" }, `${users.filter((u) => u.role === "guru" && u.active).length} guru aktif.`)),
      act("plus", "Tambah pengguna", { variant: "primary", onclick: addUser })),
    table([
      { label: "Nama", render: (u) => u.name },
      { label: "Username", render: (u) => u.username },
      { label: "Peran", render: (u) => (u.role === "admin" ? "Admin" : "Guru") },
      { label: "Status", render: (u) => el("span", { class: "pill " + (u.active ? "pill-ok" : "pill-idle") }, u.active ? "Aktif" : "Nonaktif") },
      { label: "Tarif saat ini", class: "center", render: (u) => (u.role !== "guru" ? "–"
        : u.current_rate === null ? el("span", { class: "pill pill-err" }, "Belum ada tarif") : rupiah(u.current_rate)) },
      { label: "Aksi", class: "actions", render: (u) => el("div", { class: "btns row-actions" },
        u.role === "guru" ? act("wallet", "Tarif", { size: "sm", variant: "primary", onclick: () => rates(u) }) : null,
        act("edit", "Ubah nama", { size: "sm", onclick: () => editName(u) }),
        act("key", "Reset PIN", { size: "sm", onclick: () => resetPin(u) }),
        u.user_id === ctx.user.user_id ? null
          : act("power", u.active ? "Nonaktifkan" : "Aktifkan", { size: "sm", variant: u.active ? "danger" : "ok",
            onclick: () => toggleActive(u) })) },
    ], users),
  );
}

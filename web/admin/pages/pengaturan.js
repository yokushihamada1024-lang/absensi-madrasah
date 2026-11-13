// Pengaturan: nama madrasah, titik lokasi (peta OpenStreetMap + GPS + manual), radius, jam sesi, kelas, mapel.
import { api } from "../shared/api.js";
import { mount, onLeave, refresh } from "../app.js";
import { alertBox, busy, confirmDialog, el, field, input, loading, table, toast, toastErr } from "../ui.js";

const DEFAULT_CENTER = [-2.5, 118]; // Indonesia, jika koordinat belum diisi

function num(v) {
  const n = Number(v);
  return v === "" || Number.isNaN(n) ? null : n;
}

function settingsCard(s) {
  const name = input({ value: s.madrasah_name, maxlength: "120" });
  const lat = input({ type: "number", step: "any", value: s.lat ?? "", placeholder: "-6.175392" });
  const lng = input({ type: "number", step: "any", value: s.lng ?? "", placeholder: "106.827153" });
  const radius = input({ type: "number", min: "10", max: "5000", step: "5", value: s.radius_m });
  const acc = input({ type: "number", min: "5", max: "5000", step: "5", value: s.max_accuracy_m });
  const grace = input({ type: "number", min: "0", max: "180", value: s.grace_min });
  const early = input({ type: "number", min: "0", max: "180", value: s.early_open_min });
  const rotate = input({ type: "number", min: "10", max: "300", value: s.qr_rotate_sec });
  const mapEl = el("div", { class: "map", role: "application", "aria-label": "Peta lokasi madrasah" });
  const gpsBtn = el("button", { class: "btn btn-ghost", type: "button" }, "Pakai lokasi saya sekarang");
  const gpsMsg = el("span", { class: "muted small" });
  const save = el("button", { class: "btn", type: "submit" }, "Simpan pengaturan");

  const form = el("form", { class: "card" },
    el("h2", {}, "Lokasi & aturan absen"),
    field("Nama madrasah", name),
    el("p", { class: "muted small" }, "Klik peta atau geser penanda ke titik madrasah. Lingkaran = radius absen yang sah."),
    mapEl,
    el("div", { class: "toolbar" }, gpsBtn, gpsMsg),
    el("div", { class: "inline" }, field("Latitude", lat), field("Longitude", lng), field("Radius (meter)", radius, "Default 100 m")),
    el("div", { class: "inline" },
      field("Akurasi GPS maks (m)", acc, "Scan ditolak jika akurasi lebih buruk"),
      field("Toleransi telat (menit)", grace),
      field("Buka scan sebelum mulai (menit)", early),
      field("Rotasi QR (detik)", rotate)),
    save);

  // --- Peta Leaflet (di-vendor) + tile OpenStreetMap ---
  let map = null;
  let marker = null;
  let circle = null;
  const setPoint = (la, lo, pan = false) => {
    if (!map) return;
    const ll = [la, lo];
    if (!marker) {
      marker = window.L.marker(ll, { draggable: true, title: "Titik madrasah" }).addTo(map);
      marker.on("dragend", () => {
        const p = marker.getLatLng();
        lat.value = p.lat.toFixed(6);
        lng.value = p.lng.toFixed(6);
        circle.setLatLng(p);
      });
      circle = window.L.circle(ll, { radius: num(radius.value) || 100, color: "#0f766e", weight: 2, fillOpacity: 0.15 }).addTo(map);
    } else {
      marker.setLatLng(ll);
      circle.setLatLng(ll);
    }
    if (pan) map.setView(ll, Math.max(map.getZoom(), 17));
  };
  const initMap = () => {
    if (!window.L) {
      mapEl.replaceChildren(alertBox("warn", "Peta gagal dimuat. Isi latitude/longitude secara manual."));
      return;
    }
    const has = s.lat !== null && s.lng !== null;
    map = window.L.map(mapEl, { scrollWheelZoom: true }).setView(has ? [s.lat, s.lng] : DEFAULT_CENTER, has ? 17 : 5);
    window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);
    if (has) setPoint(s.lat, s.lng);
    map.on("click", (e) => {
      lat.value = e.latlng.lat.toFixed(6);
      lng.value = e.latlng.lng.toFixed(6);
      setPoint(e.latlng.lat, e.latlng.lng);
    });
  };
  const syncFromInputs = () => {
    const la = num(lat.value);
    const lo = num(lng.value);
    if (la !== null && lo !== null && Math.abs(la) <= 90 && Math.abs(lo) <= 180) setPoint(la, lo, true);
  };
  lat.addEventListener("change", syncFromInputs);
  lng.addEventListener("change", syncFromInputs);
  radius.addEventListener("input", () => { if (circle && num(radius.value)) circle.setRadius(num(radius.value)); });

  gpsBtn.addEventListener("click", () => {
    if (!("geolocation" in navigator)) { gpsMsg.textContent = "Browser tidak mendukung lokasi."; return; }
    gpsMsg.textContent = "Mengambil lokasi…";
    navigator.geolocation.getCurrentPosition((p) => {
      lat.value = p.coords.latitude.toFixed(6);
      lng.value = p.coords.longitude.toFixed(6);
      setPoint(p.coords.latitude, p.coords.longitude, true);
      gpsMsg.textContent = `Lokasi didapat (akurasi ±${Math.round(p.coords.accuracy)} m). Periksa di peta, lalu Simpan.`;
    }, (e) => {
      gpsMsg.textContent = e.code === 1 ? "Izin lokasi ditolak browser." : "Lokasi tidak didapat. Coba lagi atau isi manual/klik peta.";
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const la = num(lat.value);
    const lo = num(lng.value);
    if ((la === null) !== (lo === null)) { toast("Latitude dan longitude harus diisi berdua.", true); return; }
    busy(save, true);
    try {
      await api("/api/admin/settings", { method: "PUT", body: {
        madrasah_name: name.value.trim(), lat: la, lng: lo, radius_m: num(radius.value), max_accuracy_m: num(acc.value),
        grace_min: num(grace.value), early_open_min: num(early.value), qr_rotate_sec: num(rotate.value),
      } });
      toast("Pengaturan disimpan.");
    } catch (err) {
      toastErr(err);
    } finally {
      busy(save, false);
    }
  });
  onLeave(() => { if (map) map.remove(); });
  return { form, initMap };
}

function sessionDefsCard(defs) {
  const rows = defs.map((d) => ({ d, name: input({ value: d.name, maxlength: "40" }),
    start: input({ type: "time", value: d.start_hhmm }), end: input({ type: "time", value: d.end_hhmm }) }));
  const save = el("button", { class: "btn" }, "Simpan jam sesi");
  save.addEventListener("click", async () => {
    const ok = await confirmDialog("Simpan jam sesi?",
      "Jam baru berlaku untuk sesi yang dibuka berikutnya. Ingat ubah juga jadwal ping pemanasan (cron) agar API sudah bangun sebelum sesi.",
      "Simpan", false);
    if (!ok) return;
    try {
      await api("/api/admin/session-defs", { method: "PUT", body: { items: rows.map((r) => ({
        code: r.d.code, name: r.name.value.trim(), start_hhmm: r.start.value, end_hhmm: r.end.value })) } });
      toast("Jam sesi disimpan.");
      refresh();
    } catch (err) { toastErr(err); }
  });
  return el("div", { class: "card" }, el("h2", {}, "Jam sesi (WIB)"),
    table([
      { label: "Kode", render: (r) => r.d.code },
      { label: "Nama", render: (r) => r.name },
      { label: "Mulai", render: (r) => r.start },
      { label: "Selesai", render: (r) => r.end },
    ], rows), el("div", { class: "toolbar" }, save));
}

function itemsCard(kind, title, items) {
  const state = items.map((i) => ({ ...i }));
  const list = el("div");
  const draw = () => list.replaceChildren(table([
    { label: "Nama", render: (i) => i.name },
    { label: "Aktif", render: (i) => {
      const cb = el("input", { type: "checkbox", checked: i.active, "aria-label": `Aktif ${i.name}` });
      cb.addEventListener("change", () => { i.active = cb.checked; });
      return cb;
    } },
  ], state));
  draw();
  const newName = input({ maxlength: "64", placeholder: `Nama ${title.toLowerCase()} baru` });
  const add = el("button", { class: "btn btn-ghost", type: "button" }, "Tambah");
  add.addEventListener("click", () => {
    const n = newName.value.trim();
    if (!n) return;
    if (state.some((i) => i.name.toLowerCase() === n.toLowerCase())) { toast("Nama sudah ada.", true); return; }
    state.push({ name: n, active: true });
    newName.value = "";
    draw();
  });
  const save = el("button", { class: "btn" }, `Simpan ${title.toLowerCase()}`);
  save.addEventListener("click", async () => {
    try {
      await api(`/api/admin/${kind}`, { method: "PUT", body: { items: state } });
      toast(`${title} disimpan.`);
      refresh();
    } catch (err) { toastErr(err); }
  });
  return el("div", { class: "card" }, el("h2", {}, title),
    el("p", { class: "muted small" }, "Item tidak dihapus; nonaktifkan agar tidak muncul di pilihan guru."),
    list, el("div", { class: "toolbar" }, newName, add, save));
}

export async function pagePengaturan() {
  mount(el("h1", {}, "Pengaturan"), loading());
  const [s, defs, kelas, mapel] = await Promise.all([
    api("/api/admin/settings"), api("/api/admin/session-defs"), api("/api/admin/kelas"), api("/api/admin/mapel"),
  ]);
  const { form, initMap } = settingsCard(s);
  mount(
    el("h1", {}, "Pengaturan"),
    s.lat === null ? alertBox("warn", "Koordinat madrasah belum diisi. Sesi tidak bisa dibuka sebelum titik lokasi disimpan.") : null,
    form,
    sessionDefsCard(defs),
    el("div", { class: "grid grid-2" }, itemsCard("kelas", "Kelas", kelas), itemsCard("mapel", "Mata pelajaran", mapel)),
  );
  initMap(); // setelah elemen peta ada di DOM
}

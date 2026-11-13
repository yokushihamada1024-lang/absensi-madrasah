// Klien API bersama (PWA guru & admin). Tahan cold start Render Free:
// timeout panjang + retry otomatis untuk error jaringan / 502 / 503 / 504.
import { API_BASE_URL } from "../config.js";

const RETRY_STATUS = new Set([502, 503, 504]);
const TOTAL_BUDGET_MS = 95_000; // total waktu tunggu termasuk retry (≥ 90 dtk)
const SLOW_NOTICE_MS = 2_500; // tampilkan "Menghubungkan ke server…" setelah ini

let tokenStore = { get: () => null, set: () => {}, clear: () => {} };
let onSlow = () => {};
let onUnauthorized = () => {};
let onRevalidated = () => {};

export function configureApi({ storage, slow, unauthorized, revalidated } = {}) {
  if (storage) tokenStore = storage;
  if (slow) onSlow = slow;
  if (unauthorized) onUnauthorized = unauthorized;
  if (revalidated) onRevalidated = revalidated;
}

// Navigasi: setiap pindah halaman membatalkan GET milik halaman sebelumnya. Hasilnya dibuang —
// promise-nya sengaja tidak pernah selesai, sehingga lanjutan halaman lama (mount/view, catch yang
// menggambar pesan error) tidak pernah berjalan dan tidak bisa menimpa halaman yang sedang dilihat.
let navCtrl = new AbortController();

/** Panggil saat berpindah halaman. Mengembalikan signal untuk halaman baru. */
export function newNavigation() {
  navCtrl.abort();
  navCtrl = new AbortController();
  revalidation = { pending: 0, changed: false };
  return navCtrl.signal;
}

const never = () => new Promise(() => {});

// Cache GET (stale-while-revalidate), hanya di memori tab ini. api(path, { cache: true }):
// - data < FRESH_MS → langsung dipakai tanpa ke server (pindah tab bolak-balik terasa instan);
// - data lebih tua (≤ MAX_STALE_MS) → langsung dipakai, lalu diperbarui di latar belakang. Setelah
//   semua pembaruan halaman ini selesai dan ada yang berubah, handler `revalidated` dipanggil sekali
//   (aplikasi menggambar ulang halaman). Pembaruan milik halaman lama ikut dibatalkan saat pindah tab;
// - setiap POST/PUT/PATCH/DELETE yang berhasil serta ganti/hapus token mengosongkan cache.
const FRESH_MS = 10_000;
const MAX_STALE_MS = 5 * 60_000;
const cache = new Map(); // path → { data, json, at }
let revalidation = { pending: 0, changed: false };

export function clearCache() {
  cache.clear();
}

function store(path, data) {
  const json = JSON.stringify(data);
  const prev = cache.get(path);
  cache.set(path, { data, json, at: Date.now() });
  return !prev || prev.json !== json;
}

function revalidate(path, opts) {
  const rv = revalidation;
  rv.pending++;
  request(path, opts).then((data) => {
    if (store(path, data)) rv.changed = true;
  }, () => { /* tetap pakai data lama; error tampil saat halaman dimuat tanpa cache */ }).finally(() => {
    rv.pending--;
    if (rv.pending === 0 && rv.changed && rv === revalidation && !navCtrl.signal.aborted) {
      rv.changed = false;
      onRevalidated();
    }
  });
}

export function getToken() {
  try { return tokenStore.get(); } catch { return null; }
}
export function setToken(t) {
  cache.clear();
  try { tokenStore.set(t); } catch { /* storage diblokir */ }
}
export function clearToken() {
  cache.clear();
  try { tokenStore.clear(); } catch { /* storage diblokir */ }
}

export class ApiError extends Error {
  constructor(status, code, message, extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

function sleep(ms, signal) {
  return new Promise((r) => {
    const t = setTimeout(done, ms);
    function done() { clearTimeout(t); signal?.removeEventListener("abort", done); r(); }
    signal?.addEventListener("abort", done);
  });
}

async function once(url, init, timeoutMs, signal) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  const stop = () => ctrl.abort();
  signal?.addEventListener("abort", stop);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
    signal?.removeEventListener("abort", stop);
  }
}

/**
 * Panggil API. Mengembalikan JSON (atau Blob jika opts.blob).
 * Melempar ApiError {status, code, message}. Kode "NETWORK" jika server tak terjangkau.
 * GET terikat ke halaman aktif (lihat newNavigation); `signal: null` untuk melepasnya.
 * `cache: true` (khusus GET JSON) memakai cache stale-while-revalidate di atas; `fresh` (ms) mengganti
 * FRESH_MS untuk panggilan itu (halaman yang perlu nyaris realtime memakai angka kecil).
 */
export async function api(path, opts = {}) {
  const { method = "GET", cache: useCache = false, fresh = FRESH_MS, ...rest } = opts;
  if (!useCache || method !== "GET" || rest.blob) {
    const data = await request(path, { method, ...rest });
    if (method !== "GET") cache.clear(); // data berubah di server
    return data;
  }
  const hit = cache.get(path);
  const age = hit ? Date.now() - hit.at : Infinity;
  if (age < fresh) return hit.data;
  if (age < MAX_STALE_MS) {
    revalidate(path, rest);
    return hit.data;
  }
  const data = await request(path, rest);
  store(path, data);
  return data;
}

async function request(path, { method = "GET", body, blob = false, auth = true, signal } = {}) {
  if (signal === undefined) signal = method === "GET" ? navCtrl.signal : null;
  if (signal?.aborted) return never();
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const tok = auth ? getToken() : null;
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  const init = { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                 credentials: "omit", cache: "no-store", mode: "cors" };
  const url = API_BASE_URL.replace(/\/$/, "") + path;
  const started = Date.now();
  let slowShown = false;
  const slowTimer = setTimeout(() => { slowShown = true; onSlow(true); }, SLOW_NOTICE_MS);
  let delay = 1500;
  try {
    for (;;) {
      const remaining = TOTAL_BUDGET_MS - (Date.now() - started);
      let res = null;
      let netErr = null;
      try {
        res = await once(url, init, Math.max(5_000, remaining), signal);
      } catch (e) {
        netErr = e;
      }
      if (signal?.aborted) return never();
      const retryable = netErr || (res && RETRY_STATUS.has(res.status));
      if (retryable && Date.now() - started + delay < TOTAL_BUDGET_MS) {
        if (!navigator.onLine) throw new ApiError(0, "OFFLINE", "Butuh koneksi internet.");
        await sleep(delay, signal);
        if (signal?.aborted) return never();
        delay = Math.min(delay * 1.6, 8_000);
        continue;
      }
      if (netErr || !res) {
        throw new ApiError(0, navigator.onLine ? "NETWORK" : "OFFLINE",
          navigator.onLine ? "Server tidak bisa dihubungi. Coba lagi sebentar lagi." : "Butuh koneksi internet.");
      }
      if (res.ok) {
        if (res.status === 204) return null;
        let data;
        try {
          data = blob ? await res.blob() : await res.json();
        } catch (e) {
          if (signal?.aborted) return never();
          throw e;
        }
        return signal?.aborted ? never() : data;
      }
      let err = {};
      try { err = (await res.json()).error || {}; } catch { /* bukan JSON */ }
      if (signal?.aborted) return never();
      if (res.status === 401 && auth) onUnauthorized();
      throw new ApiError(res.status, err.code || `HTTP_${res.status}`,
        err.message || "Terjadi kesalahan. Coba lagi.", err);
    }
  } finally {
    clearTimeout(slowTimer);
    if (slowShown) onSlow(false);
  }
}

/** Bangunkan API di latar belakang (Render Free tidur setelah 15 menit). */
export function warmUp() {
  const url = API_BASE_URL.replace(/\/$/, "") + "/healthz";
  fetch(url, { cache: "no-store", credentials: "omit", mode: "cors" }).catch(() => {});
}

/** Unduh file berautentikasi: fetch + Bearer → Blob → link sementara. */
export async function download(path, filename) {
  const b = await api(path, { blob: true });
  const href = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

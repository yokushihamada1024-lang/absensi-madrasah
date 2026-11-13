// Klien API bersama (PWA guru & admin). Tahan cold start Render Free:
// timeout panjang + retry otomatis untuk error jaringan / 502 / 503 / 504.
import { API_BASE_URL } from "../config.js";

const RETRY_STATUS = new Set([502, 503, 504]);
const TOTAL_BUDGET_MS = 95_000; // total waktu tunggu termasuk retry (≥ 90 dtk)
const SLOW_NOTICE_MS = 2_500; // tampilkan "Menghubungkan ke server…" setelah ini

let tokenStore = { get: () => null, set: () => {}, clear: () => {} };
let onSlow = () => {};
let onUnauthorized = () => {};

export function configureApi({ storage, slow, unauthorized } = {}) {
  if (storage) tokenStore = storage;
  if (slow) onSlow = slow;
  if (unauthorized) onUnauthorized = unauthorized;
}

export function getToken() {
  try { return tokenStore.get(); } catch { return null; }
}
export function setToken(t) {
  try { tokenStore.set(t); } catch { /* storage diblokir */ }
}
export function clearToken() {
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function once(url, init, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

/**
 * Panggil API. Mengembalikan JSON (atau Blob jika opts.blob).
 * Melempar ApiError {status, code, message}. Kode "NETWORK" jika server tak terjangkau.
 */
export async function api(path, { method = "GET", body, blob = false, auth = true } = {}) {
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
        res = await once(url, init, Math.max(5_000, remaining));
      } catch (e) {
        netErr = e;
      }
      const retryable = netErr || (res && RETRY_STATUS.has(res.status));
      if (retryable && Date.now() - started + delay < TOTAL_BUDGET_MS) {
        if (!navigator.onLine) throw new ApiError(0, "OFFLINE", "Butuh koneksi internet.");
        await sleep(delay);
        delay = Math.min(delay * 1.6, 8_000);
        continue;
      }
      if (netErr || !res) {
        throw new ApiError(0, navigator.onLine ? "NETWORK" : "OFFLINE",
          navigator.onLine ? "Server tidak bisa dihubungi. Coba lagi sebentar lagi." : "Butuh koneksi internet.");
      }
      if (res.ok) {
        if (res.status === 204) return null;
        return blob ? await res.blob() : await res.json();
      }
      let err = {};
      try { err = (await res.json()).error || {}; } catch { /* bukan JSON */ }
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

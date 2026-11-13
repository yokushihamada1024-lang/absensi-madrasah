// Test perilaku cold start web/shared/api.js (tanpa browser): node --test tests/js/
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, copyFileSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), "absensi-js-"));
mkdirSync(join(dir, "shared"));
copyFileSync(join(here, "..", "..", "web", "shared", "api.js"), join(dir, "shared", "api.js"));
writeFileSync(join(dir, "config.js"), 'export const API_BASE_URL = "https://api.test";\n');
Object.defineProperty(globalThis, "navigator", { value: { onLine: true }, configurable: true });
const mod = await import(pathToFileURL(join(dir, "shared", "api.js")).href);

function respond(status, body) {
  return new Response(body === undefined ? null : JSON.stringify(body),
    { status, headers: { "content-type": "application/json" } });
}

test("retry 503/502 + error jaringan sampai server bangun, banner lambat muncul lalu hilang", async () => {
  const seq = [() => Promise.reject(new TypeError("fetch failed")), () => respond(503), () => respond(502),
    () => respond(200, { ok: true })];
  let calls = 0;
  globalThis.fetch = async () => seq[calls++]();
  const slow = [];
  mod.configureApi({ slow: (on) => slow.push(on) });
  const r = await mod.api("/healthz", { auth: false });
  assert.deepEqual(r, { ok: true });
  assert.equal(calls, 4);
  assert.deepEqual(slow, [true, false]);
});

test("error 4xx tidak di-retry dan membawa kode error server", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return respond(422, { error: { code: "OUT_OF_RANGE", message: "jauh", distance_m: 340 } }); };
  await assert.rejects(mod.api("/api/attendance/scan", { method: "POST", body: {} }), (e) => {
    assert.equal(e.code, "OUT_OF_RANGE");
    assert.equal(e.extra.distance_m, 340);
    return true;
  });
  assert.equal(calls, 1);
});

test("401 memanggil handler unauthorized", async () => {
  globalThis.fetch = async () => respond(401, { error: { code: "UNAUTHENTICATED", message: "x" } });
  let hit = false;
  mod.configureApi({ unauthorized: () => { hit = true; } });
  await assert.rejects(mod.api("/api/me"));
  assert.ok(hit);
});

test("header Authorization Bearer dikirim, tanpa cookie", async () => {
  let seen;
  globalThis.fetch = async (url, init) => { seen = { url, init }; return respond(200, {}); };
  mod.configureApi({ storage: { get: () => "tok123", set() {}, clear() {} } });
  await mod.api("/api/me");
  assert.equal(seen.url, "https://api.test/api/me");
  assert.equal(seen.init.headers.Authorization, "Bearer tok123");
  assert.equal(seen.init.credentials, "omit");
});

test("pindah halaman: GET halaman lama dibatalkan & hasilnya dibuang, POST tidak terpengaruh", async () => {
  const pending = [];
  globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
    pending.push({ url, resolve });
    init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  });
  const slow = [];
  mod.configureApi({ slow: (on) => slow.push(on) });
  let settledA = false;
  const a = mod.api("/api/a").then(() => { settledA = true; }, () => { settledA = true; });
  const post = mod.api("/api/p", { method: "POST", body: {} });
  mod.newNavigation(); // pindah tab
  const b = mod.api("/api/b");
  // Respons halaman lama datang belakangan — tidak boleh sampai ke pemanggil.
  pending.find((p) => p.url.endsWith("/api/p")).resolve(respond(200, { p: 1 }));
  pending.find((p) => p.url.endsWith("/api/b")).resolve(respond(200, { b: 1 }));
  assert.deepEqual(await post, { p: 1 });
  assert.deepEqual(await b, { b: 1 });
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(settledA, false);
  void a;
});

test("respons yang tiba setelah pindah halaman tetap dibuang", async () => {
  let release;
  globalThis.fetch = () => new Promise((r) => { release = r; });
  let settled = false;
  mod.api("/api/a").then(() => { settled = true; }, () => { settled = true; });
  await new Promise((r) => setTimeout(r, 0));
  release(respond(200, { a: 1 })); // fetch selesai tanpa melihat abort...
  mod.newNavigation(); // ...tapi user sudah pindah sebelum JSON dibaca
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(settled, false);
});

test("cache: data segar dipakai tanpa ke server; mutasi & ganti token mengosongkan cache", async () => {
  mod.clearCache();
  let calls = 0;
  globalThis.fetch = async () => { calls++; return respond(200, { n: calls }); };
  assert.deepEqual(await mod.api("/api/x", { cache: true }), { n: 1 });
  assert.deepEqual(await mod.api("/api/x", { cache: true }), { n: 1 });
  assert.equal(calls, 1);
  await mod.api("/api/y", { method: "POST", body: {} }); // calls = 2
  assert.deepEqual(await mod.api("/api/x", { cache: true }), { n: 3 });
  mod.setToken("baru");
  assert.deepEqual(await mod.api("/api/x", { cache: true }), { n: 4 });
  assert.deepEqual(await mod.api("/api/x"), { n: 5 }); // tanpa opsi cache selalu ke server
});

test("cache: data basi tampil langsung, diperbarui di latar, handler revalidated dipanggil sekali", async () => {
  mod.clearCache();
  mod.newNavigation();
  let v = 1;
  globalThis.fetch = async () => respond(200, { v });
  await mod.api("/api/a", { cache: true });
  await mod.api("/api/b", { cache: true });
  const realNow = Date.now;
  Date.now = () => realNow() + 60_000; // satu menit kemudian
  try {
    v = 2;
    let hits = 0;
    let done;
    const fired = new Promise((r) => { done = r; });
    mod.configureApi({ revalidated: () => { hits++; done(); } });
    assert.deepEqual(await mod.api("/api/a", { cache: true }), { v: 1 }); // basi, langsung
    assert.deepEqual(await mod.api("/api/b", { cache: true }), { v: 1 });
    await fired;
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(hits, 1);
    assert.deepEqual(await mod.api("/api/a", { cache: true }), { v: 2 }); // sudah diperbarui
  } finally {
    Date.now = realNow;
    mod.configureApi({ revalidated: () => {} });
  }
});

test("cache: pembaruan latar milik halaman lama tidak memicu gambar ulang", async () => {
  mod.clearCache();
  mod.newNavigation();
  let v = 1;
  let release;
  globalThis.fetch = (url, init) => (v === 1 ? Promise.resolve(respond(200, { v }))
    : new Promise((r, j) => { release = () => r(respond(200, { v })); init.signal.addEventListener("abort", () => j(new DOMException("x", "AbortError"))); }));
  await mod.api("/api/a", { cache: true });
  const realNow = Date.now;
  Date.now = () => realNow() + 60_000;
  try {
    v = 2;
    let hits = 0;
    mod.configureApi({ revalidated: () => { hits++; } });
    await mod.api("/api/a", { cache: true });
    mod.newNavigation(); // pindah tab sebelum pembaruan selesai
    release();
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(hits, 0);
  } finally {
    Date.now = realNow;
    mod.configureApi({ revalidated: () => {} });
  }
});

test("cache: opsi fresh memperpendek masa segar per panggilan", async () => {
  mod.clearCache();
  mod.newNavigation();
  let calls = 0;
  globalThis.fetch = async () => { calls++; return respond(200, { n: calls }); };
  await mod.api("/api/s", { cache: true, fresh: 2_000 });
  assert.deepEqual(await mod.api("/api/s", { cache: true, fresh: 2_000 }), { n: 1 }); // < 2 dtk: dari cache
  assert.equal(calls, 1);
  const realNow = Date.now;
  Date.now = () => realNow() + 3_000; // 3 dtk kemudian: masih "segar" untuk default 10 dtk, tapi tidak untuk fresh 2 dtk
  try {
    assert.deepEqual(await mod.api("/api/s", { cache: true }), { n: 1 });
    assert.equal(calls, 1);
    assert.deepEqual(await mod.api("/api/s", { cache: true, fresh: 2_000 }), { n: 1 }); // tampil langsung...
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(calls, 2); // ...dan diperbarui di latar
  } finally {
    Date.now = realNow;
  }
});

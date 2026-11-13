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

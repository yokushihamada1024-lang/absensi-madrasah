// Kamera + decoder QR. BarcodeDetector bawaan bila ada; fallback ke qr-scanner (vendor).

export class CameraError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind; // denied | notfound | insecure | other
  }
}

async function nativeDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const formats = await window.BarcodeDetector.getSupportedFormats();
    if (!formats.includes("qr_code")) return null;
    return new window.BarcodeDetector({ formats: ["qr_code"] });
  } catch {
    return null;
  }
}

/**
 * Mulai kamera belakang di <video>, panggil onCode(teks) saat QR terbaca.
 * Mengembalikan fungsi stop().
 */
export async function startScanner(video, onCode) {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new CameraError("insecure", "Kamera hanya bisa dipakai lewat HTTPS.");
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
  } catch (e) {
    if (e.name === "NotAllowedError" || e.name === "SecurityError") throw new CameraError("denied", "Izin kamera ditolak.");
    if (e.name === "NotFoundError" || e.name === "OverconstrainedError") throw new CameraError("notfound", "Kamera tidak ditemukan.");
    throw new CameraError("other", "Kamera tidak bisa dibuka: " + e.name);
  }
  video.setAttribute("playsinline", "");
  video.muted = true;
  video.srcObject = stream;
  await video.play().catch(() => {});

  let stopped = false;
  let detector = await nativeDetector();
  let qrEngine = null;
  let QrScanner = null;
  if (!detector) {
    QrScanner = (await import("./vendor/qr-scanner/qr-scanner.min.js")).default;
    qrEngine = await QrScanner.createQrEngine();
  }

  const stop = () => {
    stopped = true;
    for (const t of stream.getTracks()) t.stop();
    video.srcObject = null;
    if (qrEngine && qrEngine instanceof Worker) qrEngine.terminate();
  };

  const tick = async () => {
    if (stopped) return;
    try {
      if (video.readyState >= 2) {
        let text = null;
        if (detector) {
          const codes = await detector.detect(video);
          if (codes.length) text = codes[0].rawValue;
        } else {
          try {
            const r = await QrScanner.scanImage(video, { qrEngine, returnDetailedScanResult: true });
            text = r.data;
          } catch { /* belum ada QR di frame */ }
        }
        if (text && !stopped) {
          stop(); // matikan kamera sebelum memproses
          onCode(text);
          return;
        }
      }
    } catch { /* abaikan frame gagal */ }
    setTimeout(tick, 120);
  };
  tick();
  return stop;
}

// --- Lokasi --------------------------------------------------------------

export const GEO_OPTS = { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 };

export function geoErrorKind(err) {
  if (!err) return "other";
  if (err.code === 1) return "denied";
  if (err.code === 2) return "unavailable";
  if (err.code === 3) return "timeout";
  return "other";
}

export function getPosition() {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) return reject({ code: 2 });
    navigator.geolocation.getCurrentPosition(resolve, reject, GEO_OPTS);
  });
}

/** Pantau lokasi selama halaman scan terbuka. Mengembalikan fungsi stop(). */
export function watchPosition(onPos, onErr) {
  if (!("geolocation" in navigator)) {
    onErr({ code: 2 });
    return () => {};
  }
  const id = navigator.geolocation.watchPosition(onPos, onErr, GEO_OPTS);
  return () => navigator.geolocation.clearWatch(id);
}

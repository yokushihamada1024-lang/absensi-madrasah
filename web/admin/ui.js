// Helper UI admin (DOM API saja; teks dari server selalu text node).
import { ApiError } from "./shared/api.js";
import { clear, el } from "./shared/format.js";

export { clear, el };

const dialog = document.getElementById("dialog");
const toastEl = document.getElementById("toast");
let toastTimer = null;

export function toast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.className = "toast" + (isError ? " err" : "");
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, isError ? 7000 : 3500);
}

export function errMsg(err) {
  return err instanceof ApiError ? err.message : "Terjadi kesalahan. Coba lagi.";
}

export function toastErr(err) {
  toast(errMsg(err), true);
}

export function alertBox(kind, ...children) {
  return el("div", { class: `alert alert-${kind}`, role: kind === "err" ? "alert" : null }, ...children);
}

export function loading(text = "Memuat…") {
  return el("p", { class: "muted" }, el("span", { class: "spinner" }), " ", text);
}

/** Tabel: columns = [{label, render(row) -> Node|string, class}], rows = array. */
export function table(columns, rows, { empty = "Tidak ada data.", rowClass, foot } = {}) {
  const thead = el("thead", {}, el("tr", {}, columns.map((c) => el("th", { class: c.class }, c.label))));
  const tbody = el("tbody", {}, rows.length ? rows.map((r) => el("tr", { class: rowClass ? rowClass(r) : null },
    columns.map((c) => el("td", { class: c.class }, c.render(r)))))
    : el("tr", {}, el("td", { colspan: String(columns.length), class: "muted" }, empty)));
  const t = el("table", {}, thead, tbody);
  if (foot) t.append(el("tfoot", {}, foot));
  return el("div", { class: "table-wrap" }, t);
}

export function field(labelText, input, hint) {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 9)}`;
  input.id = id;
  return el("div", { class: "field" }, el("label", { for: id }, labelText), input,
    hint ? el("div", { class: "muted small" }, hint) : null);
}

export function input(attrs = {}) {
  return el("input", { type: "text", ...attrs });
}

export function select(options, value, attrs = {}) {
  const s = el("select", attrs, options.map((o) => {
    const [v, label] = Array.isArray(o) ? o : [o, o];
    return el("option", { value: v, selected: String(v) === String(value) }, label);
  }));
  return s;
}

/** Dialog modal generik. build(form) mengisi isi form; resolve dengan hasil collect() atau null jika batal. */
export function modal({ title, build, okText = "Simpan", danger = false, collect = () => true }) {
  return new Promise((resolve) => {
    clear(dialog);
    const msg = el("div");
    const ok = el("button", { class: "btn" + (danger ? " btn-danger" : ""), type: "submit" }, okText);
    const cancel = el("button", { class: "btn btn-ghost", type: "button" }, "Batal");
    const body = el("div");
    const form = el("form", { method: "dialog" }, el("h2", {}, title), body, msg, el("div", { class: "btns" }, cancel, ok));
    build(body);
    dialog.append(form);
    const done = (v) => {
      dialog.close();
      resolve(v);
    };
    cancel.addEventListener("click", () => done(null));
    dialog.addEventListener("cancel", () => resolve(null), { once: true });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      clear(msg);
      try {
        const v = collect();
        if (v === false) return;
        done(v);
      } catch (err) {
        msg.append(alertBox("err", err.message));
      }
    });
    dialog.showModal();
    const first = body.querySelector("input, select, textarea");
    if (first) first.focus();
  });
}

export function confirmDialog(title, message, okText = "Ya, lanjutkan", danger = true) {
  return modal({ title, okText, danger, build: (b) => b.append(el("p", {}, message)) });
}

/** Minta alasan wajib (void, buka kembali). */
export function askReason(title, message, okText) {
  const ta = el("textarea", { required: true, maxlength: "500" });
  return modal({
    title, okText, danger: true,
    build: (b) => b.append(el("p", {}, message), field("Alasan (wajib)", ta)),
    collect: () => {
      const v = ta.value.trim();
      if (!v) throw new Error("Alasan wajib diisi.");
      return v;
    },
  });
}

export function statusPill(status, lateMin) {
  return status === "late"
    ? el("span", { class: "pill pill-late" }, `Terlambat ${lateMin} mnt`)
    : el("span", { class: "pill pill-ok" }, "Tepat waktu");
}

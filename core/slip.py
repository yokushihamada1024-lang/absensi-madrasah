"""Slip gaji PDF (reportlab, A4) dan ZIP semua slip.

Visual mengikuti design system web ("lapis & ubin") dengan gaya kop surat: pita tinta tipis + garis
kuningan, kop dua baris yang lapang, tabel bergaris tipis, dan bar Take Home Pay sebagai fokus.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

from core.money import format_rupiah
from core.payroll import PayrollLine
from core.timeutil import format_date_id, format_datetime_id, period_label

# Token warna — sama dengan web/shared/base.css
INK = colors.HexColor("#0e1f3d")
LAPIS = colors.HexColor("#1e4fa3")
LAPIS_50 = colors.HexColor("#eef3fb")
BRASS = colors.HexColor("#b7862e")
BRASS_300 = colors.HexColor("#e2c27f")
SURFACE_2 = colors.HexColor("#f8f9fc")
TEXT = colors.HexColor("#142036")
MUTED = colors.HexColor("#5b6880")
FAINT = colors.HexColor("#8a95a8")
LINE = colors.HexColor("#e2e7f0")
LINE_STRONG = colors.HexColor("#cdd5e2")
OK, OK_SOFT = colors.HexColor("#0b7a6d"), colors.HexColor("#e3f5f1")
WARN, WARN_SOFT = colors.HexColor("#a14a07"), colors.HexColor("#fdf1dc")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
HEADER_H = 30 * mm      # tinggi blok kop biru di halaman pertama
FOOTER_Y = 12 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=12,
                          textColor=TEXT)
    return {
        "base": base,
        "eyebrow": ParagraphStyle("eyebrow", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                                  textColor=FAINT),
        "name": ParagraphStyle("name", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=19,
                               textColor=INK),
        "name_sub": ParagraphStyle("name_sub", parent=base, fontSize=8.4, leading=11, textColor=MUTED),
        "kv_l": ParagraphStyle("kv_l", parent=base, fontSize=8.4, leading=11, textColor=MUTED),
        "kv_r": ParagraphStyle("kv_r", parent=base, fontName="Helvetica-Bold", fontSize=8.6, leading=11,
                               alignment=TA_RIGHT),
        "kv_warn": ParagraphStyle("kv_warn", parent=base, fontName="Helvetica-Bold", fontSize=8.6, leading=11,
                                  alignment=TA_RIGHT, textColor=WARN),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=9, textColor=FAINT),
        "thr": ParagraphStyle("thr", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                              textColor=FAINT, alignment=TA_RIGHT),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.6, leading=11),
        "cell_muted": ParagraphStyle("cell_muted", parent=base, fontSize=8.6, leading=11, textColor=FAINT),
        "cellr": ParagraphStyle("cellr", parent=base, fontName="Helvetica-Bold", fontSize=8.6, leading=11,
                                alignment=TA_RIGHT),
        "ok": ParagraphStyle("ok", parent=base, fontSize=8.4, leading=11, textColor=OK),
        "warn": ParagraphStyle("warn", parent=base, fontSize=8.4, leading=11, textColor=WARN),
        "sum_l": ParagraphStyle("sum_l", parent=base, fontSize=8.8, leading=12, textColor=MUTED),
        "sum_r": ParagraphStyle("sum_r", parent=base, fontName="Helvetica-Bold", fontSize=8.8, leading=12,
                                alignment=TA_RIGHT),
        "thp_label": ParagraphStyle("thp_label", parent=base, fontName="Helvetica-Bold", fontSize=7, leading=9,
                                    textColor=BRASS_300),
        "thp_sub": ParagraphStyle("thp_sub", parent=base, fontSize=7.6, leading=10,
                                  textColor=colors.HexColor("#b9c5db")),
        "thp_value": ParagraphStyle("thp_value", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22,
                                    textColor=colors.white, alignment=TA_RIGHT),
        "note": ParagraphStyle("note", parent=base, fontSize=7.8, leading=11, textColor=MUTED),
    }


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _khatam(canvas, cx: float, cy: float, size: float) -> None:
    """Bintang delapan: dua bujur sangkar, satu diputar 45°."""
    half = size / 2
    canvas.saveState()
    canvas.translate(cx, cy)
    canvas.rect(-half, -half, size, size, stroke=1, fill=0)
    canvas.rotate(45)
    canvas.rect(-half, -half, size, size, stroke=1, fill=0)
    canvas.restoreState()


def _spaced(canvas, x: float, y: float, text: str, font: str, size: float, space: float,
            align: str = "left") -> None:
    """Teks kapital berjarak (tracking); align 'right' menghitung lebar termasuk jaraknya."""
    w = stringWidth(text, font, size) + space * (len(text) - 1)
    t = canvas.beginText(x - w if align == "right" else x, y)
    t.setFont(font, size)
    t.setCharSpace(space)
    t.textOut(text)
    canvas.drawText(t)


class Pill(Flowable):
    """Label status berbentuk kapsul: titik + teks berjarak, padding simetris, teks di tengah vertikal."""

    FONT, SIZE, TRACK, H, PAD, DOT, GAP = "Helvetica-Bold", 6.8, 1.0, 13.5, 7.0, 1.7, 4.0

    def __init__(self, text: str, fg, bg, border) -> None:
        super().__init__()
        self.text, self.fg, self.bg, self.border = text, fg, bg, border
        tw = stringWidth(text, self.FONT, self.SIZE) + self.TRACK * (len(text) - 1)
        self.width = self.PAD + self.DOT * 2 + self.GAP + tw + self.PAD
        self.height = self.H

    def wrap(self, *_):
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setFillColor(self.bg)
        c.setStrokeColor(self.border)
        c.setLineWidth(0.6)
        c.roundRect(0, 0, self.width, self.H, self.H / 2, stroke=1, fill=1)
        c.setFillColor(self.fg)
        c.circle(self.PAD + self.DOT, self.H / 2, self.DOT, stroke=0, fill=1)
        base = (self.H - self.SIZE * 0.72) / 2  # cap-height Helvetica ≈ 0,72 em
        _spaced(c, self.PAD + self.DOT * 2 + self.GAP, base, self.text, self.FONT, self.SIZE, self.TRACK)
        c.restoreState()


def build_slip_pdf(line: PayrollLine, madrasah_name: str, session_names: dict[str, str], printed_at: datetime) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    final = line.status == "final"
    label = "FINAL" if final else "DRAFT"
    plabel = period_label(line.period)
    printed = format_datetime_id(printed_at)

    def draw_common(canvas) -> None:
        if not final:  # watermark DRAFT, sangat halus agar tabel tetap terbaca
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 110)
            canvas.setFillColor(colors.Color(0.72, 0.53, 0.18, alpha=0.05))
            canvas.translate(PAGE_W / 2, PAGE_H / 2 - 30 * mm)
            canvas.rotate(32)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.restoreState()
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, FOOTER_Y + 4 * mm, PAGE_W - MARGIN, FOOTER_Y + 4 * mm)
        canvas.setFont("Helvetica", 6.8)
        canvas.setFillColor(FAINT)
        canvas.drawString(MARGIN, FOOTER_Y, f"{madrasah_name}  ·  Slip gaji {line.user.name}  ·  {plabel}")
        canvas.drawRightString(PAGE_W - MARGIN, FOOTER_Y, f"Halaman {canvas.getPageNumber()}")
        canvas.restoreState()

    def on_first(canvas, _doc) -> None:
        canvas.saveState()
        # Kop: satu blok biru tinta penuh + garis kuningan di bawahnya.
        top = PAGE_H - HEADER_H
        canvas.setFillColor(INK)
        canvas.rect(0, top, PAGE_W, HEADER_H, stroke=0, fill=1)
        canvas.setFillColor(BRASS)
        canvas.rect(0, top - 0.8 * mm, PAGE_W, 0.8 * mm, stroke=0, fill=1)
        # Dua baris, baseline kiri dan kanan sejajar, ditengahkan di dalam kop.
        b1 = top + HEADER_H / 2 + 1.2 * mm   # baris judul
        b2 = b1 - 5.6 * mm                   # baris keterangan
        right = PAGE_W - MARGIN
        canvas.setStrokeColor(BRASS_300)
        canvas.setLineWidth(1.2)
        _khatam(canvas, MARGIN + 4.6 * mm, (b1 + b2) / 2 + 1.2 * mm, 7.2 * mm)
        tx = MARGIN + 13 * mm
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawString(tx, b1, madrasah_name)
        canvas.setFillColor(colors.HexColor("#b9c5db"))
        canvas.setFont("Helvetica", 8.4)
        canvas.drawString(tx, b2, "Rekap honor mengajar berdasarkan absensi")
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 15)
        canvas.drawRightString(right, b1, plabel)
        canvas.setFillColor(BRASS_300)
        _spaced(canvas, right, b2, "SLIP GAJI GURU", "Helvetica-Bold", 7.2, 1.8, align="right")
        canvas.restoreState()
        draw_common(canvas)

    def on_later(canvas, _doc) -> None:
        canvas.saveState()
        y = PAGE_H - 13 * mm
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, y, madrasah_name)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(PAGE_W - MARGIN, y, f"Slip gaji {line.user.name}  ·  {plabel}  ·  {label}")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, y - 3.5 * mm, PAGE_W - MARGIN, y - 3.5 * mm)
        canvas.restoreState()
        draw_common(canvas)

    bottom = FOOTER_Y + 10 * mm
    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=bottom,
        title=f"Slip Gaji {line.user.name} {plabel}", author=madrasah_name, subject="Slip Gaji Guru",
    )
    first_top = PAGE_H - HEADER_H - 9 * mm
    later_top = PAGE_H - 22 * mm
    first_frame = Frame(MARGIN, bottom, CONTENT_W, first_top - bottom, id="first",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    later_frame = Frame(MARGIN, bottom, CONTENT_W, later_top - bottom, id="later",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[first_frame], onPage=on_first, autoNextPageTemplate="Later"),
        PageTemplate(id="Later", frames=[later_frame], onPage=on_later),
    ])

    def flat(t: Table, extra: list | None = None) -> Table:
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")] + (extra or [])))
        return t

    # ---------- Identitas: penerima di kiri, rincian dokumen di kanan ----------
    if line.missing_rate:
        rate_cell = Paragraph("Belum diatur", st["kv_warn"])
    elif line.current_rate is not None:
        rate_cell = Paragraph(f"{format_rupiah(line.current_rate)}<font color='#8a95a8' face='Helvetica'>"
                              f" / pertemuan</font>", st["kv_r"])
    else:
        rate_cell = Paragraph("-", st["kv_r"])
    pill = (Pill(label, OK, OK_SOFT, colors.HexColor("#bfe6dd")) if final
            else Pill(label, WARN, WARN_SOFT, colors.HexColor("#f0d6a6")))
    kv_rows = [
        [Paragraph("Dicetak", st["kv_l"]), Paragraph(printed, st["kv_r"])],
        [Paragraph("Tarif saat ini", st["kv_l"]), rate_cell],
    ]
    if final and line.finalized_at:
        kv_rows.append([Paragraph("Difinalisasi", st["kv_l"]),
                        Paragraph(format_datetime_id(line.finalized_at), st["kv_r"])])
    kv_rows.append([Paragraph("Status", st["kv_l"]), pill])
    right_w = CONTENT_W * 0.42
    kv = Table(kv_rows, colWidths=[right_w * 0.42, right_w * 0.58])
    kv.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    who = [Paragraph("DIBERIKAN KEPADA", st["eyebrow"]), Spacer(1, 3),
           Paragraph(_esc(line.user.name), st["name"]), Spacer(1, 2.5),
           Paragraph(f"@{_esc(line.user.username)}  ·  ID {line.user.user_id[:8]}", st["name_sub"])]
    gap = CONTENT_W * 0.08
    ident = flat(Table([[who, "", kv]], colWidths=[CONTENT_W - right_w - gap, gap, right_w]))
    story: list = [ident, Spacer(1, 10 * mm)]

    # ---------- Rincian pertemuan ----------
    head = flat(Table([[Paragraph("Rincian pertemuan", st["h2"]),
                        Paragraph(f"{line.meetings} pertemuan", ParagraphStyle(
                            "cnt", parent=st["kv_l"], alignment=TA_RIGHT))]],
                      colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4]),
                [("VALIGN", (0, 0), (-1, -1), "BOTTOM")])
    story += [head, Spacer(1, 3 * mm)]

    header = [Paragraph(h.upper(), st["th"]) for h in ["No", "Tanggal", "Sesi", "Kelas", "Mata pelajaran", "Status"]]
    header.append(Paragraph("TARIF", st["thr"]))
    rows: list[list] = [header]
    for i, a in enumerate(line.rows, start=1):
        status = (Paragraph(f"Terlambat {a.late_min} mnt", st["warn"]) if a.status == "late"
                  else Paragraph("Tepat waktu", st["ok"]))
        rows.append([
            Paragraph(f"{i:02d}", st["cell_muted"]), Paragraph(format_date_id(a.date, with_day=True), st["cell"]),
            Paragraph(_esc(session_names.get(a.code, a.code)), st["cell"]),
            Paragraph(_esc(a.kelas), st["cell"]), Paragraph(_esc(a.mapel), st["cell"]), status,
            Paragraph(format_rupiah(a.rate_snapshot), st["cellr"]),
        ])
    empty = len(rows) == 1
    if empty:
        rows.append(["", Paragraph("Tidak ada pertemuan pada periode ini.", st["cell_muted"]), "", "", "", "", ""])
    detail = Table(rows, colWidths=[10 * mm, 42 * mm, 16 * mm, 21 * mm, 29 * mm, 30 * mm, None], repeatRows=1)
    ts = [
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, INK), ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE_STRONG),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 7), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
    ]
    if empty:
        ts += [("SPAN", (1, 1), (-1, 1)), ("TOPPADDING", (0, 1), (-1, 1), 14), ("BOTTOMPADDING", (0, 1), (-1, 1), 14)]
    detail.setStyle(TableStyle(ts))
    story += [detail, Spacer(1, 9 * mm)]

    # ---------- Catatan (kiri) + ringkasan & Take Home Pay (kanan) ----------
    summary: list[list] = [[Paragraph("Total pertemuan", st["sum_l"]),
                            Paragraph(f"{line.meetings} pertemuan", st["sum_r"])]]
    if len(line.rate_groups) > 1:
        for g in line.rate_groups:
            summary.append([Paragraph(f"{g.meetings} × {format_rupiah(g.rate)}", st["sum_l"]),
                            Paragraph(format_rupiah(g.subtotal), st["sum_r"])])
    elif line.rate_groups:
        summary.append([Paragraph("Tarif per pertemuan", st["sum_l"]),
                        Paragraph(format_rupiah(line.rate_groups[0].rate), st["sum_r"])])
    sum_w = CONTENT_W * 0.48
    sm = Table(summary, colWidths=[sum_w * 0.55, sum_w * 0.45])
    sm.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    thp = Table([[[Paragraph("TAKE HOME PAY", st["thp_label"]), Spacer(1, 2),
                   Paragraph(f"{line.meetings} pertemuan", st["thp_sub"])],
                  Paragraph(format_rupiah(line.take_home), st["thp_value"])]],
                colWidths=[sum_w * 0.4, sum_w * 0.6])
    thp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))

    note_txt = ("Gaji dihitung dari jumlah pertemuan × tarif yang berlaku saat absen. "
                + ("Slip ini FINAL dan sudah dikunci admin." if final
                   else "Slip ini masih DRAFT dan bisa berubah sampai periode difinalisasi admin."))
    note = [Paragraph("CATATAN", st["eyebrow"]), Spacer(1, 3), Paragraph(note_txt, st["note"])]
    note_w = CONTENT_W - sum_w - gap
    block = flat(Table([[note, "", [sm, Spacer(1, 4 * mm), thp]]], colWidths=[note_w, gap, sum_w]))
    story.append(KeepTogether([block]))
    doc.build(story)
    return buf.getvalue()


def slip_filename(line: PayrollLine) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in line.user.username)
    return f"slip-{line.period}-{safe}.pdf"


def build_slips_zip(lines: list[PayrollLine], madrasah_name: str, session_names: dict[str, str],
                    printed_at: datetime) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for ln in lines:
            z.writestr(slip_filename(ln), build_slip_pdf(ln, madrasah_name, session_names, printed_at))
    return buf.getvalue()

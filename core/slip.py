"""Slip gaji PDF (reportlab, A4) dan ZIP semua slip.

Visual mengikuti design system web ("lapis & ubin"): pita kepala biru tinta dengan tekstur bintang
delapan (khatam), aksen kuningan, tabel tenang bergaris tipis, dan kartu Take Home Pay sebagai fokus.
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
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

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
MARGIN = 16 * mm
BAND_H = 40 * mm  # tinggi pita kepala di halaman pertama
CONTENT_W = PAGE_W - 2 * MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=12,
                          textColor=TEXT)
    return {
        "base": base,
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=9,
                                textColor=FAINT),
        "value": ParagraphStyle("value", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13),
        "value_sub": ParagraphStyle("value_sub", parent=base, fontSize=8.2, leading=10.5, textColor=MUTED),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.6, leading=11),
        "cell_muted": ParagraphStyle("cell_muted", parent=base, fontSize=8.6, leading=11, textColor=MUTED),
        "cellr": ParagraphStyle("cellr", parent=base, fontSize=8.6, leading=11, alignment=TA_RIGHT),
        "ok": ParagraphStyle("ok", parent=base, fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=OK),
        "warn": ParagraphStyle("warn", parent=base, fontName="Helvetica-Bold", fontSize=8.2, leading=11,
                               textColor=WARN),
        "sum_l": ParagraphStyle("sum_l", parent=base, fontSize=9, leading=12, textColor=MUTED),
        "sum_r": ParagraphStyle("sum_r", parent=base, fontName="Helvetica-Bold", fontSize=9, leading=12,
                                alignment=TA_RIGHT),
        "thp_label": ParagraphStyle("thp_label", parent=base, fontName="Helvetica-Bold", fontSize=8, leading=10,
                                    textColor=BRASS_300),
        "thp_value": ParagraphStyle("thp_value", parent=base, fontName="Helvetica-Bold", fontSize=20, leading=24,
                                    textColor=colors.white),
        "thp_sub": ParagraphStyle("thp_sub", parent=base, fontSize=7.8, leading=10,
                                  textColor=colors.HexColor("#b9c5db")),
        "note": ParagraphStyle("note", parent=base, fontSize=7.8, leading=10.5, textColor=MUTED),
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


def _pill(canvas, x_right: float, y: float, text: str, fg, bg) -> None:
    canvas.setFont("Helvetica-Bold", 7.5)
    tw = canvas.stringWidth(text, "Helvetica-Bold", 7.5)
    w, h = tw + 14, 14
    canvas.setFillColor(bg)
    canvas.roundRect(x_right - w, y, w, h, h / 2, stroke=0, fill=1)
    canvas.setFillColor(fg)
    canvas.circle(x_right - w + 7, y + h / 2, 1.8, stroke=0, fill=1)
    canvas.drawRightString(x_right - 5, y + 4.2, text)


def build_slip_pdf(line: PayrollLine, madrasah_name: str, session_names: dict[str, str], printed_at: datetime) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    final = line.status == "final"
    label = "FINAL" if final else "DRAFT"
    plabel = period_label(line.period)
    printed = format_datetime_id(printed_at)

    def draw_common(canvas) -> None:
        if not final:  # watermark DRAFT, halus agar tabel tetap terbaca
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 96)
            canvas.setFillColor(colors.Color(0.63, 0.29, 0.03, alpha=0.06))
            canvas.translate(PAGE_W / 2, PAGE_H / 2 - 20 * mm)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.restoreState()
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        canvas.setFont("Helvetica", 7.2)
        canvas.setFillColor(FAINT)
        canvas.drawString(MARGIN, 10 * mm, f"Slip gaji {line.user.name} - {plabel} - dicetak {printed}")
        canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, f"Halaman {canvas.getPageNumber()}")
        canvas.restoreState()

    def on_first(canvas, _doc) -> None:
        canvas.saveState()
        top = PAGE_H - BAND_H
        canvas.setFillColor(INK)
        canvas.rect(0, top, PAGE_W, BAND_H, stroke=0, fill=1)
        # tekstur ubin khatam
        p = canvas.beginPath()
        p.rect(0, top, PAGE_W, BAND_H)
        canvas.clipPath(p, stroke=0, fill=0)
        canvas.setStrokeColor(colors.Color(1, 1, 1, alpha=0.05))
        canvas.setLineWidth(0.6)
        step = 16 * mm
        y = top + step / 2
        while y < PAGE_H + step:
            x = step / 2
            while x < PAGE_W + step:
                _khatam(canvas, x, y, 6.2 * mm)
                x += step
            y += step
        canvas.restoreState()

        canvas.saveState()
        canvas.setFillColor(BRASS)
        canvas.rect(0, top, PAGE_W, 1.1 * mm, stroke=0, fill=1)
        # merek: bintang kuningan + nama madrasah
        canvas.setStrokeColor(BRASS_300)
        canvas.setLineWidth(1.3)
        mid = top + BAND_H / 2 + 1 * mm
        _khatam(canvas, MARGIN + 4.2 * mm, mid, 6 * mm)
        tx = MARGIN + 12 * mm
        canvas.setFillColor(BRASS_300)
        t = canvas.beginText(tx, mid + 5.2 * mm)
        t.setFont("Helvetica-Bold", 8)
        t.setCharSpace(1.6)
        t.textOut("SLIP GAJI GURU")
        canvas.drawText(t)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 17)
        canvas.drawString(tx, mid - 2.2 * mm, madrasah_name)
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#b9c5db"))
        canvas.drawString(tx, mid - 7.6 * mm, "Rekap honor mengajar berdasarkan absensi")
        # periode + status di kanan
        right = PAGE_W - MARGIN
        canvas.setFont("Helvetica-Bold", 7)
        canvas.setFillColor(colors.HexColor("#b9c5db"))
        t = canvas.beginText()
        t.setFont("Helvetica-Bold", 7)
        t.setCharSpace(1.2)
        lbl = "PERIODE"
        t.setTextOrigin(right - canvas.stringWidth(lbl, "Helvetica-Bold", 7) - 1.2 * (len(lbl) - 1), mid + 5.2 * mm)
        t.textOut(lbl)
        canvas.drawText(t)
        canvas.setFont("Helvetica-Bold", 14)
        canvas.setFillColor(colors.white)
        canvas.drawRightString(right, mid - 1.6 * mm, plabel)
        _pill(canvas, right, mid - 9.2 * mm, label, OK if final else WARN, OK_SOFT if final else WARN_SOFT)
        canvas.restoreState()
        draw_common(canvas)

    def on_later(canvas, _doc) -> None:
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, PAGE_H - 4 * mm, PAGE_W, 4 * mm, stroke=0, fill=1)
        canvas.setFillColor(BRASS)
        canvas.rect(0, PAGE_H - 4.6 * mm, PAGE_W, 0.6 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(INK)
        canvas.drawString(MARGIN, PAGE_H - 11 * mm, madrasah_name)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 11 * mm, f"Slip gaji {line.user.name} - {plabel} - {label}")
        canvas.restoreState()
        draw_common(canvas)

    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=20 * mm,
        title=f"Slip Gaji {line.user.name} {plabel}", author=madrasah_name, subject="Slip Gaji Guru",
    )
    first_frame = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - BAND_H - 8 * mm - 20 * mm, id="first",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    later_frame = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - 16 * mm - 20 * mm, id="later",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="First", frames=[first_frame], onPage=on_first, autoNextPageTemplate="Later"),
        PageTemplate(id="Later", frames=[later_frame], onPage=on_later),
    ])

    # ---------- Kartu identitas ----------
    def field(lbl: str, val: str, sub: str = "") -> list:
        out = [Paragraph(lbl.upper(), st["label"]), Spacer(1, 1.5), Paragraph(val, st["value"])]
        if sub:
            out.append(Paragraph(sub, st["value_sub"]))
        return out

    if line.missing_rate:
        rate_txt, rate_sub = "Belum diatur", "hubungi admin"
    elif line.current_rate is not None:
        rate_txt, rate_sub = format_rupiah(line.current_rate), "per pertemuan"
    else:
        rate_txt, rate_sub = "-", ""
    status_sub = (f"difinalisasi {format_datetime_id(line.finalized_at)}" if final and line.finalized_at
                  else ("terkunci" if final else "bisa berubah"))
    cw = CONTENT_W / 4
    ident = Table([[
        field("Nama guru", _esc(line.user.name), f"@{_esc(line.user.username)} - ID {line.user.user_id[:8]}"),
        field("Periode", plabel, f"dicetak {printed}"),
        field("Tarif saat ini", rate_txt, rate_sub),
        field("Status slip", label, status_sub),
    ]], colWidths=[cw * 1.35, cw * 0.95, cw * 0.85, cw * 0.85])
    ident.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE_2), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEBEFORE", (1, 0), (-1, 0), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    story: list = [ident, Spacer(1, 7 * mm)]

    # ---------- Rincian pertemuan ----------
    head = Table([[Paragraph("Rincian pertemuan", st["h2"]),
                   Paragraph(f"{line.meetings} pertemuan", ParagraphStyle("cnt", parent=st["cell_muted"],
                                                                         alignment=TA_RIGHT))]],
                 colWidths=[CONTENT_W * 0.6, CONTENT_W * 0.4])
    head.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story.append(head)

    header = ["No", "Tanggal", "Sesi", "Kelas", "Mata Pelajaran", "Status", "Tarif"]
    rows: list[list] = [header]
    for i, a in enumerate(line.rows, start=1):
        status = (Paragraph(f"Terlambat {a.late_min} mnt", st["warn"]) if a.status == "late"
                  else Paragraph("Tepat waktu", st["ok"]))
        rows.append([
            Paragraph(str(i), st["cell_muted"]), Paragraph(format_date_id(a.date, with_day=True), st["cell"]),
            Paragraph(_esc(session_names.get(a.code, a.code)), st["cell"]),
            Paragraph(_esc(a.kelas), st["cell"]), Paragraph(_esc(a.mapel), st["cell"]), status,
            Paragraph(format_rupiah(a.rate_snapshot), st["cellr"]),
        ])
    empty = len(rows) == 1
    if empty:
        rows.append(["", Paragraph("Tidak ada pertemuan pada periode ini.", st["cell_muted"]), "", "", "", "", ""])
    detail = Table(rows, colWidths=[9 * mm, 41 * mm, 15 * mm, 20 * mm, 29 * mm, 32 * mm, None], repeatRows=1)
    ts = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 7.2),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("BACKGROUND", (0, 0), (-1, 0), LAPIS_50),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE_STRONG), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if empty:
        ts += [("SPAN", (1, 1), (-1, 1)), ("TOPPADDING", (0, 1), (-1, 1), 12), ("BOTTOMPADDING", (0, 1), (-1, 1), 12)]
    detail.setStyle(TableStyle(ts))
    story += [detail, Spacer(1, 7 * mm)]

    # ---------- Ringkasan + Take Home Pay ----------
    summary: list[list] = [[Paragraph("Total pertemuan", st["sum_l"]),
                            Paragraph(f"{line.meetings} pertemuan", st["sum_r"])]]
    if len(line.rate_groups) > 1:
        for g in line.rate_groups:
            summary.append([Paragraph(f"{g.meetings} × {format_rupiah(g.rate)}", st["sum_l"]),
                            Paragraph(format_rupiah(g.subtotal), st["sum_r"])])
    elif line.rate_groups:
        summary.append([Paragraph("Tarif per pertemuan", st["sum_l"]),
                        Paragraph(format_rupiah(line.rate_groups[0].rate), st["sum_r"])])
    left_w = CONTENT_W * 0.5
    sm = Table(summary, colWidths=[left_w * 0.55, left_w * 0.45 - 8 * mm])
    sm.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    thp = Table([[Paragraph("Total / Take Home Pay", st["thp_label"])],
                 [Paragraph(format_rupiah(line.take_home), st["thp_value"])],
                 [Paragraph(f"{line.meetings} pertemuan - {plabel}", st["thp_sub"])]],
                colWidths=[CONTENT_W * 0.5])
    thp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK), ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("LINEBEFORE", (0, 0), (0, -1), 3, BRASS_300),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, 0), 12), ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, -1), (-1, -1), 12),
    ]))
    block = Table([[sm, thp]], colWidths=[left_w, CONTENT_W * 0.5])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

    note_txt = ("Gaji dihitung dari jumlah pertemuan × tarif yang berlaku saat absen. "
                + ("Slip ini FINAL dan sudah dikunci admin." if final
                   else "Slip ini masih DRAFT dan bisa berubah sampai periode difinalisasi admin."))
    note = Table([[Paragraph(note_txt, st["note"])]], colWidths=[CONTENT_W])
    note.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), OK_SOFT if final else WARN_SOFT),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, OK if final else BRASS),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(KeepTogether([block, Spacer(1, 6 * mm), note]))
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

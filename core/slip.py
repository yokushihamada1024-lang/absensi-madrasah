"""Slip gaji PDF (reportlab, A4) dan ZIP semua slip."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.money import format_rupiah
from core.payroll import PayrollLine
from core.timeutil import format_date_id, format_datetime_id, period_label

BRAND = colors.HexColor("#0f766e")
GRID = colors.HexColor("#c9d6d3")
STRIPE = colors.HexColor("#f2f7f6")


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=12)
    return {
        "base": base,
        "school": ParagraphStyle("school", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19,
                                 alignment=TA_CENTER),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                                alignment=TA_CENTER, textColor=BRAND),
        "period": ParagraphStyle("period", parent=base, fontSize=10.5, alignment=TA_CENTER),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.8, leading=11),
        "cellr": ParagraphStyle("cellr", parent=base, fontSize=8.8, leading=11, alignment=TA_RIGHT),
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#5d6f6c")),
        "center": ParagraphStyle("center", parent=base, alignment=TA_CENTER),
    }


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_slip_pdf(line: PayrollLine, madrasah_name: str, session_names: dict[str, str], printed_at: datetime) -> bytes:
    st = _styles()
    buf = io.BytesIO()
    final = line.status == "final"
    label = "FINAL" if final else "DRAFT"
    plabel = period_label(line.period)
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
        title=f"Slip Gaji {line.user.name} {plabel}", author=madrasah_name, subject="Slip Gaji Guru",
    )

    def on_page(canvas, _doc) -> None:
        canvas.saveState()
        w, h = A4
        # Label status di pojok kanan atas
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(BRAND if final else colors.HexColor("#b45309"))
        canvas.drawRightString(w - 16 * mm, h - 11 * mm, label)
        if not final:  # watermark DRAFT
            canvas.setFont("Helvetica-Bold", 90)
            canvas.setFillColor(colors.Color(0.85, 0.55, 0.2, alpha=0.12))
            canvas.translate(w / 2, h / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.rotate(-35)
            canvas.translate(-w / 2, -h / 2)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5d6f6c"))
        foot = f"Slip gaji {line.user.name} - {plabel} - dicetak {format_datetime_id(printed_at)}"
        canvas.drawString(16 * mm, 10 * mm, foot)
        canvas.drawRightString(w - 16 * mm, 10 * mm, f"Halaman {canvas.getPageNumber()}")
        canvas.restoreState()

    story: list = [
        Paragraph(_esc(madrasah_name), st["school"]),
        Paragraph("SLIP GAJI GURU", st["title"]),
        Paragraph(f"Periode {plabel}", st["period"]),
        Spacer(1, 6 * mm),
    ]
    ident = Table(
        [["Nama guru", f": {line.user.name}"], ["Username / ID", f": {line.user.username} / {line.user.user_id[:8]}"],
         ["Status slip", f": {label}"]],
        colWidths=[32 * mm, 140 * mm], hAlign="LEFT",
    )
    ident.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 10),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [ident, Spacer(1, 5 * mm)]

    header = ["No", "Tanggal", "Sesi", "Kelas", "Mata Pelajaran", "Status", "Tarif"]
    rows: list[list] = [header]
    for i, a in enumerate(line.rows, start=1):
        status = f"Terlambat {a.late_min} mnt" if a.status == "late" else "Tepat waktu"
        rows.append([
            str(i), Paragraph(format_date_id(a.date), st["cell"]),
            Paragraph(_esc(session_names.get(a.code, a.code)), st["cell"]),
            Paragraph(_esc(a.kelas), st["cell"]), Paragraph(_esc(a.mapel), st["cell"]), Paragraph(status, st["cell"]),
            Paragraph(format_rupiah(a.rate_snapshot), st["cellr"]),
        ])
    empty = len(rows) == 1
    if empty:
        rows.append(["", Paragraph("Tidak ada pertemuan pada periode ini.", st["cell"]), "", "", "", "", ""])
    detail = Table(rows, colWidths=[9 * mm, 33 * mm, 20 * mm, 24 * mm, 30 * mm, 30 * mm, None], repeatRows=1)
    ts = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.8),
        ("BACKGROUND", (0, 0), (-1, 0), BRAND), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"), ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in range(2, len(rows), 2):
        ts.append(("BACKGROUND", (0, r), (-1, r), STRIPE))
    if empty:
        ts.append(("SPAN", (1, 1), (-1, 1)))
    detail.setStyle(TableStyle(ts))
    story += [detail, Spacer(1, 6 * mm)]

    summary: list[list] = [["Total pertemuan", f"{line.meetings} pertemuan"]]
    if len(line.rate_groups) > 1:
        summary.append(["Rincian tarif", ""])
        for g in line.rate_groups:
            summary.append([f"   {g.meetings} × {format_rupiah(g.rate)}", format_rupiah(g.subtotal)])
    elif line.rate_groups:
        summary.append(["Tarif per pertemuan", format_rupiah(line.rate_groups[0].rate)])
    summary.append(["Total / Take Home Pay", format_rupiah(line.take_home)])
    sm = Table(summary, colWidths=[70 * mm, 45 * mm], hAlign="RIGHT")
    sm.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("LINEABOVE", (0, -1), (-1, -1), 1, BRAND), ("TOPPADDING", (0, -1), (-1, -1), 6),
    ]))

    sign = Table(
        [[Paragraph(f"Dicetak: {format_datetime_id(printed_at)}", st["small"]), ""],
         [Paragraph("Admin / Bendahara", st["center"]), Paragraph("Penerima", st["center"])],
         ["", ""],
         [Paragraph("(......................................)", st["center"]),
          Paragraph(f"( {_esc(line.user.name)} )", st["center"])]],
        colWidths=[85 * mm, 85 * mm], rowHeights=[None, None, 18 * mm, None],
    )
    sign.setStyle(TableStyle([("SPAN", (0, 0), (1, 0)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    note = Paragraph(
        "Gaji dihitung dari jumlah pertemuan × tarif yang berlaku saat absen. "
        + ("Slip ini FINAL." if final else "Slip ini masih DRAFT dan bisa berubah sampai periode difinalisasi admin."),
        st["small"])
    story += [KeepTogether([sm, Spacer(1, 4 * mm), note, Spacer(1, 8 * mm), sign])]
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
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

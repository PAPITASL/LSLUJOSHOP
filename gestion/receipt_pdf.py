from io import BytesIO
from pathlib import Path
from math import cos, pi, sin

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import DetalleOrden


RED = colors.HexColor("#E6313A")
BLACK = colors.HexColor("#151615")
GRAY = colors.HexColor("#5C5F62")
LIGHT = colors.HexColor("#E9E9E9")
BORDER = colors.HexColor("#777777")


def money(value):
    return "$ {:,.0f}".format(value or 0).replace(",", ".")


def _logo_path():
    preferred = Path(settings.BASE_DIR) / "static" / "img" / "lg-transparent-final.png"
    return preferred if preferred.exists() else Path(settings.BASE_DIR) / "static" / "img" / "lg.png"


def _draw_badge(canvas, x, y):
    """Dibuja el emblema oficial; conserva un respaldo vectorial."""
    badge_path = Path(settings.BASE_DIR) / "static" / "img" / "logo-circular.png"
    if badge_path.exists():
        canvas.drawImage(
            ImageReader(str(badge_path)), x - 13 * mm, y - 13 * mm,
            width=26 * mm, height=26 * mm, preserveAspectRatio=True,
            anchor="c", mask="auto",
        )
        return
    canvas.setFillColor(colors.HexColor("#333333"))
    canvas.circle(x, y, 12 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(RED)
    canvas.setLineWidth(1.5)
    canvas.circle(x, y, 9.5 * mm, fill=0, stroke=1)
    for index in range(16):
        angle = 2 * pi * index / 16
        canvas.setStrokeColor(RED if index % 2 == 0 else colors.white)
        canvas.setLineWidth(1.2)
        canvas.line(x + cos(angle) * 7.3 * mm, y + sin(angle) * 7.3 * mm, x + cos(angle) * 9 * mm, y + sin(angle) * 9 * mm)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawCentredString(x, y + 1.2 * mm, "1  3  5")
    canvas.setFillColor(RED)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawCentredString(x, y - 4 * mm, "LS")


def _draw_header(canvas, document):
    width, height = letter
    left, right = document.leftMargin, width - document.rightMargin
    top, bottom = height - 12 * mm, height - 42 * mm
    canvas.saveState()
    canvas.setFillColor(BLACK)
    canvas.setStrokeColor(BLACK)
    canvas.setLineWidth(0)
    canvas.polygon = None
    path = canvas.beginPath()
    path.moveTo(left, top)
    path.lineTo(right, top)
    path.lineTo(right, bottom + 9 * mm)
    path.lineTo(left, bottom)
    path.close()
    canvas.drawPath(path, fill=1, stroke=0)
    canvas.setFillColor(RED)
    stripe = canvas.beginPath()
    stripe.moveTo(left, bottom + 2.5 * mm)
    stripe.lineTo(right, bottom + 11.5 * mm)
    stripe.lineTo(right, bottom + 8 * mm)
    stripe.lineTo(left, bottom - 1 * mm)
    stripe.close()
    canvas.drawPath(stripe, fill=1, stroke=0)
    canvas.drawImage(ImageReader(str(_logo_path())), left + 2 * mm, bottom + 8 * mm, width=92 * mm, height=23 * mm, preserveAspectRatio=True, anchor="sw", mask="auto")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(left + 29 * mm, bottom + 7 * mm, "Accesorios para carros")
    _draw_badge(canvas, right - 20 * mm, bottom + 17 * mm)
    canvas.restoreState()


def _draw_footer(canvas, document):
    canvas.saveState()
    width, _ = letter
    left, right = document.leftMargin, width - document.rightMargin
    canvas.setFillColor(BLACK)
    footer = canvas.beginPath()
    footer.moveTo(left, 10 * mm)
    footer.lineTo(right, 14 * mm)
    footer.lineTo(right, 25 * mm)
    footer.lineTo(left, 21 * mm)
    footer.close()
    canvas.drawPath(footer, fill=1, stroke=0)
    canvas.setFillColor(RED)
    canvas.rect(left, 21 * mm, 82 * mm, 2.5 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-BoldOblique", 7)
    canvas.drawString(left + 9 * mm, 14.2 * mm, "GRACIAS POR SU COMPRA EN LUJOSHOP")
    canvas.setFont("Helvetica", 6.2)
    canvas.drawRightString(right - 3 * mm, 17 * mm, "(+57) 319 2382976  •  lujoshop.accesorios")
    canvas.drawRightString(right - 3 * mm, 13.3 * mm, "www.lujoshop.com")
    canvas.setFillColor(GRAY)
    canvas.drawRightString(right, 6.5 * mm, f"Página {document.page}")
    canvas.restoreState()


def _first_page(canvas, document):
    _draw_header(canvas, document)
    _draw_footer(canvas, document)


def build_order_receipt(order):
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=letter, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=47 * mm, bottomMargin=30 * mm,
        title=f"Orden {order.numero_orden} - LujoShop", author="LujoShop",
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("normal-receipt", parent=styles["Normal"], fontName="Helvetica", fontSize=7.2, leading=9, textColor=BLACK)
    tiny = ParagraphStyle("tiny", parent=normal, fontSize=6.2, leading=7.4)
    center = ParagraphStyle("center", parent=normal, alignment=TA_CENTER)
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    white = ParagraphStyle("white", parent=normal, alignment=TA_CENTER, textColor=colors.white, fontName="Helvetica-Bold")
    section = ParagraphStyle("section", parent=normal, textColor=colors.white, fontName="Helvetica-Bold", fontSize=7)
    story = []
    order_date = timezone.localtime(order.fecha) if timezone.is_aware(order.fecha) else order.fecha

    company = Paragraph("<b>ORDEN DE PEDIDO</b><br/>Calle 6c #70b-78 Bogotá, Colombia<br/>Teléfono: (+57) 319 2382976", tiny)
    order_info = Table([
        [Paragraph("ORDEN DE PEDIDO #", white), Paragraph(str(order.numero_orden), white)],
        [Paragraph("FECHA DE FACTURACIÓN", center), Paragraph(order_date.strftime("%d/%m/%Y"), center)],
        [Paragraph("FECHA DE ENTREGA", center), Paragraph("POR CONFIRMAR", center)],
    ], colWidths=[66 * mm, 52 * mm], rowHeights=[9 * mm, 6 * mm, 6 * mm])
    order_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RED), ("GRID", (0, 0), (-1, -1), .55, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    summary = Table([[company, order_info]], colWidths=[56 * mm, 118 * mm], rowHeights=[21 * mm])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 5)]))
    story.extend([summary, Spacer(1, 2.5 * mm)])

    client = order.cliente
    clients = Table([
        [Paragraph("DATOS DEL CLIENTE:", section), "", "", ""],
        [Paragraph("Nombre del cliente:", normal), Paragraph(client.nombre, center), Paragraph("Teléfono:", normal), Paragraph(client.telefono or "N/A", center)],
        [Paragraph("Correo electrónico", normal), Paragraph("N/A", center), Paragraph("Ciudad:", normal), Paragraph(client.ciudad or "N/A", center)],
        [Paragraph("Dirección residencia", normal), Paragraph(client.direccion or "N/A", center), Paragraph("", normal), Paragraph("COLOMBIA", center)],
    ], colWidths=[37 * mm, 68 * mm, 26 * mm, 43 * mm], rowHeights=[6 * mm, 6 * mm, 6 * mm, 6 * mm])
    clients.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), RED),
        ("GRID", (0, 1), (-1, -1), .45, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([clients, Spacer(1, 2.5 * mm)])

    details = DetalleOrden.objects.filter(orden=order).select_related("producto").order_by("pk")
    rows = [[Paragraph("Descripción del producto", white), Paragraph("Precio", white), Paragraph("Cantidad", white), Paragraph("Total", white)]]
    for detail in details:
        rows.append([Paragraph(detail.descripcion_producto, normal), Paragraph(money(detail.precio_venta_unitario), right), Paragraph(str(detail.cantidad), center), Paragraph(money(detail.total_venta), right)])
    if len(rows) == 1:
        rows.append([Paragraph("Sin productos detallados", normal), "", "", ""])
    while len(rows) < 12:
        rows.append(["", "", "", ""])
    products = Table(rows, colWidths=[92 * mm, 27 * mm, 22 * mm, 33 * mm], rowHeights=[6 * mm] + [5.7 * mm] * (len(rows) - 1), repeatRows=1)
    products.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RED), ("GRID", (0, 0), (-1, -1), .45, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([products, Spacer(1, 3 * mm)])

    contact = Paragraph("Si tiene alguna pregunta o inquietud, no dude en ponerse<br/>en contacto con nosotros al número de teléfono o correo electrónico<br/>proporcionado en nuestro sitio web.", center)
    totals = Table([
        [Paragraph("Total", section), Paragraph(money(order.total_venta), right)],
        [Paragraph("ABONO", normal), Paragraph(money(order.total_abonado), right)],
        [Paragraph("Saldo:", normal), Paragraph(money(order.saldo_pendiente), right)],
    ], colWidths=[22 * mm, 46 * mm], rowHeights=[7 * mm, 7 * mm, 7 * mm])
    totals.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), RED), ("GRID", (0, 0), (-1, -1), .5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    closing = Table([[contact, totals]], colWidths=[104 * mm, 68 * mm])
    closing.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("RIGHTPADDING", (0, 0), (0, 0), 5)]))
    story.append(KeepTogether(closing))
    if order.observaciones:
        story.extend([Spacer(1, 3 * mm), Paragraph(f"<b>Observaciones:</b> {order.observaciones}", normal)])

    doc.build(story, onFirstPage=_first_page, onLaterPages=_draw_footer)
    output.seek(0)
    return output

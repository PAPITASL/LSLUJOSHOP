from io import BytesIO
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal
from collections import defaultdict
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String

from .models import DetalleOrden


RED = colors.HexColor("#E6313A")
BLACK = colors.HexColor("#151615")
GRAY = colors.HexColor("#5C5F62")
LIGHT = colors.HexColor("#F3F3F3")
BORDER = colors.HexColor("#CDCFD1")

REPORT_COLUMNS = {
    "productos": (("id", "ID"), ("nombre", "Producto"), ("categoria", "Categoría"), ("marca", "Marca"), ("modelo", "Modelo"), ("cantidad_disponible", "Stock"), ("costo_pesos", "Costo COP"), ("precio_venta_sugerido", "Precio venta"), ("estado", "Estado")),
    "clientes": (("id", "ID"), ("nombre", "Nombre"), ("telefono", "Teléfono"), ("ciudad", "Ciudad"), ("direccion", "Dirección"), ("creado_en", "Registro")),
    "vendedores": (("id", "ID"), ("nombre", "Vendedor"), ("telefono", "Teléfono"), ("porcentaje_comision", "Comisión %"), ("activo", "Activo")),
    "ordenes": (("numero_orden", "Orden"), ("fecha", "Fecha"), ("cliente", "Cliente"), ("vendedor", "Vendedor"), ("subtotal_venta", "Subtotal"), ("total_venta", "Total"), ("total_abonado", "Abonado"), ("saldo_pendiente", "Saldo"), ("ganancia_neta", "Ganancia"), ("estado", "Estado")),
    "detalles": (("orden", "Orden"), ("descripcion_producto", "Producto"), ("cantidad", "Cant."), ("cantidad_recibida", "Pedida"), ("costo_unitario_dolares", "Costo USD"), ("costo_unitario_pesos", "Costo COP"), ("flete_unitario_dolares", "Flete USD"), ("flete_unitario_pesos", "Flete COP"), ("precio_venta_unitario", "Precio venta"), ("ganancia_producto", "Ganancia")),
    "abonos": (("id", "ID"), ("orden", "Orden"), ("fecha", "Fecha"), ("valor", "Valor"), ("metodo_pago", "Método"), ("referencia", "Referencia")),
    "comisiones": (("orden", "Orden"), ("vendedor", "Vendedor"), ("porcentaje", "%"), ("base_comision", "Base"), ("valor_comision", "Comisión"), ("estado_pago", "Estado"), ("fecha_pago", "Fecha pago")),
    "recibos": (("numero_recibo", "Recibo"), ("orden", "Orden"), ("fecha_generacion", "Fecha"), ("total_recibo", "Total"), ("generado_por", "Generado por")),
    "movimientos": (("fecha", "Fecha"), ("tipo_movimiento", "Tipo"), ("categoria", "Categoría"), ("descripcion", "Descripción"), ("moneda", "Moneda"), ("valor_moneda_original", "Valor original"), ("valor_pesos", "Valor COP"), ("metodo_pago", "Método")),
}

REPORT_TOTALS = {
    "productos": (("cantidad_disponible", "Unidades disponibles"), ("costo_pesos", "Suma costos unitarios"), ("precio_venta_sugerido", "Suma precios")),
    "ordenes": (("total_venta", "Ventas"), ("total_abonado", "Abonado"), ("saldo_pendiente", "Saldo pendiente"), ("ganancia_neta", "Ganancia neta")),
    "detalles": (("cantidad", "Unidades"), ("total_venta", "Ventas"), ("ganancia_producto", "Ganancia")),
    "abonos": (("valor", "Total abonado"),),
    "comisiones": (("valor_comision", "Total comisiones"),),
    "recibos": (("total_recibo", "Total recibos"),),
    "movimientos": (("valor_pesos", "Valor total COP"),),
}

MONEY_FIELDS = {
    "costo_pesos", "precio_venta_sugerido", "subtotal_venta", "total_venta",
    "total_abonado", "saldo_pendiente", "ganancia_neta", "precio_venta_unitario",
    "costo_unitario_pesos", "flete_unitario_pesos",
    "ganancia_producto", "valor", "base_comision", "valor_comision", "total_recibo",
    "valor_moneda_original", "valor_pesos",
}


def _money(value):
    return "$ {:,.0f}".format(value or 0).replace(",", ".")


def _display(record, field):
    value = getattr(record, field, None)
    if value is None:
        return "—"
    if field in MONEY_FIELDS:
        return _money(value)
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _footer(canvas, document):
    canvas.saveState()
    width, _ = landscape(letter)
    canvas.setFillColor(BLACK)
    canvas.rect(document.leftMargin, 10 * mm, width - document.leftMargin - document.rightMargin, 8 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(document.leftMargin + 4 * mm, 13 * mm, "LUJOSHOP · REPORTE ADMINISTRATIVO")
    canvas.drawRightString(width - document.rightMargin - 4 * mm, 13 * mm, f"Página {document.page}")
    canvas.restoreState()


def _top_entry(values, default="Sin datos"):
    return max(values.items(), key=lambda item: item[1]) if values else (default, 0)


def _analytics(module, records):
    """Indicadores y serie gráfica adecuados para cada módulo."""
    kpis, groups = [], defaultdict(Decimal)
    count = len(records)
    if module == "productos":
        units = sum((item.cantidad_disponible or 0 for item in records), 0)
        inventory = sum(((item.cantidad_disponible or 0) * (item.costo_pesos or 0) for item in records), Decimal("0"))
        low_stock = sum(1 for item in records if (item.cantidad_disponible or 0) <= 3)
        brands = defaultdict(int)
        for item in records:
            brands[item.marca or "Sin marca"] += 1
            groups[item.estado or "Sin estado"] += item.cantidad_disponible or 0
        top_brand, _ = _top_entry(brands)
        kpis = [("Productos", str(count)), ("Unidades en inventario", f"{units:,}"), ("Valor del inventario", _money(inventory)), ("Stock bajo", str(low_stock)), ("Marca principal", top_brand)]
        chart_title = "Unidades disponibles por estado"
    elif module == "clientes":
        cities = defaultdict(int)
        for item in records:
            cities[item.ciudad or "Sin ciudad"] += 1
        top_city, top_count = _top_entry(cities)
        groups.update(cities)
        kpis = [("Clientes registrados", str(count)), ("Ciudad principal", top_city), ("Clientes en esa ciudad", str(top_count))]
        chart_title = "Clientes por ciudad"
    elif module == "vendedores":
        active = sum(1 for item in records if item.activo)
        average = sum((item.porcentaje_comision or 0 for item in records), Decimal("0")) / count if count else 0
        groups["Activos"] = active
        groups["Inactivos"] = count - active
        kpis = [("Vendedores", str(count)), ("Activos", str(active)), ("Comisión promedio", f"{average:.1f}%")]
        chart_title = "Estado de vendedores"
    elif module == "ordenes":
        sales = sum((item.total_venta or 0 for item in records), Decimal("0"))
        balance = sum((item.saldo_pendiente or 0 for item in records), Decimal("0"))
        profit = sum((item.ganancia_neta or 0 for item in records), Decimal("0"))
        for item in records:
            groups[item.estado or "Sin estado"] += item.total_venta or 0
        details = DetalleOrden.objects.filter(orden_id__in=[item.pk for item in records]).select_related("producto")
        products, brands = defaultdict(int), defaultdict(int)
        for detail in details:
            products[detail.descripcion_producto] += detail.cantidad
            brands[(detail.producto.marca if detail.producto else None) or "Sin marca"] += detail.cantidad
        top_product, _ = _top_entry(products)
        top_brand, _ = _top_entry(brands)
        average = sales / count if count else 0
        kpis = [("Total de ventas", _money(sales)), ("Órdenes", str(count)), ("Ticket promedio", _money(average)), ("Saldo pendiente", _money(balance)), ("Ganancia neta", _money(profit)), ("Producto más pedido", top_product), ("Marca más vendida", top_brand)]
        chart_title = "Ventas por estado de orden"
    elif module == "detalles":
        units = sum((item.cantidad or 0 for item in records), 0)
        sales = sum((item.total_venta or 0 for item in records), Decimal("0"))
        profit = sum((item.ganancia_producto or 0 for item in records), Decimal("0"))
        for item in records:
            groups[item.descripcion_producto] += item.cantidad or 0
        top_product, top_units = _top_entry(groups)
        kpis = [("Unidades ordenadas", str(units)), ("Ventas", _money(sales)), ("Ganancia", _money(profit)), ("Producto más pedido", top_product), ("Unidades del líder", str(top_units))]
        chart_title = "Productos más pedidos"
    elif module == "abonos":
        total = sum((item.valor or 0 for item in records), Decimal("0"))
        for item in records:
            groups[item.metodo_pago or "Sin método"] += item.valor or 0
        top_method, _ = _top_entry(groups)
        kpis = [("Total abonado", _money(total)), ("Número de abonos", str(count)), ("Abono promedio", _money(total / count if count else 0)), ("Método principal", top_method)]
        chart_title = "Abonos por método de pago"
    elif module == "comisiones":
        total = sum((item.valor_comision or 0 for item in records), Decimal("0"))
        pending = sum((item.valor_comision or 0 for item in records if str(item.estado_pago).lower() != "pagada"), Decimal("0"))
        for item in records:
            groups[str(item.vendedor)] += item.valor_comision or 0
        top_seller, _ = _top_entry(groups)
        kpis = [("Comisiones", _money(total)), ("Pendientes", _money(pending)), ("Registros", str(count)), ("Vendedor destacado", top_seller)]
        chart_title = "Comisiones por vendedor"
    elif module == "recibos":
        total = sum((item.total_recibo or 0 for item in records), Decimal("0"))
        for item in records:
            groups[str(item.orden)] += item.total_recibo or 0
        kpis = [("Total facturado", _money(total)), ("Recibos", str(count)), ("Promedio", _money(total / count if count else 0))]
        chart_title = "Valor de recibos por orden"
    else:  # movimientos
        income = sum((item.valor_pesos or 0 for item in records if str(item.tipo_movimiento).lower() in ("ingreso", "entrada")), Decimal("0"))
        expense = sum((item.valor_pesos or 0 for item in records if str(item.tipo_movimiento).lower() in ("egreso", "salida")), Decimal("0"))
        for item in records:
            groups[item.categoria or "Sin categoría"] += item.valor_pesos or 0
        kpis = [("Ingresos", _money(income)), ("Egresos", _money(expense)), ("Balance", _money(income - expense)), ("Movimientos", str(count))]
        chart_title = "Movimientos por categoría"
    return kpis, chart_title, groups


def _bar_chart(title, groups):
    ranked = sorted(groups.items(), key=lambda item: item[1], reverse=True)[:7]
    if not ranked:
        return None
    drawing = Drawing(245 * mm, 55 * mm)
    drawing.add(String(6 * mm, 50 * mm, title, fontName="Helvetica-Bold", fontSize=9, fillColor=BLACK))
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 14 * mm, 10 * mm, 220 * mm, 34 * mm
    chart.data = [[float(value) for _label, value in ranked]]
    chart.categoryAxis.categoryNames = [str(label)[:18] for label, _value in ranked]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.angle = 20
    chart.categoryAxis.labels.dy = -7
    chart.valueAxis.labels.fontSize = 6
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = RED
    chart.bars[0].strokeColor = RED
    drawing.add(chart)
    return drawing


def _executive_chart(title, labels, series, money=True):
    """Vector bars with a shared signed axis and a legend for each series."""
    drawing = Drawing(250 * mm, 76 * mm)
    drawing.add(String(0, 72 * mm, title, fontName="Helvetica-Bold", fontSize=10, fillColor=BLACK))
    drawing.add(String(0, 66 * mm, "Millones de COP" if money else "Cantidad", fontSize=7, fillColor=GRAY))
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 22 * mm, 19 * mm, 220 * mm, 42 * mm
    scale = 1000000 if money else 1
    chart.data = [[float(value or 0) / scale for value in values] for _, values in series]
    chart.categoryAxis.categoryNames = [str(label)[:28] for label in labels]
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.angle = 18
    chart.categoryAxis.labels.dy = -8
    chart.valueAxis.labels.fontSize = 7
    values = [value for row in chart.data for value in row]
    chart.valueAxis.valueMin = min(0, min(values, default=0))
    chart.valueAxis.valueMax = max(0, max(values, default=0)) or (1 if chart.valueAxis.valueMin == 0 else 0)
    palette = (RED, colors.HexColor("#438A68"), BLACK)
    for index, (label, _) in enumerate(series):
        color = palette[index % len(palette)]
        chart.bars[index].fillColor = color
        chart.bars[index].strokeColor = color
        drawing.add(String((65 + index * 65) * mm, 66 * mm, label, fontSize=8, fillColor=color))
    drawing.add(chart)
    return drawing


def build_module_report(module, config, queryset, params):
    output = BytesIO()
    doc = SimpleDocTemplate(
        output, pagesize=landscape(letter), leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=23 * mm,
        title=f"Reporte de {config['title']} - LujoShop", author="LujoShop",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("report-title", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=17, textColor=BLACK, leading=20)
    normal = ParagraphStyle("report-normal", parent=styles["Normal"], fontName="Helvetica", fontSize=7, leading=8.5, textColor=BLACK)
    small = ParagraphStyle("report-small", parent=normal, fontSize=6.4, textColor=GRAY)
    center = ParagraphStyle("report-center", parent=normal, alignment=TA_CENTER)
    right = ParagraphStyle("report-right", parent=normal, alignment=TA_RIGHT)
    white = ParagraphStyle("report-white", parent=normal, alignment=TA_CENTER, fontName="Helvetica-Bold", textColor=colors.white)

    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "lg-transparent-final.png"
    logo = Image(str(logo_path), width=55 * mm, height=14 * mm, kind="proportional")
    generated = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    heading = Table([[logo, Paragraph(f"<b>REPORTE DE {config['title'].upper()}</b><br/><font color='#5C5F62'>Generado: {generated}</font>", right)]], colWidths=[85 * mm, 170 * mm], rowHeights=[18 * mm])
    heading.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLACK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))

    active_filters = []
    labels = {"q": "Búsqueda", "periodo": "Mes"}
    for name, value in params.items():
        if value:
            label = labels.get(name, name.replace("_", " ").replace(" desde", " desde").title())
            active_filters.append(f"<b>{label}:</b> {value}")
    filter_text = " · ".join(active_filters) if active_filters else "Reporte completo del módulo (sin filtros)"
    records = list(queryset)
    story = [heading, Spacer(1, 3 * mm), Paragraph(filter_text, small), Spacer(1, 3 * mm)]

    kpis, chart_title, chart_groups = _analytics(module, records)
    story.append(Paragraph("RESUMEN EJECUTIVO", ParagraphStyle("section-title", parent=normal, fontName="Helvetica-Bold", fontSize=10, textColor=RED)))
    story.append(Spacer(1, 2 * mm))
    kpi_cells = [Paragraph(f"<font color='#5C5F62' size='6'>{label.upper()}</font><br/><b><font size='10'>{value}</font></b>", normal) for label, value in kpis]
    while len(kpi_cells) % 4:
        kpi_cells.append("")
    kpi_rows = [kpi_cells[index:index + 4] for index in range(0, len(kpi_cells), 4)]
    kpi_table = Table(kpi_rows, colWidths=[63.75 * mm] * 4, rowHeights=[14 * mm] * len(kpi_rows))
    kpi_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), .4, BORDER), ("INNERGRID", (0, 0), (-1, -1), .4, BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([kpi_table, Spacer(1, 3 * mm)])
    chart = _bar_chart(chart_title, chart_groups)
    if chart:
        story.extend([Paragraph("ANÁLISIS GRÁFICO", ParagraphStyle("chart-title", parent=normal, fontName="Helvetica-Bold", fontSize=10, textColor=RED)), Spacer(1, 1 * mm), chart, Spacer(1, 3 * mm)])

    story.extend([Paragraph("TOTALES DEL REPORTE", ParagraphStyle("totals-title", parent=normal, fontName="Helvetica-Bold", fontSize=9, textColor=RED)), Spacer(1, 1.5 * mm)])

    totals = []
    for field, label in REPORT_TOTALS.get(module, ()):
        total = sum((getattr(record, field, 0) or 0 for record in records), Decimal("0"))
        totals.append((label, _money(total) if field != "cantidad" and field != "cantidad_disponible" else f"{total:,.0f}".replace(",", ".")))
    cards = [[Paragraph("REGISTROS", white), Paragraph(str(len(records)), center)]]
    for label, value in totals:
        cards.append([Paragraph(label.upper(), white), Paragraph(value, center)])
    card_width = (landscape(letter)[0] - doc.leftMargin - doc.rightMargin) / (len(cards) * 2)
    summary = Table([sum(([label, value] for label, value in cards), [])], colWidths=[card_width] * (len(cards) * 2), rowHeights=[10 * mm])
    style = [("GRID", (0, 0), (-1, -1), .5, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for index in range(0, len(cards) * 2, 2):
        style.append(("BACKGROUND", (index, 0), (index, 0), RED))
    summary.setStyle(TableStyle(style))
    story.extend([summary, Spacer(1, 3 * mm)])

    columns = REPORT_COLUMNS[module]
    data = [[Paragraph(label.upper(), white) for _field, label in columns]]
    for record in records:
        data.append([Paragraph(_display(record, field), right if field in MONEY_FIELDS else normal) for field, _label in columns])
    if not records:
        data.append([Paragraph("No hay registros para los criterios seleccionados.", center)] + [""] * (len(columns) - 1))
    available_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
    widths = [available_width / len(columns)] * len(columns)
    story.extend([Paragraph("DETALLE DE REGISTROS", ParagraphStyle("detail-title", parent=normal, fontName="Helvetica-Bold", fontSize=9, textColor=RED)), Spacer(1, 1.5 * mm)])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RED), ("GRID", (0, 0), (-1, -1), .35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]))
    story.append(table)
    story.extend([Spacer(1, 4 * mm), Paragraph("Este reporte fue generado automáticamente por el sistema de gestión LujoShop.", small)])
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    output.seek(0)
    return output


def build_full_report(context, orders):
    from .executive_pdf import build_executive_report
    return build_executive_report(context, orders)

"""A fixed-height appendix: exactly one page, without changing prior flowables."""
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, Paragraph

from .executive_pdf import GREEN, INK, LINE, MUTED, PALE, RED, WARNING, compact, money


class MonthlyFinancePage(Flowable):
    def __init__(self, data, width):
        super().__init__()
        self.data, self.width, self.height = data, width - 12, 505

    def text(self, text, x, y, size=9, color=INK, bold=False, max_width=None):
        c = self.canv
        font = "Helvetica-Bold" if bold else "Helvetica"
        text = str(text)
        if max_width:
            original = text
            while text and stringWidth(text, font, size) > max_width:
                text = text[:-1]
            if text != original:
                text = text[:-3] + "..." if len(text) > 3 else "..."
        c.setFont(font, size)
        c.setFillColor(color)
        c.drawString(x, y, text)

    def paragraph(self, text, x, top, width, size=8.5, color=MUTED):
        paragraph = Paragraph(escape(text), ParagraphStyle(
            "finance-note", fontName="Helvetica", fontSize=size, leading=size + 2, textColor=color))
        _, height = paragraph.wrap(width, 200)
        paragraph.drawOn(self.canv, x, top - height)
        return height

    def card(self, x, top, width, label, value, note, color=INK):
        c = self.canv
        c.setFillColor(PALE)
        c.setStrokeColor(LINE)
        c.roundRect(x, top - 59, width, 59, 4, fill=1, stroke=1)
        self.text(label, x + 9, top - 13, 8, MUTED, True)
        self.text(value, x + 9, top - 34, 17, color, True, width - 18)
        self.paragraph(note, x + 9, top - 40, width - 18, 8)

    def charts(self):
        c, d = self.canv, self.data
        gap = 12
        panel = (self.width - 2 * gap) / 3
        for i in range(3):
            c.setStrokeColor(LINE)
            c.roundRect(i * (panel + gap), 195, panel, 137, 4, fill=0, stroke=1)
        self.text("Ventas y dinero · COP", 9, 316, 10.5, bold=True)
        rows = [("Ventas registradas", d["registered"], INK),
                ("Dinero recibido", d["received"], GREEN),
                ("Pendiente ventas mes", d["pending"], RED)]
        maximum = max([float(value) for _, value, _ in rows] + [1])
        for i, (label, value, color) in enumerate(rows):
            y = 295 - 30 * i
            self.text(label, 9, y, 8.5)
            self.text(money(value), panel - 102, y, 8.5, color, True)
            c.setFillColor(PALE)
            c.roundRect(9, y - 12, panel - 18, 7, 2, fill=1, stroke=0)
            length = float(value) / maximum * (panel - 18)
            if length > 0:
                c.setFillColor(color)
                c.rect(9, y - 12, length, 7, fill=1, stroke=0)
        self.text("Recaudo incluye ventas de otros meses.", 9, 204, 8, MUTED)

        x = panel + gap
        self.text("Órdenes del mes", x + 9, 316, 10.5, bold=True)
        center_x, center_y, radius = x + 46, 263, 33
        segments = [("paid", "Pagadas", GREEN), ("partial", "Parciales", WARNING),
                    ("pending", "Pendientes", INK), ("cancelled", "Canceladas", RED)]
        count = d["order_count"]
        start = 90
        if not count:
            c.setFillColor(LINE)
            c.circle(center_x, center_y, radius, fill=1, stroke=0)
        for i, (key, label, color) in enumerate(segments):
            n = d["buckets"][key]["count"]
            extent = 360 * n / count if count else 0
            if extent:
                c.setFillColor(color)
                c.wedge(center_x-radius, center_y-radius, center_x+radius, center_y+radius,
                        startAng=start, extent=-extent, fill=1, stroke=0)
                start -= extent
            c.setFillColor(color)
            c.rect(x + 92, 289 - i * 19, 6, 6, fill=1, stroke=0)
            self.text(f"{label}: {n} · {n / count * 100 if count else 0:.0f}%", x + 103, 289 - i * 19, 8.5)
        c.setFillColor(colors.white)
        c.circle(center_x, center_y, 23, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(center_x, center_y - 2, str(count))
        c.setFont("Helvetica", 7.5)
        c.drawCentredString(center_x, center_y - 13, "órdenes")
        self.text("Pago calculado con abonos al corte.", x + 9, 204, 8, MUTED)

        x = 2 * (panel + gap)
        self.text("Evolución diaria de recaudos", x + 9, 316, 10.5, bold=True)
        series = [("current", "Ventas mes", RED), ("previous", "Anteriores", INK)]
        if d["received_other"]:
            series.append(("other", "Otros", WARNING))
        daily = d["daily"]
        left, right, bottom, height = x + 43, x + panel - 14, 233, 58
        maximum = max([float(row[key]) for row in daily for key, _, _ in series] + [1])
        for i, (key, label, color) in enumerate(series):
            self.text(label, x + 9 + i * 76, 303, 8, color, True)
            c.setStrokeColor(color)
            c.setLineWidth(1.5)
            points = [(left + j / max(1, len(daily) - 1) * (right - left),
                       bottom + float(row[key]) / maximum * height) for j, row in enumerate(daily)]
            for first, second in zip(points, points[1:]):
                c.line(*first, *second)
            c.setFillColor(color)
            for px, py in points:
                c.circle(px, py, 1.5, fill=1, stroke=0)
        c.setLineWidth(.5)
        c.setStrokeColor(LINE)
        c.line(left, bottom, right, bottom)
        self.text("0", x + 9, bottom - 2, 7.5, MUTED)
        self.text(compact(maximum) if maximum != 1 else "$ 0", x + 9, bottom + height - 2, 7, MUTED)
        for i in sorted({0, len(daily)//2, len(daily)-1}):
            if i >= 0 and daily:
                px = left + i / max(1, len(daily)-1) * (right-left)
                self.text(daily[i]["date"].strftime("%d/%m"), px - 10, 219, 7.5, MUTED)
        self.text("Por fecha de abono · días sin cobro = $ 0", x + 9, 204, 8, MUTED)

    def tracking(self):
        c, data = self.canv, self.data
        rows = data["tracking"]
        # Reserve room for every available category rather than hiding all
        # cancellations behind a long list of overdue orders.
        selected = []
        for condition in (lambda r: r["overdue"], lambda r: r["cancelled"],
                          lambda r: not r["overdue"] and not r["cancelled"]):
            selected.extend([r for r in rows if condition(r) and r not in selected][:2])
        selected.extend([r for r in rows if r not in selected][:6-len(selected)])
        self.text("Seguimiento · canceladas, pendientes y atrasadas", 0, 180, 11, bold=True)
        self.text(f"{len(selected)} de {len(rows)} casos · prioridad: más de 10 días", self.width - 243, 180, 8, MUTED)
        positions = [0, 75, 266, 365, 464, 644]
        headers = ["Orden", "Cliente", "Valor COP", "Saldo COP", "Estado actual / alerta", "Edad"]
        c.setFillColor(INK)
        c.rect(0, 157, self.width, 17, fill=1, stroke=0)
        for x, header in zip(positions, headers):
            self.text(header, x + 6, 162, 8, colors.white, True)
        for index, row in enumerate(selected):
            y = 140 - index * 16
            if index % 2 == 0:
                c.setFillColor(PALE)
                c.rect(0, y - 4, self.width, 16, fill=1, stroke=0)
            alert = " / >10 días" if row["overdue"] else ""
            values = [row["number"], row["client"], money(row["total"]), money(row["balance"]),
                      row["state"] + alert, f'{row["age"]} d']
            widths = [69, 185, 93, 93, 174, self.width - 650]
            for x, value, width in zip(positions, values, widths):
                self.text(value, x + 6, y, 8, RED if row["cancelled"] else INK, max_width=width)
        if not selected:
            self.text("Sin órdenes para seguimiento en este corte.", 6, 140, 9, MUTED)

    def draw(self):
        d = self.data
        self.text("Control financiero y recaudos", 0, 486, 22, bold=True)
        self.text(f'{d["period_label"]} · Corte {d["close_date"]:%d/%m/%Y} · Importes en COP', 0, 470, 9.5, MUTED)
        width = (self.width - 24) / 4
        cards = [
            ("VENTAS REGISTRADAS", money(d["registered"]), f'{d["order_count"]} órdenes · incluye canceladas', INK),
            ("VENTAS CANCELADAS", money(d["cancelled_value"]), f'{d["cancelled_count"]} órdenes del mes, hoy canceladas', RED),
            ("DINERO RECIBIDO · ABONOS", money(d["received"]), f'De ventas del mes: {money(d["received_current"])}', GREEN),
            ("DINERO PENDIENTE · MES", money(d["pending"]), f'{d["paid_percent"]:.1f}% cobrado de ventas no canceladas'.replace('.', ','), RED),
            ("VENTAS CONTRA ENTREGA", "Sin identificar", f'{d["unresolved_count"]} por entregar/cobrar · modalidad sin dato', INK),
            ("PAGOS PARCIALES · MES", money(d["partial_paid"]), f'{d["partial_count"]} órdenes · saldo {money(d["partial_pending"])}', WARNING),
            ("RECAUDOS DE MESES ANTERIORES", money(d["received_previous"]), f'Cartera anterior aún pendiente: {money(d["previous_pending"])}', GREEN),
            ("ÓRDENES ATRASADAS · >10 DÍAS", str(d["overdue_count"]), f'Saldo por cobrar: {money(d["overdue_balance"])}', RED),
        ]
        for i, (label, value, note, color) in enumerate(cards):
            self.card((i % 4) * (width + 8), 462 - (i // 4) * 65, width, label, value, note, color)
        self.charts()
        self.tracking()
        notes = (
            "Base: fecha de la orden, sin cotizaciones. Abonos por fecha, contados una vez; no se suman los movimientos de caja. "
            "Recibido = abonos registrados únicamente después de recibir el dinero. La modalidad contra entrega no está identificada en el sistema. "
            "Saldos al corte; entregas y cancelaciones según estado actual, sin historial de fechas. Parciales: abonos acumulados de esas órdenes. "
            "Atraso: más de 10 días desde la orden, sin asumir fecha pactada. Canceladas sin saldo exigible; recaudo bruto, sin descontar devoluciones."
        )
        if d["received_other"]:
            notes += f' Otros recaudos (órdenes posteriores al mes): {money(d["received_other"])}.'
        if d["receipts_on_cancelled"]:
            notes += f' Abonos en órdenes hoy canceladas: {money(d["receipts_on_cancelled"])}.'
        self.paragraph(notes, 0, 47, self.width, 8)

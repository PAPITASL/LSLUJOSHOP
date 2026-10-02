"""Presentation only: render the existing report context without database access."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable, KeepTogether


INK = colors.HexColor('#191919')
RED = colors.HexColor('#C82932')
MUTED = colors.HexColor('#55585C')
PALE = colors.HexColor('#F3F4F5')
LINE = colors.HexColor('#DBDDE0')
GREEN = colors.HexColor('#276746')
WARNING = colors.HexColor('#925B17')


def money(value):
    return '$ ' + format(value or 0, ',.0f').replace(',', '.')


def compact(value):
    value = float(value or 0)
    if abs(value) >= 1000000:
        return ('$ {:.1f} M'.format(value / 1000000)).replace('.', ',')
    return money(value)


def variation(data):
    if not data or data.get('value') is None:
        return 'Sin período comparable', MUTED
    sign = '+' if data['icon'] == 'arrow-up' else '-' if data['icon'] == 'arrow-down' else ''
    return f"{sign}{data['value']:.1f}% vs mes anterior".replace('.', ','), GREEN if data['direction'] == 'good' else RED if data['direction'] == 'bad' else MUTED


def monthly_summary(context):
    from .report_insights import build_monthly_insights
    findings = context.get("monthly_insights")
    if findings is None:
        findings = build_monthly_insights(context)
    return [finding["text"] for finding in findings]


class Bars(Flowable):
    """Horizontal signed bars with directly printed values and wrapped labels."""
    def __init__(self, rows, width, currency=True, color=RED):
        super().__init__()
        self.rows, self.width, self.currency, self.color = rows, width, currency, color
        self.height = max(45, len(rows) * 45)

    def draw(self):
        c = self.canv
        if not self.rows:
            c.setFillColor(MUTED)
            c.setFont('Helvetica', 11)
            c.drawString(0, 22, 'Sin registros para este período.')
            return
        label_width = self.width * .37
        value_width = 116 if self.width > 450 else 92
        bar_width = self.width - label_width - value_width - 18
        maximum = max([abs(float(v or 0)) for _, v in self.rows] + [1])
        negative = any(float(v or 0) < 0 for _, v in self.rows)
        available = bar_width / 2 if negative else bar_width
        origin = label_width + (available if negative else 0)
        for index, (label, value) in enumerate(self.rows):
            y = self.height - index * 45 - 27
            style = ParagraphStyle('bar-label', fontName='Helvetica', fontSize=10.5, leading=12, textColor=INK)
            p = Paragraph(escape(str(label or 'Sin información')), style)
            _, h = p.wrap(label_width - 10, 44)
            p.drawOn(c, 0, y + 6 - h / 2)
            c.setFillColor(PALE)
            c.roundRect(label_width, y, bar_width, 12, 3, fill=1, stroke=0)
            length = abs(float(value or 0)) / maximum * available
            c.setFillColor(RED if float(value or 0) < 0 else self.color)
            if length:
                c.roundRect(origin - length if float(value or 0) < 0 else origin, y, length, 12, min(3, length / 2), fill=1, stroke=0)
            c.setFont('Helvetica-Bold', 10.5)
            c.setFillColor(INK)
            c.drawRightString(self.width, y + 2, compact(value) if self.currency else str(value or 0))


class Trend(Flowable):
    def __init__(self, rows, width):
        super().__init__()
        self.rows, self.width, self.height = rows, width, 190

    def draw(self):
        c = self.canv
        if not self.rows:
            c.setFont('Helvetica', 11)
            c.drawString(0, 90, 'Sin ventas registradas para este período.')
            return
        lo = min([0] + [float(r[k] or 0) for r in self.rows for k in ('sales', 'profit')])
        hi = max([1] + [float(r[k] or 0) for r in self.rows for k in ('sales', 'profit')])
        left, right, bottom, height = 60, self.width - 60, 36, 105
        def point(i, value):
            return left + (right-left) * i / max(1, len(self.rows)-1), bottom + (float(value or 0)-lo)/(hi-lo)*height
        c.setStrokeColor(LINE)
        _, zero_y = point(0, 0)
        c.line(left, zero_y, right, zero_y)
        for key, label, color, offset in [('sales', 'Ventas', RED, 12), ('profit', 'Utilidad después de comisiones', INK, -17)]:
            c.setFillColor(color)
            c.setFont('Helvetica-Bold', 10.5)
            c.drawString(0 if key == 'sales' else 180, 177, label)
            c.setStrokeColor(color)
            c.setLineWidth(2)
            points = [point(i, row[key]) for i, row in enumerate(self.rows)]
            for (x1,y1),(x2,y2) in zip(points, points[1:]):
                c.line(x1,y1,x2,y2)
            for x,y in points:
                c.circle(x,y,3,fill=1,stroke=0)
            for i in sorted({0, len(points)-1, max(range(len(points)), key=lambda j: float(self.rows[j][key] or 0))}):
                x,y = points[i]
                c.drawCentredString(x,y+offset,compact(self.rows[i][key]))
        c.setFillColor(MUTED)
        c.setFont('Helvetica', 10.5)
        for i in sorted({0, len(self.rows)//2, len(self.rows)-1}):
            x,_ = point(i,0)
            c.drawCentredString(x,10,str(self.rows[i]['label']))


def build_executive_report(context, orders):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=36, rightMargin=36,
                            topMargin=32, bottomMargin=38, title=f"LUJOSHOP · {context['period_label']}", author='LUJOSHOP')
    width = doc.width
    styles = {
        'body': ParagraphStyle('body', fontName='Helvetica', fontSize=11, leading=15, textColor=INK),
        'muted': ParagraphStyle('muted', fontName='Helvetica', fontSize=10.5, leading=14, textColor=MUTED),
        'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=26, leading=30, textColor=INK),
        'month': ParagraphStyle('month', fontName='Helvetica-Bold', fontSize=21, leading=25, textColor=RED),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold', fontSize=17, leading=21, textColor=INK, keepWithNext=True),
        'table': ParagraphStyle('table', fontName='Helvetica', fontSize=10, leading=13, textColor=INK),
        'thead': ParagraphStyle('thead', fontName='Helvetica-Bold', fontSize=10.5, leading=14, textColor=colors.white),
    }
    def p(text, style='body'):
        return Paragraph(escape(str(text if text is not None else 'No disponible')).replace("\n", "<br/>"), styles[style])
    story = []
    def heading(title, subtitle=None, new=True):
        if new:
            story.append(PageBreak())
        story.extend([p(title,'section'), Spacer(1,8)])
        if subtitle:
            story.extend([p(subtitle,'muted'),Spacer(1,12)])

    def cards(items, columns=4, show_comparison=True):
        gap = 10
        card_width = (width-gap*(columns-1))/columns
        cells = []
        for label, value, comparison, note in items:
            change, color = variation(comparison)
            number = ParagraphStyle('number',fontName='Helvetica-Bold',fontSize=20,leading=25,textColor=INK)
            small = ParagraphStyle('change',fontName='Helvetica',fontSize=10.5,leading=13,textColor=color)
            cell = [p(label,'muted'),Spacer(1,5),Paragraph(escape(str(value)),number)]
            if show_comparison:
                cell += [Spacer(1,5),Paragraph(escape(change),small)]
            if note:
                cell += [p(note,'muted')]
            card=Table([[cell]],colWidths=[card_width])
            card.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('BOX',(0,0),(-1,-1),.4,LINE),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
            cells.append(card)
        for start in range(0,len(cells),columns):
            row=[]
            for cell in cells[start:start+columns]:
                if row: row.append('')
                row.append(cell)
            widths=[]
            for index in range(len(row)): widths.append(gap if index%2 else card_width)
            table=Table([row],colWidths=widths,hAlign="LEFT")
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
            story.extend([table,Spacer(1,8)])

    def table(title, headers, rows, widths=None):
        story.extend([p(title,'section'),Spacer(1,8)])
        values=[[p(v,'thead') for v in headers]]
        values += [[p(v,'table') for v in row] for row in rows]
        if len(values)==1: values.append([p('Sin registros','table')]+['']*(len(headers)-1))
        t=Table(values,colWidths=widths or [width/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),INK),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,0),2,RED)]))
        story.extend([t,Spacer(1,18)])

    story.extend([p('LUJOSHOP · '+context['report_title'],'title'),Spacer(1,5),p(context['period_label'],'month'),Spacer(1,5),p('Período: '+(context['period_range'] or ', '.join(context['selected_periods']) or 'Todo el historial')+'  |  Comparado con: '+(context['comparison_label'] or 'Sin período comparable'),'muted'),p('Generado: '+context['generated_at'].strftime('%d/%m/%Y %H:%M')+' · Bogotá','muted'),Spacer(1,14)])
    cards([
        ('VENTAS',compact(context['total_sales']),context['sales_variation'],None),
        ('UTILIDAD BRUTA',compact(context['gross_profit']),None,None),
        ('DINERO RECAUDADO',compact(context['payments_total']),None,None),
        ('PENDIENTE POR COBRAR',compact(context['pending_balance']),None,None),
        ('ÓRDENES',context['orders_count'],context['orders_variation'],None),
        ('TICKET PROMEDIO',compact(context['ticket_average']),None,None),
        ('CLIENTES',context['active_clients'],None,None),
        ('UNIDADES',context['products_sold'],None,None),
    ])
    story.extend([Spacer(1,8),p('EL MES EN 30 SEGUNDOS','section'),Spacer(1,6)])
    for sentence in monthly_summary(context):
        story.extend([p('• '+sentence),Spacer(1,4)])

    heading('¿Cuánto quedó y cuánto dinero se movió?', 'Ventas y rentabilidad de las órdenes seleccionadas. El recaudo y los movimientos corresponden a sus propias fechas.')
    panels=[]
    for title,rows in [
        ('Resultado comercial', [('Ventas',context['total_sales']),('Costos totales registrados',context['total_costs']),('Utilidad bruta',context['gross_profit']),('Comisiones',context['commissions']),('Después de comisiones',context['total_profit'])]),
        ('Dinero del período',[('Entradas totales',context['income']),('Salidas',context['expenses']),('Flujo neto',context['cash_balance'])])]:
        panels.append([p(title,'section'),Spacer(1,12),Bars(rows,(width-28)/2)])
    t=Table([[panels[0],'',panels[1]]],colWidths=[(width-28)/2,28,(width-28)/2])
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story.extend([t,Spacer(1,20),p(f"Margen después de comisiones: {context['margin']:.1f}%"),p('El recaudo forma parte de las entradas: no se suman entre sí. Los costos registrados no equivalen necesariamente a pagos realizados.','muted'),Spacer(1,8),p('Gastos operativos y utilidad operativa: información insuficiente para separarlos de forma fiable.','muted')])

    timeline=context['timeline']
    for start in range(0,max(1,len(timeline)),36):
        rows=timeline[start:start+36]
        heading('¿Cómo evolucionaron las ventas?', 'Ventas en rojo · Resultado después de comisiones en negro. Fechas sin registros no aparecen en la serie existente.')
        story.extend([Trend(rows,width),Spacer(1,20)])
        if start == 0:
            story.extend([p('Resultado después de comisiones vs período anterior', 'section'),
                          Spacer(1, 8), p(variation(context['profit_variation'])[0]),
                          Spacer(1, 8), p('Los valores exactos por fecha están en el anexo de evolución.', 'muted')])

    rankings = [
        ('top_products', '¿Qué categorías vendieron más?', 'categoria_reporte', 'sales'),
        ('profitable_products', '¿Cuáles dejaron más ganancia?', 'categoria_reporte', 'profit'),
        ('brands', '¿Qué marcas generaron negocio?', 'marca_reporte', 'sales'),
        ('vehicles', '¿Qué vehículos tuvieron demanda?', 'modelo_reporte', 'sales'),
        ('sellers_chart', '¿Quiénes generaron ventas?', 'vendedor__nombre', 'sales'),
        ('cities', '¿Dónde estuvieron los compradores?', 'cliente__ciudad', 'sales'),
    ]
    page_titles = ['¿Qué productos funcionaron mejor?', '¿Qué marcas y vehículos generaron negocio?', '¿Qué equipo y ciudades impulsaron las ventas?']
    for start in range(0, len(rankings), 2):
        heading(page_titles[start//2], 'Hasta cinco resultados por gráfico. Todas las cifras y referencias están en el anexo.')
        panels = []
        for key, title, label_key, metric in rankings[start:start+2]:
            rows = context[key][:5]
            labels = [f"{r['marca_reporte']} {r[label_key]}" if key == 'vehicles' else r[label_key] or 'Sin ciudad' for r in rows]
            panels.append([p(title,'section'), Spacer(1,18), Bars(list(zip(labels,[r[metric] for r in rows])), (width-32)/2, color=RED if metric=='sales' else INK)])
        t=Table([[panels[0], '', panels[1]]], colWidths=[(width-32)/2,32,(width-32)/2])
        t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
        story.extend([t,Spacer(1,24)])
        if start == 0:
            story.append(p('Las ventas por categoría provienen de los detalles, antes del descuento general. La ganancia del detalle no incluye comisiones ni otros costos generales.','muted'))
        elif start == 4:
            story.append(p('Vendedores y ciudades registrados en las órdenes y fichas actuales de los clientes.','muted'))

    heading('¿En qué estado están los pedidos?', 'Estados actuales de las órdenes seleccionadas. No equivalen a entregas ocurridas dentro del mes.')
    story.extend([Bars([(r['label'],r['value']) for r in context['status_chart']],width,currency=False,color=INK),Spacer(1,10)])
    heading('¿Cómo está el inventario hoy?',context['inventory_note'])
    cards([('VALOR ESTIMADO',compact(context['inventory_value']),None,None),('UNIDADES FÍSICAS',context['inventory_units'],None,None),('REFERENCIAS',context['inventory_products'],None,None)], show_comparison=False)
    story.extend([Bars([('Referencias con stock bajo',context['low_stock_count']),('Referencias agotadas',context['exhausted_count'])],width,currency=False,color=WARNING),Spacer(1,16)])
    story.append(p('Stock bajo: entre 1 y 5 unidades por referencia. Agotado: sin existencias registradas. Las acciones de reposición del cierre solo se activan cuando también hay pedidos en el período.','muted'))
    story.append(p('Baja rotación: información insuficiente para calcularla.','muted'))

    story.extend([PageBreak(), p('CIERRE DEL MES', 'title'), Spacer(1, 5),
                  p(context['period_label'], 'month'), Spacer(1, 12),
                  p('1. RESULTADO', 'section'), Spacer(1, 8)])
    cards([
        ('VENTAS', compact(context['total_sales']), None, None),
        ('DESPUÉS DE COMISIONES', compact(context['total_profit']), None,
         f"Margen: {context['margin']:.1f}%".replace('.', ',')),
        ('RECAUDO', compact(context['payments_total']), None, None),
        ('ÓRDENES', context['orders_count'], None, None),
    ], show_comparison=False)
    story.append(Spacer(1, 12))
    findings = context.get('monthly_insights', [])[:3]
    left = [p('2. PRINCIPALES HALLAZGOS', 'section'), Spacer(1, 14)]
    for item in findings:
        emphasis = RED if item['priority'] == 'HIGH' else INK
        label = 'ATENCIÓN' if item['priority'] == 'HIGH' else 'DATO DEL MES'
        flag = ParagraphStyle('closing-flag', parent=styles['muted'], fontName='Helvetica-Bold', textColor=emphasis)
        left += [Paragraph(label, flag), Spacer(1, 4), p(item['text']), Spacer(1, 14)]
    if not findings:
        left.append(p('No hay hallazgos suficientes para este período.', 'muted'))

    priorities = context.get('next_month_priorities', [])[:5]
    area_labels = {'ventas': 'VENTAS / PRODUCTO', 'cartera': 'CARTERA', 'inventario': 'INVENTARIO',
                   'clientes': 'CLIENTES', 'marketing': 'MARKETING', 'operaciones': 'OPERACIONES'}
    priority_labels = {'high': 'Alta', 'medium': 'Media', 'low': 'Baja'}
    right = [p('3. PRIORIDADES PRÓXIMO MES', 'section'), Spacer(1, 14)]
    for index, item in enumerate(priorities, 1):
        right += [p(f"{index:02d} · {area_labels[item['area']]} · Prioridad {priority_labels[item['priority']]}", 'muted'),
                  Spacer(1, 3), p(item['action']), Spacer(1, 10)]
    if not priorities:
        right.append(p('No se activaron prioridades con las reglas y la información disponibles para este período.'))
    elif len(priorities) < 3:
        right.append(p('Solo se incluyen acciones con evidencia suficiente.', 'muted'))
    closing = Table([[left, '', right]], colWidths=[width*.34, 26, width*.66-26])
    closing.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0), ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(closing)

    heading('Anexo · Alcance y cifras exactas','Datos de respaldo para consultar después del resumen gerencial.')
    story.extend([p(context['temporal_note']),Spacer(1,8),p(context['inventory_note']),Spacer(1,8),p('Unidades = cantidades pedidas. Clientes = compradores distintos de las órdenes seleccionadas. Pendiente por cobrar = saldo de esas órdenes, no cartera total del negocio.','muted'),Spacer(1,16)])
    table('Importes sin abreviar',['Concepto','Valor'],[(label,money(context[key])) for key,label in [('total_sales','Ventas'),('total_costs','Costos totales'),('gross_profit','Utilidad bruta'),('commissions','Comisiones'),('total_profit','Resultado después de comisiones'),('discounts','Descuentos'),('ticket_average','Ticket promedio'),('total_paid','Abonado a las órdenes seleccionadas'),('pending_balance','Pendiente por cobrar'),('payments_total','Recaudo del período'),('income','Entradas'),('expenses','Salidas'),('cash_balance','Flujo neto'),('inventory_value','Valor del inventario')]])
    table('Clientes y disponibilidad de información',['Indicador','Resultado'],[('Compradores',context['active_clients']),('Clientes registrados en el período',context['new_clients']),('Clientes recurrentes y recompra','Información insuficiente en el reporte actual'),('Canales de adquisición','Información insuficiente'),('Metas','No disponibles en el reporte actual')])
    for key,title,label_key in [('top_products','Categorías','categoria_reporte'),('brands','Marcas','marca_reporte'),('vehicles','Vehículos','modelo_reporte')]:
        heading('Anexo · '+title,new=True)
        table('Detalle completo',['Referencia','Unidades','Ventas','Ganancia del detalle'],[(f"{r['marca_reporte']} {r[label_key]}" if key=='vehicles' else r[label_key],r['units'],money(r['sales']),money(r['profit'])) for r in context[key]], [width*.4,width*.12,width*.24,width*.24])
    heading('Anexo · Equipo y ciudades')
    table('Vendedores',['Vendedor','Órdenes','Ventas','Resultado','Comisión'],[(r['vendedor__nombre'],r['orders'],money(r['sales']),money(r['profit']),money(r['commission'])) for r in context['sellers_chart']], [width*.24,width*.1,width*.22,width*.22,width*.22])
    table('Ciudades',['Ciudad','Clientes','Ventas'],[(r['cliente__ciudad'] or 'Sin ciudad',r['clients'],money(r['sales'])) for r in context['cities']])
    heading('Anexo · Evolución completa')
    table('Fechas con registros',['Fecha','Ventas','Resultado después de comisiones'],[(r['label'],money(r['sales']),money(r['profit'])) for r in timeline])
    heading('Anexo · Órdenes','Valores exactos. La situación de entrega corresponde al estado registrado actualmente.')
    order_rows=[]
    for order in orders:
        from django.utils import timezone
        local=timezone.localtime(order.fecha) if timezone.is_aware(order.fecha) else order.fecha
        order_rows.append((f"{order.numero_orden} · {local:%d/%m/%Y}\n{order.cliente}\n{order.estado}",money(order.total_venta),money(order.total_abonado),money(order.saldo_pendiente),money(order.ganancia_neta)))
    table('Seguimiento de órdenes',['Orden / cliente / estado','Venta','Abonado','Pendiente','Resultado'],order_rows,[width*.36,width*.16,width*.16,width*.16,width*.16])

    def footer(canvas,document):
        canvas.saveState()
        canvas.setStrokeColor(RED)
        canvas.setLineWidth(2)
        canvas.line(36,25,70,25)
        canvas.setFont('Helvetica',10.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(80,21,'LUJOSHOP · '+context['period_label'])
        canvas.drawRightString(landscape(A4)[0]-36,21,str(document.page))
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    output.seek(0)
    return output

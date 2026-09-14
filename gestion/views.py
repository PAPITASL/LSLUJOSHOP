from datetime import date, timedelta
from decimal import Decimal
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, F, Max, Min, Q, Sum, Value
from django.db.models.functions import Coalesce, NullIf, TruncDay, TruncMonth, TruncWeek
from django.shortcuts import get_object_or_404, redirect, render
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone

from .forms import DetalleOrdenFormSet, FORM_CLASSES, PRODUCT_CATEGORIES
from .models import (
    Abonos, Clientes, Comisiones, DetalleOrden, MovimientosDinero,
    Ordenes, Productos, Recibos, Vendedores,
)
from .services import obtener_trm_oficial
from .receipt_pdf import build_order_receipt
from .report_pdf import build_module_report
from .excel_import import IMPORT_CONFIG, build_template, import_excel


@login_required
def order_preview(request, pk):
    order = get_object_or_404(Ordenes.objects.select_related("cliente", "vendedor"), pk=pk)
    return render(request, "gestion/order_preview.html", {
        "order": order,
        "details": DetalleOrden.objects.filter(orden=order).order_by("pk"),
    })


MODULES = {
    "productos": {"model": Productos, "title": "Productos", "icon": "box-seam", "search": ("nombre", "categoria", "marca", "modelo", "estado"), "columns": (("nombre", "Producto"), ("categoria", "Categoría"), ("marca", "Marca"), ("modelo", "Modelo"), ("cantidad_disponible", "Existencias"), ("precio_venta_sugerido", "Precio"), ("estado", "Estado"))},
    "clientes": {"model": Clientes, "title": "Clientes", "icon": "people", "search": ("nombre", "telefono", "ciudad"), "columns": (("nombre", "Nombre"), ("telefono", "Teléfono"), ("ciudad", "Ciudad"), ("direccion", "Dirección"))},
    "vendedores": {"model": Vendedores, "title": "Vendedores", "icon": "person-badge", "search": ("nombre", "telefono"), "columns": (("nombre", "Nombre"), ("telefono", "Teléfono"), ("porcentaje_comision", "Comisión %"), ("activo", "Activo"))},
    "ordenes": {"model": Ordenes, "title": "Órdenes", "icon": "receipt", "search": ("numero_orden", "cliente__nombre", "estado"), "columns": (("numero_orden", "Número"), ("fecha", "Fecha"), ("cliente", "Cliente"), ("total_venta", "Total"), ("saldo_pendiente", "Saldo"), ("estado", "Estado"))},
    "detalles": {"model": DetalleOrden, "title": "Detalle de órdenes", "icon": "list-check", "search": ("orden__numero_orden", "descripcion_producto"), "columns": (("orden", "Orden"), ("descripcion_producto", "Producto"), ("cantidad", "Cantidad"), ("cantidad_recibida", "Recibida"), ("total_venta", "Venta"), ("ganancia_producto", "Ganancia"))},
    "abonos": {"model": Abonos, "title": "Abonos", "icon": "cash-coin", "search": ("orden__numero_orden", "metodo_pago", "referencia"), "columns": (("orden", "Orden"), ("fecha", "Fecha"), ("valor", "Valor"), ("metodo_pago", "Método"), ("referencia", "Referencia"))},
    "comisiones": {"model": Comisiones, "title": "Comisiones", "icon": "percent", "search": ("orden__numero_orden", "vendedor__nombre", "estado_pago"), "columns": (("orden", "Orden"), ("vendedor", "Vendedor"), ("valor_comision", "Valor"), ("estado_pago", "Estado"), ("fecha_pago", "Fecha pago"))},
    "recibos": {"model": Recibos, "title": "Recibos", "icon": "file-earmark-text", "search": ("numero_recibo", "orden__numero_orden", "generado_por"), "columns": (("numero_recibo", "Número"), ("orden", "Orden"), ("fecha_generacion", "Fecha"), ("total_recibo", "Total"), ("generado_por", "Generado por"))},
    "movimientos": {"model": MovimientosDinero, "title": "Movimientos", "icon": "wallet2", "search": ("descripcion", "categoria", "referencia", "tipo_movimiento"), "columns": (("fecha", "Fecha"), ("tipo_movimiento", "Tipo"), ("categoria", "Categoría"), ("descripcion", "Descripción"), ("valor_pesos", "Valor COP"))},
}

MODULE_FILTERS = {
    "productos": (("categoria", "Categoría", "distinct"), ("marca", "Marca", "distinct"), ("modelo", "Modelo", "distinct"), ("estado", "Estado", "distinct"), ("cantidad_disponible", "Existencias", "range")),
    "clientes": (("ciudad", "Ciudad", "distinct"),),
    "vendedores": (("activo", "Estado", "boolean"),),
    "ordenes": (("estado", "Estado", "distinct"), ("cliente", "Cliente", "foreign"), ("vendedor", "Vendedor", "foreign"), ("fecha", "Fecha", "date")),
    "detalles": (("orden", "Orden", "foreign"), ("producto", "Producto", "foreign")),
    "abonos": (("orden", "Orden", "foreign"), ("metodo_pago", "Método de pago", "distinct"), ("fecha", "Fecha", "date")),
    "comisiones": (("estado_pago", "Estado de pago", "distinct"), ("vendedor", "Vendedor", "foreign"), ("orden", "Orden", "foreign")),
    "recibos": (("orden", "Orden", "foreign"), ("fecha_generacion", "Fecha", "date")),
    "movimientos": (("tipo_movimiento", "Tipo", "distinct"), ("categoria", "Categoría", "distinct"), ("moneda", "Moneda", "distinct"), ("fecha", "Fecha", "date")),
}

REPORT_DATE_FIELDS = {
    "productos": "creado_en", "clientes": "creado_en", "vendedores": "creado_en",
    "ordenes": "fecha", "detalles": "creado_en", "abonos": "fecha",
    "comisiones": "creado_en", "recibos": "fecha_generacion", "movimientos": "fecha",
}


def _dashboard_bars(rows, label_key, value_key, demo):
    """Normaliza datos para barras SVG; usa demostración solo si no hay datos."""
    source = rows or demo
    maximum = max((float(row[value_key] or 0) for row in source), default=0) or 1
    return [{
        "label": str(row[label_key] or "Sin definir"), "value": float(row[value_key] or 0),
        "percent": round(float(row[value_key] or 0) / maximum * 100, 1),
    } for row in source], not bool(rows)


def _dashboard_donut(rows, label_key, value_key, demo):
    """Genera segmentos de un gráfico circular SVG usando pathLength=100."""
    colors = ("#e6313a", "#202221", "#f0a51a", "#438a68", "#4263c7", "#85888a")
    source = rows or demo
    total = sum(float(row[value_key] or 0) for row in source) or 1
    offset, segments = 0, []
    for index, row in enumerate(source):
        percent = round(float(row[value_key] or 0) / total * 100, 1)
        segments.append({"label": str(row[label_key] or "Sin definir"), "value": row[value_key], "percent": percent, "remainder": 100 - percent, "offset": -offset, "color": colors[index % len(colors)]})
        offset += percent
    return segments, sum(float(row[value_key] or 0) for row in source), not bool(rows)


def _apply_module_filters(records, request, module, config):
    query = request.GET.get("q", "").strip()
    if query:
        search_filter = Q()
        for field in config["search"]:
            search_filter |= Q(**{f"{field}__icontains": query})
        records = records.filter(search_filter)

    for field_name, _label, filter_type in MODULE_FILTERS.get(module, ()):
        if filter_type in ("date", "range"):
            start, end = request.GET.get(f"{field_name}_desde", ""), request.GET.get(f"{field_name}_hasta", "")
            if start:
                lookup = f"{field_name}__date__gte" if filter_type == "date" else f"{field_name}__gte"
                records = records.filter(**{lookup: start})
            if end:
                lookup = f"{field_name}__date__lte" if filter_type == "date" else f"{field_name}__lte"
                records = records.filter(**{lookup: end})
            continue
        value = request.GET.get(field_name, "")
        if value != "":
            if filter_type == "boolean":
                records = records.filter(**{field_name: value == "1"})
            elif filter_type == "text":
                records = records.filter(**{f"{field_name}__icontains": value})
            else:
                records = records.filter(**{field_name: value})

    period = request.GET.get("periodo", "")
    if period:
        try:
            year, month = (int(part) for part in period.split("-", 1))
            date_field = REPORT_DATE_FIELDS[module]
            records = records.filter(**{f"{date_field}__year": year, f"{date_field}__month": month})
        except (ValueError, KeyError):
            pass
    return records, query


def _valid_month_period(value):
    """Devuelve YYYY-MM únicamente cuando representa un mes real."""
    try:
        year, month = (int(part) for part in value.split("-", 1))
        return date(year, month, 1).strftime("%Y-%m")
    except (AttributeError, TypeError, ValueError):
        return ""


def _module_or_404(module):
    from django.http import Http404
    if module not in MODULES:
        raise Http404("Módulo no encontrado")
    return MODULES[module]


def _next_order_number():
    """Calcula el siguiente consecutivo, comenzando en 275."""
    numbers = Ordenes.objects.values_list("numero_orden", flat=True)
    numeric_values = []
    for number in numbers:
        text = str(number).strip()
        if text.isdigit():
            numeric_values.append(int(text))
    return str(max(numeric_values, default=274) + 1)


def _order_receipt_filename(client_name):
    """Construye un nombre legible y valido para el PDF descargado."""
    safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', " ", str(client_name or "")).strip(" .")
    safe_name = re.sub(r"\s+", " ", safe_name) or "Cliente"
    return f"Orden - {safe_name}.pdf"


def _sync_order_commission(order):
    """Crea o actualiza la comisión sin sobrescribir una comisión ya pagada."""
    existing = Comisiones.objects.filter(orden=order).order_by("pk").first()
    if not order.vendedor_id:
        if existing and str(existing.estado_pago).upper() != "PAGADA":
            existing.delete()
        return None

    percentage = order.vendedor.porcentaje_comision or Decimal("0")
    # La comision se calcula sobre el valor total facturado, no sobre la
    # utilidad de la orden.
    base = max(order.total_venta or Decimal("0"), Decimal("0"))
    value = base * percentage / Decimal("100")
    state = "PENDIENTE POR PAGAR" if (order.saldo_pendiente or 0) <= 0 else "EN ESPERA"
    if existing:
        existing.vendedor = order.vendedor
        existing.porcentaje = percentage
        existing.base_comision = base
        existing.valor_comision = value
        if str(existing.estado_pago).upper() != "PAGADA":
            existing.estado_pago = state
            existing.fecha_pago = None
        existing.save()
        return existing
    return Comisiones.objects.create(
        orden=order, vendedor=order.vendedor, porcentaje=percentage,
        base_comision=base, valor_comision=value, estado_pago=state,
    )


def _sync_payment_movement(payment, order):
    """Registra el ingreso del abono una sola vez y conserva su trazabilidad."""
    last_payment_id = Abonos.objects.filter(orden=order).order_by("fecha", "pk").values_list("pk", flat=True).last()
    is_fully_paid = (order.saldo_pendiente or 0) <= 0 and payment.pk == last_payment_id
    category = "PRODUCTO PAGADO" if is_fully_paid else "ABONO"
    description = (
        f"{category.title()} del cliente {order.cliente.nombre} · "
        f"Orden {order.numero_orden}"
    )
    MovimientosDinero.objects.update_or_create(
        referencia=f"AUTO-ABONO-{payment.pk}",
        defaults={
            "fecha": payment.fecha,
            "tipo_movimiento": "ENTRADA",
            "categoria": category,
            "descripcion": description,
            "valor_moneda_original": payment.valor,
            "moneda": "COP",
            "tasa_dolar": order.tasa_dolar or Decimal("0"),
            "valor_pesos": payment.valor,
            "orden": order,
            "vendedor": order.vendedor,
            "metodo_pago": payment.metodo_pago,
            "registrado_por": "Sistema",
            "observaciones": f"Generado automáticamente desde el abono #{payment.pk}.",
        },
    )


def _upsert_expense_movement(reference, registration_date, defaults):
    """Crea el egreso hoy o actualiza uno existente sin cambiarle la fecha."""
    return MovimientosDinero.objects.update_or_create(
        referencia=reference,
        defaults=defaults,
        create_defaults={**defaults, "fecha": registration_date},
    )


def _sync_order_expense_movements(order):
    """Sincroniza compras y fletes sin duplicarlos al editar la orden."""
    active_references = set()
    registration_date = timezone.now()
    for detail in DetalleOrden.objects.filter(orden=order).select_related("producto"):
        product_cost = (detail.costo_unitario_pesos or 0) * (detail.cantidad or 0)
        freight_cost = (detail.flete_unitario_pesos or 0) * (detail.cantidad or 0)
        common = {
            "tipo_movimiento": "SALIDA",
            "moneda": "COP",
            "tasa_dolar": order.tasa_dolar or Decimal("0"),
            "orden": order,
            "vendedor": order.vendedor,
            "registrado_por": "Sistema",
        }
        purchase_ref = f"AUTO-COMPRA-{detail.pk}"
        if product_cost > 0:
            active_references.add(purchase_ref)
            _upsert_expense_movement(
                purchase_ref, registration_date,
                {
                    **common,
                    "categoria": "COMPRA DE PRODUCTO",
                    "descripcion": (
                        f"Compra de {detail.cantidad} × {detail.descripcion_producto} · "
                        f"Cliente {order.cliente.nombre} · Orden {order.numero_orden}"
                    ),
                    "valor_moneda_original": product_cost,
                    "valor_pesos": product_cost,
                    "observaciones": "Generado automáticamente desde el costo del producto en la orden.",
                },
            )
        else:
            MovimientosDinero.objects.filter(referencia=purchase_ref).delete()
        freight_ref = f"AUTO-FLETE-{detail.pk}"
        if freight_cost > 0:
            active_references.add(freight_ref)
            _upsert_expense_movement(
                freight_ref, registration_date,
                {
                    **common,
                    "categoria": "PAGO DE FLETE",
                    "descripcion": (
                        f"Flete de {detail.descripcion_producto} · Cliente {order.cliente.nombre} · "
                        f"Orden {order.numero_orden}"
                    ),
                    "valor_moneda_original": freight_cost,
                    "valor_pesos": freight_cost,
                    "observaciones": "Generado automáticamente desde el flete del producto en la orden.",
                },
            )
        else:
            MovimientosDinero.objects.filter(referencia=freight_ref).delete()
    MovimientosDinero.objects.filter(
        orden=order, referencia__startswith="AUTO-COMPRA-"
    ).exclude(referencia__in=active_references).delete()
    MovimientosDinero.objects.filter(
        orden=order, referencia__startswith="AUTO-FLETE-"
    ).exclude(referencia__in=active_references).delete()


def _refresh_order_balance(order):
    order.total_abonado = Abonos.objects.filter(orden=order).aggregate(total=Sum("valor"))["total"] or Decimal("0")
    order.saldo_pendiente = max(Decimal("0"), order.total_venta - order.total_abonado)
    order.save(update_fields=["total_abonado", "saldo_pendiente", "actualizado_en"])
    _sync_order_commission(order)
    for payment in Abonos.objects.filter(orden=order):
        _sync_payment_movement(payment, order)


@login_required
def dashboard(request):
    return _dashboard_profesional(request)


def _period_query(field, periods):
    query = Q()
    for year, month in periods:
        query |= Q(**{f"{field}__year": year, f"{field}__month": month})
    return query


def _previous_month(year, month):
    previous = date(year, month, 1) - timedelta(days=1)
    return previous.year, previous.month


@login_required
def reports_dashboard(request):
    """Radiografía visual del negocio, general o para uno o varios meses."""
    zero = Decimal("0")
    month_names = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
    full_month_names = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    raw_periods = request.GET.get("meses", "")
    periods = []
    for value in raw_periods.split(","):
        valid = _valid_month_period(value.strip())
        if valid:
            pair = tuple(int(part) for part in valid.split("-"))
            if pair not in periods:
                periods.append(pair)
    periods.sort()

    orders = Ordenes.objects.select_related("cliente", "vendedor").exclude(estado__iexact="Cancelada")
    if periods:
        orders = orders.filter(_period_query("fecha", periods))
    order_ids = orders.values_list("pk", flat=True)
    details = DetalleOrden.objects.filter(orden_id__in=order_ids).select_related("producto")

    totals = orders.aggregate(
        sales=Sum("total_venta"), gross=Sum("ganancia_bruta"), profit=Sum("ganancia_neta"),
        costs=Sum("costo_total_pesos"), pending=Sum("saldo_pendiente"), paid=Sum("total_abonado"),
        commissions=Sum("comision_vendedor"), discounts=Sum("descuento"),
    )
    sales, profit = totals["sales"] or zero, totals["profit"] or zero
    order_count = orders.count()
    margin = profit / sales * 100 if sales else zero
    ticket = sales / order_count if order_count else zero
    units = details.aggregate(total=Sum("cantidad"))["total"] or 0

    previous_periods = []
    if periods:
        cursor = _previous_month(*periods[0])
        for _index in range(len(periods)):
            previous_periods.append(cursor)
            cursor = _previous_month(*cursor)
    previous_orders = Ordenes.objects.exclude(estado__iexact="Cancelada")
    if previous_periods:
        previous_orders = previous_orders.filter(_period_query("fecha", previous_periods))
        previous_totals = previous_orders.aggregate(sales=Sum("total_venta"), profit=Sum("ganancia_neta"))
        previous_sales = previous_totals["sales"] or zero
        previous_profit = previous_totals["profit"] or zero
        previous_count = previous_orders.count()
    else:
        previous_sales = previous_profit = zero
        previous_count = 0

    def variation(current, previous, inverse=False):
        if not previous:
            return {"value": None, "direction": "neutral", "icon": "dash"}
        value = round(float((current - previous) / abs(previous) * 100), 1)
        improved = value < 0 if inverse else value > 0
        return {"value": abs(value), "direction": "good" if improved else ("bad" if value else "neutral"), "icon": "arrow-up" if value > 0 else ("arrow-down" if value < 0 else "dash")}

    date_span = orders.aggregate(first=Min("fecha"), last=Max("fecha"))
    first_date, last_date = date_span["first"], date_span["last"]
    span_days = (last_date - first_date).days if first_date and last_date else 0
    timeline_is_daily = len(periods) == 1 or (not periods and span_days <= 45)
    timeline_rows = list(orders.annotate(bucket=TruncDay("fecha") if timeline_is_daily else TruncMonth("fecha")).values("bucket").annotate(
        sales=Sum("total_venta"), profit=Sum("ganancia_neta")
    ).order_by("bucket"))
    if not periods:
        timeline_rows = timeline_rows[-12:]
    timeline_max = max((float(row["sales"] or 0) for row in timeline_rows), default=0) or 1
    timeline = []
    for row in timeline_rows:
        bucket = timezone.localtime(row["bucket"]) if timezone.is_aware(row["bucket"]) else row["bucket"]
        timeline.append({
            "label": bucket.strftime("%d") if timeline_is_daily else f"{month_names[bucket.month - 1]} {str(bucket.year)[2:]}",
            "sales": row["sales"] or zero, "profit": row["profit"] or zero,
            "sales_height": max(2, round(float(row["sales"] or 0) / timeline_max * 100, 1)),
            "profit_height": max(2, round(float(max(row["profit"] or 0, zero)) / timeline_max * 100, 1)),
        })

    def ranked(rows, value_key, limit=7):
        rows = list(rows[:limit])
        maximum = max((float(row[value_key] or 0) for row in rows), default=0) or 1
        return [{**row, "width": round(float(row[value_key] or 0) / maximum * 100, 1)} for row in rows]

    category_expression = Coalesce(NullIf("categoria_producto", Value("")), NullIf("producto__categoria", Value("")), Value("OTROS"))
    top_products = ranked(details.annotate(categoria_reporte=category_expression).values("categoria_reporte").annotate(
        units=Sum("cantidad"), sales=Sum("total_venta"), profit=Sum("ganancia_producto")
    ).order_by("-sales"), "sales")
    profitable_products = ranked(details.annotate(categoria_reporte=category_expression).values("categoria_reporte").annotate(
        units=Sum("cantidad"), sales=Sum("total_venta"), profit=Sum("ganancia_producto")
    ).order_by("-profit"), "profit")
    brands = ranked(details.annotate(marca_reporte=Coalesce(NullIf("marca_producto", Value("")), NullIf("producto__marca", Value("")), Value("Sin marca"))).values("marca_reporte").annotate(
        units=Sum("cantidad"), sales=Sum("total_venta"), profit=Sum("ganancia_producto")
    ).order_by("-sales"), "sales")
    vehicles = ranked(details.annotate(
        marca_reporte=Coalesce(NullIf("marca_producto", Value("")), NullIf("producto__marca", Value("")), Value("Sin marca")),
        modelo_reporte=Coalesce(NullIf("modelo_producto", Value("")), NullIf("producto__modelo", Value("")), Value("Sin modelo")),
    ).values("marca_reporte", "modelo_reporte").annotate(
        units=Sum("cantidad"), sales=Sum("total_venta"), profit=Sum("ganancia_producto")
    ).order_by("-sales"), "sales")
    sellers = ranked(orders.exclude(vendedor__isnull=True).values("vendedor__nombre").annotate(
        orders=Count("id"), sales=Sum("total_venta"), profit=Sum("ganancia_neta"), commission=Sum("comision_vendedor")
    ).order_by("-sales"), "sales")
    cities = ranked(orders.values("cliente__ciudad").annotate(
        clients=Count("cliente_id", distinct=True), sales=Sum("total_venta")
    ).order_by("-sales"), "sales", 6)

    colors = ("#e6313a", "#202221", "#f0a51a", "#438a68", "#4263c7", "#85888a")
    status_rows = list(orders.values("estado").annotate(value=Count("id")).order_by("-value"))
    status_total = sum(row["value"] for row in status_rows) or 1
    status_chart, gradient, offset = [], [], 0
    for index, row in enumerate(status_rows):
        percent = round(row["value"] / status_total * 100, 1)
        color = colors[index % len(colors)]
        status_chart.append({**row, "label": row["estado"] or "Sin estado", "percent": percent, "color": color})
        gradient.append(f"{color} {offset}% {offset + percent}%")
        offset += percent

    movements = MovimientosDinero.objects.all()
    payments = Abonos.objects.all()
    if periods:
        movements = movements.filter(_period_query("fecha", periods))
        payments = payments.filter(_period_query("fecha", periods))
    income = movements.filter(tipo_movimiento__in=["INGRESO", "ENTRADA"]).aggregate(total=Sum("valor_pesos"))["total"] or zero
    expenses = movements.filter(tipo_movimiento__in=["EGRESO", "SALIDA"]).aggregate(total=Sum("valor_pesos"))["total"] or zero
    cash_max = max(float(income), float(expenses), 1)

    inventory = Productos.objects.all()
    inventory_units = inventory.aggregate(total=Sum("cantidad_disponible"))["total"] or 0
    inventory_value = sum(((item.cantidad_disponible or 0) * (item.costo_pesos or zero) for item in inventory), zero)
    exhausted_count = inventory.filter(cantidad_disponible=0).count()
    low_stock_count = inventory.filter(cantidad_disponible__gt=0, cantidad_disponible__lte=5).count()
    active_clients = orders.values("cliente_id").distinct().count()
    new_clients = Clientes.objects.filter(_period_query("creado_en", periods)).count() if periods else Clientes.objects.count()

    if not periods:
        period_label = "Panorama general · Todo el historial"
    elif len(periods) == 1:
        year, month = periods[0]
        period_label = f"{full_month_names[month - 1].capitalize()} {year}"
    else:
        period_label = f"{len(periods)} meses seleccionados · {full_month_names[periods[0][1] - 1].capitalize()} {periods[0][0]} a {full_month_names[periods[-1][1] - 1].capitalize()} {periods[-1][0]}"

    context = {
        "periodo": raw_periods, "selected_periods": [f"{year:04d}-{month:02d}" for year, month in periods],
        "period_label": period_label, "is_general": not periods,
        "total_sales": sales, "total_profit": profit, "gross_profit": totals["gross"] or zero,
        "total_costs": totals["costs"] or zero, "discounts": totals["discounts"] or zero,
        "commissions": totals["commissions"] or zero, "pending_balance": totals["pending"] or zero,
        "total_paid": totals["paid"] or zero, "orders_count": order_count, "products_sold": units,
        "ticket_average": ticket, "margin": margin, "active_clients": active_clients, "new_clients": new_clients,
        "sales_variation": variation(sales, previous_sales), "profit_variation": variation(profit, previous_profit),
        "orders_variation": variation(order_count, previous_count), "has_comparison": bool(periods),
        "timeline": timeline, "timeline_granularity": "diaria" if timeline_is_daily else "mensual",
        "top_products": top_products, "profitable_products": profitable_products,
        "brands": brands, "vehicles": vehicles, "sellers_chart": sellers, "cities": cities,
        "status_chart": status_chart, "status_gradient": ", ".join(gradient), "status_total": status_total if status_rows else 0,
        "income": income, "expenses": expenses, "cash_balance": income - expenses,
        "income_width": round(float(income) / cash_max * 100, 1), "expense_width": round(float(expenses) / cash_max * 100, 1),
        "inventory_units": inventory_units, "inventory_value": inventory_value,
        "inventory_products": inventory.count(), "exhausted_count": exhausted_count, "low_stock_count": low_stock_count,
        "payments_total": payments.aggregate(total=Sum("valor"))["total"] or zero,
    }
    return render(request, "gestion/reports.html", context)


def _dashboard_profesional(request):
    """Dashboard ejecutivo construido exclusivamente con datos reales."""
    now = timezone.localtime()
    today = now.date()
    zero = Decimal("0")
    period = request.GET.get("periodo", "mes")
    date_from = request.GET.get("fecha_desde", "")
    date_to = request.GET.get("fecha_hasta", "")
    seller = request.GET.get("vendedor", "")
    status = request.GET.get("estado", "")

    if period == "hoy":
        start, end = today, today
    elif period == "30":
        start, end = today - timedelta(days=29), today
    elif period == "anio":
        start, end = today.replace(month=1, day=1), today
    elif period == "todo":
        start = end = None
    else:
        start, end = today.replace(day=1), today
    try:
        if date_from:
            start = timezone.datetime.strptime(date_from, "%Y-%m-%d").date()
        if date_to:
            end = timezone.datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        messages.warning(request, "Alguna fecha del filtro no es válida; se utilizó el período seleccionado.")

    orders = Ordenes.objects.select_related("cliente", "vendedor").all()
    if start:
        orders = orders.filter(fecha__date__gte=start)
    if end:
        orders = orders.filter(fecha__date__lte=end)
    if seller:
        orders = orders.filter(vendedor_id=seller)
    if status:
        orders = orders.filter(estado=status)

    order_ids = orders.values_list("pk", flat=True)
    details = DetalleOrden.objects.filter(orden_id__in=order_ids)
    aggregates = orders.aggregate(
        sales=Sum("total_venta"), profit=Sum("ganancia_neta"), costs=Sum("costo_total_pesos"),
        pending=Sum("saldo_pendiente"), paid=Sum("total_abonado"), commissions=Sum("comision_vendedor"),
    )
    sales = aggregates["sales"] or zero
    profit = aggregates["profit"] or zero
    costs = aggregates["costs"] or zero
    pending = aggregates["pending"] or zero
    paid = aggregates["paid"] or zero
    margin = (profit / sales * 100) if sales else zero

    days = (end - start).days if start and end else 366
    if days <= 45:
        trunc, time_label, granularity = TruncDay("fecha"), "%d %b", "Diario"
    elif days <= 180:
        trunc, time_label, granularity = TruncWeek("fecha"), "%d %b", "Semanal"
    else:
        trunc, time_label, granularity = TruncMonth("fecha"), "%b %Y", "Mensual"
    timeline_rows = list(orders.annotate(bucket=trunc).values("bucket").annotate(
        sales=Sum("total_venta"), profit=Sum("ganancia_neta"), costs=Sum("costo_total_pesos")
    ).order_by("bucket"))
    timeline_max = max((float(row["sales"] or 0) for row in timeline_rows), default=0) or 1
    timeline = [{
        "label": timezone.localtime(row["bucket"]).strftime(time_label) if timezone.is_aware(row["bucket"]) else row["bucket"].strftime(time_label),
        "sales": row["sales"] or zero, "profit": row["profit"] or zero, "costs": row["costs"] or zero,
        "sales_height": max(2, round(float(row["sales"] or 0) / timeline_max * 100, 1)),
        "profit_height": max(2, round(float(max(row["profit"] or 0, zero)) / timeline_max * 100, 1)),
    } for row in timeline_rows]

    colors = ("#e6313a", "#202221", "#f0a51a", "#438a68", "#4263c7", "#85888a")
    status_rows = list(orders.values("estado").annotate(total=Count("id")).order_by("-total"))
    status_total = sum(row["total"] for row in status_rows) or 1
    status_chart, gradient, offset = [], [], 0
    for index, row in enumerate(status_rows):
        percent = round(row["total"] / status_total * 100, 1)
        color = colors[index % len(colors)]
        gradient.append(f"{color} {offset}% {offset + percent}%")
        status_chart.append({"label": row["estado"] or "Sin estado", "value": row["total"], "percent": percent, "color": color})
        offset += percent

    dashboard_category = Coalesce(NullIf("categoria_producto", Value("")), NullIf("producto__categoria", Value("")), Value("OTROS"))
    top_rows = list(details.annotate(categoria_reporte=dashboard_category).values("categoria_reporte").annotate(
        units=Sum("cantidad_entregada"), sales=Sum("total_venta"), profit=Sum("ganancia_producto")
    ).order_by("-units")[:5])
    top_max = max((row["units"] or 0 for row in top_rows), default=0) or 1
    top_products = [{**row, "width": round((row["units"] or 0) / top_max * 100, 1)} for row in top_rows if row["units"]]

    seller_rows = list(orders.exclude(vendedor__isnull=True).values("vendedor__nombre").annotate(
        sales=Sum("total_venta"), commission=Sum("comision_vendedor")
    ).order_by("-sales")[:6])
    seller_max = max((float(row["sales"] or 0) for row in seller_rows), default=0) or 1
    sellers_chart = [{**row, "width": round(float(row["sales"] or 0) / seller_max * 100, 1)} for row in seller_rows]

    payments = Abonos.objects.filter(orden_id__in=order_ids)
    if start:
        payments = payments.filter(fecha__date__gte=start)
    if end:
        payments = payments.filter(fecha__date__lte=end)
    method_rows = list(payments.values("metodo_pago").annotate(value=Sum("valor")).order_by("-value"))
    method_total = sum((row["value"] or zero for row in method_rows), zero) or Decimal("1")
    payment_methods = [{
        "label": row["metodo_pago"] or "Sin especificar", "value": row["value"] or zero,
        "percent": round(float((row["value"] or zero) / method_total * 100), 1),
        "color": colors[index % len(colors)],
    } for index, row in enumerate(method_rows)]

    movements = MovimientosDinero.objects.all()
    if start:
        movements = movements.filter(fecha__date__gte=start)
    if end:
        movements = movements.filter(fecha__date__lte=end)
    income = movements.filter(tipo_movimiento__in=["INGRESO", "ENTRADA"]).aggregate(total=Sum("valor_pesos"))["total"] or zero
    expenses = movements.filter(tipo_movimiento__in=["EGRESO", "SALIDA"]).aggregate(total=Sum("valor_pesos"))["total"] or zero
    movement_max = max(float(income), float(expenses), 1)

    inventory = Productos.objects.all()
    inventory_units = inventory.aggregate(total=Sum("cantidad_disponible"))["total"] or 0
    inventory_value = sum(((item.cantidad_disponible or 0) * (item.costo_pesos or zero) for item in inventory), zero)
    exhausted = inventory.filter(cantidad_disponible=0)
    low_stock = inventory.filter(cantidad_disponible__gt=0, cantidad_disponible__lte=5)
    available = inventory.filter(cantidad_disponible__gt=5)
    inventory_chart = [
        {"label": "Disponibles", "value": available.count(), "color": "#438a68"},
        {"label": "Stock bajo", "value": low_stock.count(), "color": "#f0a51a"},
        {"label": "Agotados", "value": exhausted.count(), "color": "#e6313a"},
    ]

    pending_orders = orders.filter(saldo_pendiente__gt=0).order_by("-saldo_pendiente")
    client_city_rows = list(Clientes.objects.exclude(ciudad__isnull=True).exclude(ciudad="").values("ciudad").annotate(value=Count("id")).order_by("-value")[:5])
    city_max = max((row["value"] for row in client_city_rows), default=0) or 1
    client_cities = [{**row, "width": round(row["value"] / city_max * 100, 1)} for row in client_city_rows]
    new_clients = Clientes.objects.all()
    if start:
        new_clients = new_clients.filter(creado_en__date__gte=start)
    if end:
        new_clients = new_clients.filter(creado_en__date__lte=end)
    active_clients = orders.values("cliente_id").distinct().count()
    pending_commissions = Comisiones.objects.filter(orden_id__in=order_ids).exclude(estado_pago__iexact="PAGADA")

    context = {
        "filter_period": period, "filter_from": date_from, "filter_to": date_to,
        "filter_seller": seller, "filter_status": status, "sellers": Vendedores.objects.filter(activo=True).order_by("nombre"),
        "statuses": Ordenes.objects.values_list("estado", flat=True).distinct().order_by("estado"), "granularity": granularity,
        "total_sales": sales, "total_profit": profit, "total_costs": costs, "margin": margin,
        "orders_count": orders.count(), "pending_balance": pending, "total_paid": paid,
        "inventory_units": inventory_units, "inventory_value": inventory_value,
        "total_clients": Clientes.objects.count(), "new_clients": new_clients.count(), "active_clients": active_clients,
        "commissions_total": aggregates["commissions"] or zero, "products_sold": details.aggregate(total=Sum("cantidad_entregada"))["total"] or 0,
        "timeline": timeline, "status_chart": status_chart, "status_total": sum(row["total"] for row in status_rows),
        "status_gradient": ", ".join(gradient), "top_products": top_products, "sellers_chart": sellers_chart,
        "payment_methods": payment_methods, "payment_total": (method_total if method_rows else zero),
        "income": income, "expenses": expenses, "balance": income - expenses,
        "income_width": round(float(income) / movement_max * 100, 1), "expense_width": round(float(expenses) / movement_max * 100, 1),
        "inventory_chart": inventory_chart, "inventory_total_products": inventory.count(),
        "low_stock_count": low_stock.count(), "exhausted_count": exhausted.count(), "low_stock_products": list(low_stock.order_by("cantidad_disponible")[:4]),
        "receivables": pending_orders[:7], "pending_orders_count": pending_orders.count(),
        "client_cities": client_cities, "pending_commissions_count": pending_commissions.count(),
        "pending_commissions_total": pending_commissions.aggregate(total=Sum("valor_comision"))["total"] or zero,
        "shipping_pending_count": orders.filter(estado__in=["Pendiente", "En proceso", "Entrega parcial"]).count(),
    }
    return render(request, "gestion/dashboard.html", context)


@login_required
def _dashboard_anterior(request):
    now = timezone.localtime()
    zero = Decimal("0")
    month_names = ("Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
    months = []
    for offset in range(5, -1, -1):
        month_number, year = now.month - offset, now.year
        while month_number <= 0:
            month_number += 12
            year -= 1
        months.append((year, month_number))
    try:
        monthly_orders = Ordenes.objects.filter(fecha__year=now.year, fecha__month=now.month)
        monthly = monthly_orders.aggregate(ventas=Sum("total_venta"), ganancia=Sum("ganancia_neta"))
        portfolio = Ordenes.objects.aggregate(saldo=Sum("saldo_pendiente"))
        money = MovimientosDinero.objects.filter(fecha__year=now.year, fecha__month=now.month)
        ingresos = money.filter(tipo_movimiento__iexact="INGRESO").aggregate(total=Sum("valor_pesos"))["total"] or zero
        egresos = money.filter(tipo_movimiento__iexact="EGRESO").aggregate(total=Sum("valor_pesos"))["total"] or zero
        low_stock = Productos.objects.filter(cantidad_disponible__lte=5).order_by("cantidad_disponible", "nombre")
        pending_commissions = Comisiones.objects.filter(estado_pago__iexact="PENDIENTE")
        first_year, first_month = months[0]
        sales_rows = Ordenes.objects.filter(
            fecha__year__gte=first_year,
        ).annotate(period=TruncMonth("fecha")).values("period").annotate(
            sales=Sum("total_venta"), profit=Sum("ganancia_neta"), orders=Count("id"),
        ).order_by("period")
        sales_by_month = {
            (row["period"].year, row["period"].month): row for row in sales_rows
        }
        order_status_rows = list(monthly_orders.values("estado").annotate(total=Count("id")).order_by("-total"))
        top_products_rows = list(DetalleOrden.objects.values("descripcion_producto").annotate(
            units=Sum("cantidad"), sales=Sum("total_venta"),
        ).order_by("-units")[:5])
        charts_simulated = False
        if not any((row.get("sales") or row.get("profit") or row.get("orders")) for row in sales_by_month.values()):
            charts_simulated = True
            demo_sales = (3200000, 4800000, 4100000, 6700000, 5900000, 8200000)
            demo_profit = (850000, 1250000, 980000, 1800000, 1540000, 2250000)
            demo_orders = (5, 8, 7, 11, 9, 14)
            sales_by_month = {
                key: {"sales": demo_sales[index], "profit": demo_profit[index], "orders": demo_orders[index]}
                for index, key in enumerate(months)
            }
        if not order_status_rows:
            charts_simulated = True
            order_status_rows = [
                {"estado": "Completada", "total": 8}, {"estado": "Pendiente", "total": 4},
                {"estado": "En proceso", "total": 2},
            ]
        if not top_products_rows:
            charts_simulated = True
            top_products_rows = [
                {"descripcion_producto": "Farola LED", "units": 18, "sales": 0},
                {"descripcion_producto": "Stop trasero", "units": 14, "sales": 0},
                {"descripcion_producto": "Exploradora", "units": 11, "sales": 0},
                {"descripcion_producto": "Espejo lateral", "units": 8, "sales": 0},
                {"descripcion_producto": "Bombillo LED", "units": 6, "sales": 0},
            ]
        monthly_chart = []
        max_money = max([
            float(sales_by_month.get(key, {}).get(field) or 0)
            for key in months for field in ("sales", "profit")
        ], default=0) or 1
        max_orders = max([sales_by_month.get(key, {}).get("orders", 0) for key in months], default=0) or 1
        for year, month in months:
            row = sales_by_month.get((year, month), {})
            sales_value, profit_value = float(row.get("sales") or 0), float(row.get("profit") or 0)
            order_value = row.get("orders", 0)
            monthly_chart.append({
                "label": month_names[month - 1], "sales": sales_value, "profit": profit_value,
                "sales_height": round((sales_value / max_money) * 100, 1),
                "profit_height": round((profit_value / max_money) * 100, 1),
                "orders": order_value, "orders_height": round((order_value / max_orders) * 100, 1),
                "x": 25 + len(monthly_chart) * 55,
                "sales_y": 120 - round((sales_value / max_money) * 100, 1),
                "profit_y": 120 - round((profit_value / max_money) * 100, 1),
            })
        status_colors = ("#e6313a", "#202221", "#f0a51a", "#438a68", "#4263c7", "#85888a")
        status_total = sum(row["total"] for row in order_status_rows) or 1
        status_chart, gradient_parts, cumulative = [], [], 0
        for index, row in enumerate(order_status_rows):
            percent = round((row["total"] / status_total) * 100, 1)
            color = status_colors[index % len(status_colors)]
            gradient_parts.append(f"{color} {cumulative}% {cumulative + percent}%")
            cumulative += percent
            status_chart.append({"label": row["estado"] or "Sin estado", "total": row["total"], "percent": percent, "color": color})
        max_units = max([row["units"] or 0 for row in top_products_rows], default=0) or 1
        product_chart = [{
            "label": row["descripcion_producto"], "units": row["units"] or 0,
            "width": round(((row["units"] or 0) / max_units) * 100, 1),
        } for row in top_products_rows]
        product_rows = [
            {"label": "Agotados", "value": Productos.objects.filter(cantidad_disponible=0).count()},
            {"label": "Existencias bajas", "value": Productos.objects.filter(cantidad_disponible__gt=0, cantidad_disponible__lte=5).count()},
            {"label": "Disponibles", "value": Productos.objects.filter(cantidad_disponible__gt=5).count()},
        ]
        product_rows = product_rows if any(row["value"] for row in product_rows) else []
        product_donut, product_donut_total, product_demo = _dashboard_donut(product_rows, "label", "value", [{"label": "Disponibles", "value": 18}, {"label": "Existencias bajas", "value": 6}, {"label": "Agotados", "value": 3}])
        client_rows = list(Clientes.objects.exclude(ciudad__isnull=True).exclude(ciudad="").values("ciudad").annotate(total=Count("id")).order_by("-total")[:5])
        client_bars, client_demo = _dashboard_bars(client_rows, "ciudad", "total", [{"ciudad": "Bogotá", "total": 18}, {"ciudad": "Medellín", "total": 13}, {"ciudad": "Cali", "total": 9}, {"ciudad": "Barranquilla", "total": 6}])
        seller_rows = list(Ordenes.objects.exclude(vendedor__isnull=True).values("vendedor__nombre").annotate(total=Sum("total_venta")).order_by("-total")[:5])
        seller_bars, seller_demo = _dashboard_bars(seller_rows, "vendedor__nombre", "total", [{"vendedor__nombre": "Laura", "total": 8200000}, {"vendedor__nombre": "Carlos", "total": 6100000}, {"vendedor__nombre": "Andrés", "total": 4300000}])
        commission_rows = list(Comisiones.objects.values("estado_pago").annotate(total=Count("id")).order_by("-total"))
        commission_donut, commission_donut_total, commission_demo = _dashboard_donut(commission_rows, "estado_pago", "total", [{"estado_pago": "Pagadas", "total": 12}, {"estado_pago": "Pendientes", "total": 5}])
        movement_rows = list(money.values("tipo_movimiento").annotate(total=Sum("valor_pesos")).order_by("-total"))
        movement_bars, movement_demo = _dashboard_bars(movement_rows, "tipo_movimiento", "total", [{"tipo_movimiento": "Ingresos", "total": 9200000}, {"tipo_movimiento": "Egresos", "total": 3700000}])
        charts_simulated = charts_simulated or product_demo or client_demo or seller_demo or commission_demo or movement_demo
        context = {
            "current_month": now.strftime("%B").capitalize(), "sales_month": monthly["ventas"] or zero,
            "profit_month": monthly["ganancia"] or zero, "orders_month": monthly_orders.count(),
            "pending_balance": portfolio["saldo"] or zero, "total_products": Productos.objects.count(),
            "total_clients": Clientes.objects.count(), "low_stock_count": low_stock.count(),
            "low_stock_products": low_stock[:5], "pending_commissions_count": pending_commissions.count(),
            "pending_commissions_total": pending_commissions.aggregate(total=Sum("valor_comision"))["total"] or zero,
            "month_income": ingresos, "month_expenses": egresos, "month_cashflow": ingresos - egresos,
            "recent_orders": Ordenes.objects.select_related("cliente", "vendedor").order_by("-fecha")[:6],
            "database_available": True,
            "chart_months": [month_names[month - 1] for _year, month in months],
            "chart_sales": [float(sales_by_month.get(key, {}).get("sales") or 0) for key in months],
            "chart_profit": [float(sales_by_month.get(key, {}).get("profit") or 0) for key in months],
            "chart_orders": [sales_by_month.get(key, {}).get("orders", 0) for key in months],
            "chart_status_labels": [row["estado"] or "Sin estado" for row in order_status_rows],
            "chart_status_values": [row["total"] for row in order_status_rows],
            "chart_product_labels": [row["descripcion_producto"] for row in top_products_rows],
            "chart_product_values": [row["units"] or 0 for row in top_products_rows],
            "monthly_chart": monthly_chart, "status_chart": status_chart,
            "status_gradient": ", ".join(gradient_parts) if gradient_parts else "#e2e4e5 0% 100%",
            "product_chart": product_chart,
            "charts_simulated": charts_simulated, "status_chart_total": sum(row["total"] for row in order_status_rows),
            "product_donut": product_donut, "product_donut_total": product_donut_total,
            "client_bars": client_bars, "seller_bars": seller_bars,
            "commission_donut": commission_donut, "commission_donut_total": commission_donut_total,
            "movement_bars": movement_bars,
        }
    except DatabaseError:
        demo_sales = (3200000, 4800000, 4100000, 6700000, 5900000, 8200000)
        demo_profit = (850000, 1250000, 980000, 1800000, 1540000, 2250000)
        demo_orders = (5, 8, 7, 11, 9, 14)
        max_demo_money, max_demo_orders = max(demo_sales), max(demo_orders)
        demo_monthly_chart = [{
            "label": month_names[month - 1], "sales": demo_sales[index], "profit": demo_profit[index],
            "sales_height": round(demo_sales[index] / max_demo_money * 100, 1),
            "profit_height": round(demo_profit[index] / max_demo_money * 100, 1),
            "orders": demo_orders[index], "orders_height": round(demo_orders[index] / max_demo_orders * 100, 1),
            "x": 25 + index * 55,
            "sales_y": 120 - round(demo_sales[index] / max_demo_money * 100, 1),
            "profit_y": 120 - round(demo_profit[index] / max_demo_money * 100, 1),
        } for index, (_year, month) in enumerate(months)]
        demo_product_donut, demo_product_total, _ = _dashboard_donut([], "label", "value", [{"label": "Disponibles", "value": 18}, {"label": "Existencias bajas", "value": 6}, {"label": "Agotados", "value": 3}])
        demo_clients, _ = _dashboard_bars([], "ciudad", "total", [{"ciudad": "Bogotá", "total": 18}, {"ciudad": "Medellín", "total": 13}, {"ciudad": "Cali", "total": 9}])
        demo_sellers, _ = _dashboard_bars([], "nombre", "total", [{"nombre": "Laura", "total": 8200000}, {"nombre": "Carlos", "total": 6100000}, {"nombre": "Andrés", "total": 4300000}])
        demo_commissions, demo_commission_total, _ = _dashboard_donut([], "estado", "total", [{"estado": "Pagadas", "total": 12}, {"estado": "Pendientes", "total": 5}])
        demo_movements, _ = _dashboard_bars([], "tipo", "total", [{"tipo": "Ingresos", "total": 9200000}, {"tipo": "Egresos", "total": 3700000}])
        context = {
            "current_month": now.strftime("%B").capitalize(), "sales_month": zero, "profit_month": zero,
            "orders_month": 0, "pending_balance": zero, "total_products": 0, "total_clients": 0,
            "low_stock_count": 0, "low_stock_products": [], "pending_commissions_count": 0,
            "pending_commissions_total": zero, "month_income": zero, "month_expenses": zero,
            "month_cashflow": zero, "recent_orders": [], "database_available": False,
            "chart_months": [], "chart_sales": [], "chart_profit": [], "chart_orders": [],
            "chart_status_labels": [], "chart_status_values": [], "chart_product_labels": [],
            "chart_product_values": [],
            "monthly_chart": demo_monthly_chart,
            "status_chart": [{"label": "Completada", "total": 8, "color": "#e6313a"}, {"label": "Pendiente", "total": 4, "color": "#202221"}, {"label": "En proceso", "total": 2, "color": "#f0a51a"}],
            "status_gradient": "#e6313a 0% 57.1%, #202221 57.1% 85.7%, #f0a51a 85.7% 100%",
            "product_chart": [{"label": "Farola LED", "units": 18, "width": 100}, {"label": "Stop trasero", "units": 14, "width": 77.8}, {"label": "Exploradora", "units": 11, "width": 61.1}, {"label": "Espejo lateral", "units": 8, "width": 44.4}],
            "charts_simulated": True, "status_chart_total": 14,
            "product_donut": demo_product_donut, "product_donut_total": demo_product_total,
            "client_bars": demo_clients, "seller_bars": demo_sellers,
            "commission_donut": demo_commissions, "commission_donut_total": demo_commission_total,
            "movement_bars": demo_movements,
        }
        messages.warning(request, "No fue posible consultar la base de datos. Revisa la conexión y las tablas.")
    return render(request, "gestion/dashboard.html", context)


@login_required
def record_list(request, module):
    config = _module_or_404(module)

    # Órdenes y movimientos siempre se consultan dentro de un período contable
    # mensual. Canonicalizarlo también hace que búsquedas y reportes lo conserven.
    if module in ("ordenes", "movimientos") and not _valid_month_period(request.GET.get("periodo")):
        params = request.GET.copy()
        params["periodo"] = timezone.localdate().strftime("%Y-%m")
        return redirect(f"{request.path}?{params.urlencode()}")

    records = config["model"].objects.all().order_by("-pk")
    records, query = _apply_module_filters(records, request, module, config)

    controls = []
    for field_name, label, filter_type in MODULE_FILTERS.get(module, ()):
        model_field = config["model"]._meta.get_field(field_name)
        if filter_type in ("date", "range"):
            start_name, end_name = f"{field_name}_desde", f"{field_name}_hasta"
            start, end = request.GET.get(start_name, ""), request.GET.get(end_name, "")
            if start:
                lookup = f"{field_name}__date__gte" if filter_type == "date" else f"{field_name}__gte"
                records = records.filter(**{lookup: start})
            if end:
                lookup = f"{field_name}__date__lte" if filter_type == "date" else f"{field_name}__lte"
                records = records.filter(**{lookup: end})
            input_type = "date" if filter_type == "date" else "number"
            controls.extend((
                {"name": start_name, "label": f"{label} mínimo" if filter_type == "range" else f"{label} desde", "type": input_type, "value": start},
                {"name": end_name, "label": f"{label} máximo" if filter_type == "range" else f"{label} hasta", "type": input_type, "value": end},
            ))
            continue

        selected = request.GET.get(field_name, "")
        if selected != "":
            if filter_type == "boolean":
                records = records.filter(**{field_name: selected == "1"})
            elif filter_type == "text":
                records = records.filter(**{f"{field_name}__icontains": selected})
            else:
                records = records.filter(**{field_name: selected})
        if filter_type == "text":
            controls.append({"name": field_name, "label": label, "type": "text", "value": selected})
            continue
        if filter_type == "foreign":
            options = [(str(item.pk), str(item)) for item in model_field.remote_field.model.objects.all().order_by("pk")]
        elif filter_type == "boolean":
            options = (("1", "Activo"), ("0", "Inactivo"))
        else:
            values = config["model"].objects.exclude(**{f"{field_name}__isnull": True}).exclude(**{field_name: ""}).values_list(field_name, flat=True).distinct().order_by(field_name)
            options = [(str(value), str(value)) for value in values]
        controls.append({"name": field_name, "label": label, "type": "select", "value": selected, "options": options})

    records = list(records[:200])
    current_period = timezone.localdate().strftime("%Y-%m")
    if module == "ordenes":
        for order in records:
            order_date = timezone.localtime(order.fecha) if timezone.is_aware(order.fecha) else order.fecha
            order.can_manage_order = order_date.strftime("%Y-%m") == current_period
            order.can_cancel_order = (
                order.estado.lower() != "cancelada"
                or DetalleOrden.objects.filter(orden=order, cantidad_entregada__gt=0).exists()
            )

    return render(request, "gestion/list.html", {
        "module": module, "config": config, "records": records, "query": query,
        "filter_controls": controls, "periodo": request.GET.get("periodo", ""),
        "current_period": current_period, "can_import": module in IMPORT_CONFIG,
    })


@login_required
def record_form(request, module, pk=None):
    config = _module_or_404(module)
    instance = get_object_or_404(config["model"], pk=pk) if pk else None
    if module == "ordenes":
        return _order_form(request, config, instance)
    form = FORM_CLASSES[module](request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            saved = form.save()
            if module == "abonos":
                _refresh_order_balance(saved.orden)
            messages.success(request, f'Registro {"actualizado" if instance else "creado"} correctamente.')
            return redirect("record_list", module=module)
        except DatabaseError as error:
            form.add_error(None, f"No se pudo guardar el registro: {error}")
    return render(request, "gestion/form.html", {"module": module, "config": config, "form": form, "editing": instance is not None})


def _order_form(request, config, instance):
    creating = instance is None
    order_date = None
    if instance:
        order_date = timezone.localtime(instance.fecha) if timezone.is_aware(instance.fecha) else instance.fecha
    historical_cost_only = bool(
        order_date and order_date.strftime("%Y-%m") != timezone.localdate().strftime("%Y-%m")
    )
    form_kwargs = {"historical_cost_only": historical_cost_only}
    form = FORM_CLASSES["ordenes"](request.POST or None, instance=instance, **form_kwargs)
    formset = DetalleOrdenFormSet(
        request.POST or None, instance=instance, prefix="productos", form_kwargs=form_kwargs,
    )

    forms_are_valid = request.method == "POST" and form.is_valid() and formset.is_valid()
    cancellation_requires_action = bool(
        forms_are_valid
        and form.cleaned_data.get("estado") == "Cancelada"
        and (creating or instance.estado.lower() != "cancelada")
    )
    if cancellation_requires_action:
        form.add_error("estado", "Usa la opción «Cancelar y devolver al inventario» en el listado de órdenes.")

    if forms_are_valid and not cancellation_requires_action:
        try:
            with transaction.atomic():
                if creating:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [7310301])
                order = form.save(commit=False)
                previous_details = {
                    detail.pk: detail
                    for detail in DetalleOrden.objects.select_for_update().filter(orden=order)
                } if not creating else {}
                selected_product_ids = set()
                for cleaned in formset.cleaned_data:
                    if not cleaned:
                        continue
                    old = previous_details.get(cleaned.get("id").pk) if cleaned.get("id") else None
                    if cleaned.get("DELETE"):
                        if historical_cost_only:
                            raise ValidationError("En órdenes de meses anteriores solo puedes modificar los costos y fletes de los productos.")
                        if old and (old.cantidad_recibida or old.cantidad_entregada):
                            raise ValidationError(f"No puedes eliminar {old.descripcion_producto} porque ya tuvo movimientos de inventario.")
                        continue
                    product = cleaned.get("producto")
                    origin = cleaned.get("origen_producto") or "INVENTARIO"
                    if product:
                        selected_product_ids.add(product.pk)
                    if origin == "INVENTARIO" and not product:
                        raise ValidationError("Selecciona un producto del inventario.")
                    received = cleaned["cantidad"]
                    delivered = old.cantidad_entregada if old else 0
                    product_name = product.nombre if product else cleaned.get("descripcion_producto")
                    if cleaned["cantidad"] < delivered:
                        raise ValidationError(f"No puedes reducir {product_name} por debajo de las {delivered} unidades ya entregadas.")
                    if old and received < old.cantidad_recibida:
                        raise ValidationError(f"La cantidad recibida de {product_name} no puede disminuir.")
                    if old and product and old.producto_id != product.pk and (old.cantidad_recibida or old.cantidad_entregada):
                        raise ValidationError(f"No puedes cambiar {old.descripcion_producto} por otro producto porque ya tuvo movimientos de inventario.")

                locked_products = {
                    product.pk: product
                    for product in Productos.objects.select_for_update().filter(pk__in=selected_product_ids)
                }
                if creating:
                    order.numero_orden = _next_order_number()
                    for field in (
                        "flete_pesos", "subtotal_venta", "costo_productos_pesos",
                        "costo_total_pesos", "total_venta", "ganancia_bruta",
                        "comision_vendedor", "ganancia_neta", "total_abonado",
                        "saldo_pendiente",
                    ):
                        setattr(order, field, Decimal("0"))
                order.flete_dolares = Decimal("0")
                order.flete_pesos = Decimal("0")
                order.save()

                formset.instance = order
                changed_details = formset.save(commit=False)
                for deleted in formset.deleted_objects:
                    deleted.delete()
                for detail in changed_details:
                    old = previous_details.get(detail.pk)
                    cleaned = next((item.cleaned_data for item in formset.forms if item.instance is detail), None)
                    origin = (cleaned or {}).get("origen_producto") or "INVENTARIO"
                    selected_product = detail.producto
                    purchased = bool(detail.costo_unitario_dolares or detail.costo_unitario_pesos)
                    if origin == "INVENTARIO":
                        product = locked_products.get(detail.producto_id)
                        detail.descripcion_producto = selected_product.nombre
                        detail.categoria_producto = selected_product.categoria
                        detail.marca_producto = selected_product.marca
                        detail.modelo_producto = selected_product.modelo
                        detail.anio_inicio_producto = selected_product.anio_inicio
                        detail.anio_fin_producto = selected_product.anio_fin
                        detail.cantidad_recibida = old.cantidad_recibida if old else 0
                    else:
                        product = locked_products.get(detail.producto_id) if detail.producto_id else None
                        detail.descripcion_producto = (cleaned or {}).get("descripcion_producto") or (old.descripcion_producto if old else "Producto externo")
                        if purchased and not product:
                            product = Productos.objects.create(
                                nombre=detail.descripcion_producto, marca=detail.marca_producto,
                                categoria=detail.categoria_producto,
                                modelo=detail.modelo_producto, anio_inicio=detail.anio_inicio_producto,
                                anio_fin=detail.anio_fin_producto, cantidad_disponible=0,
                                costo_dolares=detail.costo_unitario_dolares,
                                costo_pesos=detail.costo_unitario_pesos,
                                precio_venta_sugerido=detail.precio_venta_unitario,
                                estado="Reservado",
                            )
                            detail.producto = product
                        detail.cantidad_recibida = detail.cantidad if purchased else 0
                    newly_received = detail.cantidad_recibida - (old.cantidad_recibida if old else 0)
                    detail.total_costo_pesos = (
                        detail.costo_unitario_pesos + detail.flete_unitario_pesos
                    ) * detail.cantidad
                    detail.total_venta = detail.precio_venta_unitario * detail.cantidad
                    detail.ganancia_producto = detail.total_venta - detail.total_costo_pesos
                    detail.orden = order
                    detail.save()
                    if product and origin == "EXTERNO":
                        product.costo_pesos = detail.costo_unitario_pesos
                        product.costo_dolares = detail.costo_unitario_dolares
                        product.precio_venta_sugerido = detail.precio_venta_unitario
                        if newly_received:
                            product.cantidad_disponible += newly_received
                        product.estado = "Reservado" if product.cantidad_disponible > 0 else "Agotado"
                        product.save(update_fields=[
                            "costo_pesos", "costo_dolares", "precio_venta_sugerido",
                            "cantidad_disponible", "estado", "actualizado_en",
                        ])
                formset.save_m2m()

                all_details = DetalleOrden.objects.filter(orden=order)
                order.subtotal_venta = sum((item.total_venta for item in all_details), Decimal("0"))
                order.costo_productos_pesos = sum((item.total_costo_pesos for item in all_details), Decimal("0"))
                order.costo_total_pesos = order.costo_productos_pesos + order.flete_pesos + (order.otros_costos_pesos or 0)
                order.total_venta = max(Decimal("0"), order.subtotal_venta - (order.descuento or 0))
                order.ganancia_bruta = order.total_venta - order.costo_total_pesos
                commission_rate = order.vendedor.porcentaje_comision if order.vendedor else Decimal("0")
                commission_base = max(Decimal("0"), order.total_venta)
                order.comision_vendedor = commission_base * commission_rate / Decimal("100")
                order.ganancia_neta = order.ganancia_bruta - order.comision_vendedor
                order.total_abonado = Abonos.objects.filter(orden=order).aggregate(total=Sum("valor"))["total"] or Decimal("0")
                order.saldo_pendiente = max(Decimal("0"), order.total_venta - order.total_abonado)
                order.save()
                _sync_order_commission(order)
                _sync_order_expense_movements(order)

            messages.success(
                request,
                "Costos y fletes históricos actualizados correctamente." if historical_cost_only
                else f'Orden {"creada" if creating else "actualizada"} correctamente con todos sus cálculos.',
            )
            if historical_cost_only:
                return redirect(f"{reverse('record_list', args=['ordenes'])}?periodo={order_date:%Y-%m}")
            return redirect("record_list", module="ordenes")
        except ValidationError as error:
            form.add_error(None, error.message)
        except DatabaseError:
            form.add_error(None, "No se pudo guardar la orden. Revisa los datos e inténtalo nuevamente.")

    product_data = {
        str(product.pk): {
            "precio": str(product.precio_venta_sugerido or 0),
            "costo": str(product.costo_pesos or 0),
            "costo_usd": str(product.costo_dolares or 0),
            "stock": product.cantidad_disponible,
        }
        for product in Productos.objects.all()
    }
    return render(request, "gestion/order_form.html", {
        "module": "ordenes", "config": config, "form": form, "formset": formset,
        "editing": not creating, "numero_orden": instance.numero_orden if instance else _next_order_number(),
        "historical_cost_only": historical_cost_only,
        "product_data": product_data,
        "product_categories": PRODUCT_CATEGORIES,
    })


@login_required
def record_delete(request, module, pk):
    config = _module_or_404(module)
    if module == "clientes":
        messages.warning(request, "Los clientes forman parte del historial comercial y no se pueden eliminar.")
        return redirect("record_list", module="clientes")
    record = get_object_or_404(config["model"], pk=pk)
    if module == "ordenes":
        order_date = timezone.localtime(record.fecha) if timezone.is_aware(record.fecha) else record.fecha
        if order_date.strftime("%Y-%m") != timezone.localdate().strftime("%Y-%m"):
            messages.warning(request, "No puedes eliminar órdenes de meses anteriores; el período ya está cerrado.")
            return redirect(f"{reverse('record_list', args=['ordenes'])}?periodo={order_date:%Y-%m}")
    if request.method == "POST":
        try:
            record.delete()
            messages.success(request, "Registro eliminado correctamente.")
            return redirect("record_list", module=module)
        except IntegrityError:
            messages.error(request, "No se puede eliminar porque otros registros dependen de este elemento.")
            return redirect("record_list", module=module)
    return render(request, "gestion/confirm_delete.html", {"module": module, "config": config, "record": record})


@login_required
def trm_actual(request):
    try:
        return JsonResponse({"ok": True, **obtener_trm_oficial()})
    except Exception:
        return JsonResponse(
            {"ok": False, "error": "No fue posible consultar la TRM oficial. Puedes ingresar la tasa manualmente."},
            status=503,
        )


@login_required
def quick_product_create(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Método no permitido."}, status=405)

    nombre = request.POST.get("nombre", "").strip()
    if not nombre:
        return JsonResponse({"ok": False, "error": "El nombre del producto es obligatorio."}, status=400)
    category = request.POST.get("categoria", "").strip()
    if category not in PRODUCT_CATEGORIES:
        return JsonResponse({"ok": False, "error": "Selecciona una categoría válida."}, status=400)

    try:
        product = Productos.objects.create(
            nombre=nombre,
            categoria=category,
            marca=request.POST.get("marca", "").strip() or None,
            modelo=request.POST.get("modelo", "").strip() or None,
            anio_inicio=request.POST.get("anio_inicio") or None,
            anio_fin=request.POST.get("anio_fin") or None,
            descripcion=request.POST.get("descripcion", "").strip() or None,
            cantidad_disponible=0,
            costo_dolares=Decimal("0"),
            costo_pesos=Decimal("0"),
            precio_venta_sugerido=Decimal("0"),
            estado="Por pedir",
        )
    except (DatabaseError, ValueError):
        return JsonResponse({"ok": False, "error": "No se pudo crear el producto. Revisa los años ingresados."}, status=400)

    return JsonResponse({
        "ok": True,
        "producto": {
            "id": product.pk,
            "nombre": str(product),
            "label": f"{product.nombre} · {product.categoria or 'Sin categoría'} · Stock: 0 · $0",
            "precio": "0",
            "costo": "0",
        },
    })


@login_required
def order_receipt(request, pk):
    order = get_object_or_404(Ordenes.objects.select_related("cliente", "vendedor"), pk=pk)
    pdf = build_order_receipt(order)
    return FileResponse(
        pdf,
        as_attachment=True,
        filename=_order_receipt_filename(order.cliente.nombre),
        content_type="application/pdf",
    )


@login_required
def pending_deliveries(request):
    """Reune productos vendidos que todavia no han sido entregados."""
    search = request.GET.get("q", "").strip()
    details = (
        DetalleOrden.objects.select_related("orden", "orden__cliente", "producto")
        .filter(cantidad_entregada__lt=F("cantidad"))
        .exclude(orden__estado__iexact="cancelada")
        .order_by("orden__fecha", "orden_id", "pk")
    )
    if search:
        details = details.filter(
            Q(orden__numero_orden__icontains=search)
            | Q(orden__cliente__nombre__icontains=search)
            | Q(orden__cliente__telefono__icontains=search)
            | Q(descripcion_producto__icontains=search)
        )

    orders = {}
    total_units = ready_units = 0
    for detail in details:
        detail.pending_quantity = detail.cantidad - detail.cantidad_entregada
        stock = detail.producto.cantidad_disponible if detail.producto else 0
        detail.ready_quantity = min(detail.pending_quantity, max(stock, 0))
        detail.is_ready = detail.ready_quantity > 0
        total_units += detail.pending_quantity
        ready_units += detail.ready_quantity
        group = orders.setdefault(detail.orden_id, {"order": detail.orden, "details": [], "ready": False})
        group["details"].append(detail)
        group["ready"] = group["ready"] or detail.is_ready

    order_groups = sorted(
        orders.values(),
        key=lambda group: (not group["ready"], group["order"].fecha),
    )
    return render(request, "gestion/pending_deliveries.html", {
        "order_groups": order_groups,
        "orders_count": len(order_groups),
        "total_units": total_units,
        "ready_units": ready_units,
        "search": search,
    })


@login_required
def order_delivery(request, pk):
    order = get_object_or_404(Ordenes.objects.select_related("cliente"), pk=pk)
    if order.estado.lower() == "cancelada":
        messages.warning(request, "No puedes registrar entregas ni pagos desde una orden cancelada.")
        return redirect("record_list", module="ordenes")
    details = list(DetalleOrden.objects.filter(orden=order).select_related("producto").order_by("pk"))

    if request.method == "POST":
        try:
            payment = Decimal(request.POST.get("abono") or "0")
            if payment < 0:
                raise ValidationError("El abono no puede ser negativo.")
            if payment > order.saldo_pendiente:
                raise ValidationError(f"El abono no puede superar el saldo pendiente de ${order.saldo_pendiente:,.0f}.")

            requested = {}
            for detail in details:
                try:
                    quantity = int(request.POST.get(f"entregar_{detail.pk}") or 0)
                except ValueError:
                    raise ValidationError(f"La cantidad de {detail.descripcion_producto} no es válida.")
                pending = detail.cantidad - detail.cantidad_entregada
                if quantity < 0 or quantity > pending:
                    raise ValidationError(f"Puedes entregar entre 0 y {pending} unidades de {detail.descripcion_producto}.")
                requested[detail.pk] = quantity

            if not any(requested.values()) and not payment:
                raise ValidationError("Indica al menos un producto para entregar o un valor de abono.")

            with transaction.atomic():
                locked_order = Ordenes.objects.select_for_update().get(pk=order.pk)
                if locked_order.estado.lower() == "cancelada":
                    raise ValidationError("No puedes registrar entregas ni pagos desde una orden cancelada.")
                locked_details = list(
                    DetalleOrden.objects.select_for_update()
                    .filter(orden=locked_order).order_by("pk")
                )
                product_ids = {item.producto_id for item in locked_details if requested.get(item.pk) and item.producto_id}
                products = {item.pk: item for item in Productos.objects.select_for_update().filter(pk__in=product_ids)}

                for detail in locked_details:
                    quantity = requested.get(detail.pk, 0)
                    if not quantity:
                        continue
                    pending = detail.cantidad - detail.cantidad_entregada
                    if quantity > pending:
                        raise ValidationError(f"Solo quedan {pending} unidades pendientes de {detail.descripcion_producto}.")
                    if not detail.producto_id:
                        raise ValidationError(f"Registra primero los costos de {detail.descripcion_producto}; el producto todavía no ha sido comprado.")
                    if detail.producto_id:
                        product = products[detail.producto_id]
                        if quantity > product.cantidad_disponible:
                            raise ValidationError(f"Stock insuficiente de {product.nombre}: hay {product.cantidad_disponible} unidades.")
                        product.cantidad_disponible -= quantity
                        product.estado = "Vendido" if product.cantidad_disponible == 0 else "Disponible"
                        product.save(update_fields=["cantidad_disponible", "estado"])
                    detail.cantidad_entregada += quantity
                    detail.save(update_fields=["cantidad_entregada"])

                created_payment = None
                if payment:
                    created_payment = Abonos.objects.create(
                        orden=locked_order,
                        fecha=timezone.now(),
                        valor=payment,
                        metodo_pago=request.POST.get("metodo_pago") or None,
                        referencia=request.POST.get("referencia") or None,
                        observaciones="Registrado desde la entrega de productos.",
                    )

                locked_order.total_abonado = Abonos.objects.filter(orden=locked_order).aggregate(total=Sum("valor"))["total"] or Decimal("0")
                locked_order.saldo_pendiente = max(Decimal("0"), locked_order.total_venta - locked_order.total_abonado)
                remaining = DetalleOrden.objects.filter(orden=locked_order, cantidad_entregada__lt=F("cantidad")).exists()
                if not remaining:
                    locked_order.estado = "Entregada"
                elif any(requested.values()):
                    locked_order.estado = "Entrega parcial"
                elif locked_order.saldo_pendiente == 0:
                    locked_order.estado = "Pagada"
                elif locked_order.total_abonado > 0:
                    locked_order.estado = "Abonada"
                locked_order.save(update_fields=["total_abonado", "saldo_pendiente", "estado", "actualizado_en"])
                _sync_order_commission(locked_order)
                if created_payment:
                    _sync_payment_movement(created_payment, locked_order)

            messages.success(request, "Entrega y pago registrados correctamente.")
            if request.GET.get("next") == reverse("pending_deliveries"):
                return redirect("pending_deliveries")
            return redirect("record_list", module="ordenes")
        except (ValidationError, ValueError) as error:
            messages.error(request, error.message if isinstance(error, ValidationError) else str(error))
        order.refresh_from_db()
        details = list(DetalleOrden.objects.filter(orden=order).select_related("producto").order_by("pk"))

    return render(request, "gestion/order_delivery.html", {
        "order": order,
        "details": details,
        "return_url": reverse("pending_deliveries") if request.GET.get("next") == reverse("pending_deliveries") else reverse("record_list", args=["ordenes"]),
    })


@login_required
def order_cancel(request, pk):
    """Cancela una orden y reintegra únicamente las unidades que ya salieron."""
    order = get_object_or_404(Ordenes.objects.select_related("cliente"), pk=pk)
    details = list(DetalleOrden.objects.filter(orden=order).select_related("producto").order_by("pk"))

    if request.method == "POST":
        try:
            with transaction.atomic():
                locked_order = Ordenes.objects.select_for_update().get(pk=order.pk)
                locked_details = list(
                    DetalleOrden.objects.select_for_update()
                    .filter(orden=locked_order).order_by("pk")
                )
                has_units_to_return = any(detail.cantidad_entregada for detail in locked_details)
                if locked_order.estado.lower() == "cancelada" and not has_units_to_return:
                    messages.warning(request, "La orden ya estaba cancelada; no se modificó el inventario.")
                    return redirect("record_list", module="ordenes")
                product_ids = {detail.producto_id for detail in locked_details if detail.producto_id}
                products = {
                    product.pk: product
                    for product in Productos.objects.select_for_update().filter(pk__in=product_ids)
                }
                returned_units = 0
                for detail in locked_details:
                    if detail.producto_id:
                        product = products[detail.producto_id]
                        if detail.cantidad_entregada:
                            product.cantidad_disponible += detail.cantidad_entregada
                            returned_units += detail.cantidad_entregada
                        # Al cancelar, las unidades reservadas vuelven a estar disponibles.
                        product.estado = "Disponible" if product.cantidad_disponible > 0 else "Agotado"
                        product.save(update_fields=["cantidad_disponible", "estado", "actualizado_en"])
                    if detail.cantidad_entregada:
                        detail.cantidad_entregada = 0
                        detail.save(update_fields=["cantidad_entregada"])

                locked_order.estado = "Cancelada"
                locked_order.save(update_fields=["estado", "actualizado_en"])

            if returned_units:
                messages.success(request, f"Orden cancelada. Se devolvieron {returned_units} unidades al inventario.")
            else:
                messages.success(request, "Orden cancelada. Sus productos pendientes quedaron disponibles en inventario.")
            return redirect("record_list", module="ordenes")
        except DatabaseError:
            messages.error(request, "No se pudo cancelar la orden. Inténtalo nuevamente.")

    return render(request, "gestion/order_cancel.html", {"order": order, "details": details})


@login_required
def module_report(request, module):
    config = _module_or_404(module)
    records = config["model"].objects.all().order_by("-pk")
    records, _ = _apply_module_filters(records, request, module, config)
    pdf = build_module_report(module, config, records, request.GET)
    period = request.GET.get("periodo") or "completo"
    return FileResponse(pdf, as_attachment=True, filename=f"reporte-{module}-{period}.pdf", content_type="application/pdf")


@login_required
def excel_template(request, module):
    if module not in IMPORT_CONFIG:
        return JsonResponse({"error": "Este módulo no admite importación."}, status=404)
    return FileResponse(build_template(module), as_attachment=True, filename=f"plantilla-{module}-lujoshop.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@login_required
def excel_import(request, module):
    if module not in IMPORT_CONFIG:
        return redirect("record_list", module=module)
    errors = []
    if request.method == "POST":
        uploaded = request.FILES.get("archivo")
        if not uploaded:
            errors.append("Selecciona un archivo Excel.")
        elif not uploaded.name.lower().endswith(".xlsx"):
            errors.append("El archivo debe tener extensión .xlsx.")
        elif uploaded.size > 10 * 1024 * 1024:
            errors.append("El archivo supera el máximo permitido de 10 MB.")
        else:
            imported, errors = import_excel(module, uploaded)
            if not errors:
                messages.success(request, f"Importación completada: {imported} registros procesados correctamente.")
                return redirect("record_list", module=module)
    return render(request, "gestion/import_excel.html", {"module": module, "config": MODULES[module], "errors": errors})

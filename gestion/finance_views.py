from decimal import Decimal
from calendar import monthrange

from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.db.models.functions import TruncDay
from django.shortcuts import render
from django.utils import timezone

from .models import Abonos, MovimientosDinero, Ordenes
from .payment_status import delivery_label, with_payments
from .report_periods import ReportMonth


def selected_period(request):
    try:
        year, month = map(int, request.GET.get("periodo", "").split("-"))
        period = ReportMonth(year, month)
        period.start
        period.end
        return period
    except (ValueError, TypeError):
        now = timezone.localdate()
        return ReportMonth(now.year, now.month)


def paid_orders():
    return (with_payments(Ordenes.objects.select_related("cliente"))
            .exclude(estado__iexact="Cancelada").exclude(estado__iexact="Cotización")
            .filter(total_venta__gt=0, received__gte=F("total_venta")))


@login_required
def paid_list(request):
    period = selected_period(request)
    orders = paid_orders().filter(last_payment__gte=period.start, last_payment__lt=period.end)
    query = request.GET.get("q", "").strip()
    if query:
        from django.db.models import Q
        orders = orders.filter(Q(numero_orden__icontains=query) | Q(cliente__nombre__icontains=query))
    rows = list(orders.prefetch_related("detalleorden_set").order_by("-last_payment", "-pk"))
    for order in rows:
        order.delivery_status = delivery_label(order, order.detalleorden_set.all())
    return render(request, "gestion/paid_list.html", {
        "orders": rows, "periodo": f"{period.year:04d}-{period.month:02d}", "query": query,
    })


@login_required
def financial_report(request):
    period = selected_period(request)
    movements = MovimientosDinero.objects.filter(fecha__gte=period.start, fecha__lt=period.end)
    zero = Decimal("0")
    def amount(query):
        return query.aggregate(value=Sum("valor_pesos"))["value"] or zero
    receipts = Abonos.objects.filter(fecha__gte=period.start, fecha__lt=period.end)
    received = receipts.aggregate(value=Sum("valor"))["value"] or zero
    incoming = received + amount(movements.filter(tipo_movimiento="ENTRADA").exclude(referencia__startswith="AUTO-ABONO-"))
    outgoing = amount(movements.filter(tipo_movimiento="SALIDA"))
    closed = paid_orders().filter(last_payment__gte=period.start, last_payment__lt=period.end)
    confirmed = closed.filter(costos_completos=True)
    profit = confirmed.aggregate(value=Sum("ganancia_neta"))["value"] or zero
    # Only unassigned manual expenses are deducted here: assigned product/freight
    # costs are already in each order's net margin.
    overhead = amount(movements.filter(tipo_movimiento="SALIDA", orden__isnull=True, categoria="MOVIMIENTO MANUAL"))
    days = monthrange(period.year, period.month)[1]
    daily_in = [zero for _ in range(days)]
    daily_out = [zero for _ in range(days)]
    for row in receipts.annotate(day=TruncDay("fecha")).values("day").annotate(total=Sum("valor")):
        daily_in[row["day"].day - 1] += row["total"]
    manual_in = movements.filter(tipo_movimiento="ENTRADA").exclude(referencia__startswith="AUTO-ABONO-")
    for query, values in ((manual_in, daily_in), (movements.filter(tipo_movimiento="SALIDA"), daily_out)):
        for row in query.annotate(day=TruncDay("fecha")).values("day").annotate(total=Sum("valor_pesos")):
            values[row["day"].day - 1] += row["total"]
    confirmed_count = confirmed.count()
    provisional = closed.filter(costos_completos=False).count()
    charts = {
        "cash": [incoming, outgoing, incoming - outgoing],
        "profit": [profit, overhead, profit - overhead],
        "daily_in": daily_in, "daily_out": daily_out,
        "confirmed": confirmed_count, "provisional": provisional,
    }
    return render(request, "gestion/financial_report.html", {
        "periodo": f"{period.year:04d}-{period.month:02d}",
        "incoming": incoming, "outgoing": outgoing, "cash_balance": incoming-outgoing,
        "confirmed_profit": profit, "overhead": overhead, "result": profit-overhead,
        "provisional": provisional,
        "confirmed_count": confirmed_count,
        "financial_charts": charts,
        "movements": movements.select_related("orden").order_by("fecha", "pk"),
    })

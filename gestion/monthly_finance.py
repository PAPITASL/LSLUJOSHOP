"""Read-only monthly cash analysis.

Abonos is the sole receipt ledger: the business records an abono only after
receiving the money. Its automatic cash movement is not a second receipt.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Prefetch, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Abonos, DetalleOrden, Ordenes


ZERO = Decimal("0")


def build_monthly_finance(period, *, as_of=None):
    cutoff = min(as_of or timezone.now(), period.end)
    close_date = timezone.localtime(cutoff - timedelta(microseconds=1)).date()
    receipts = Abonos.objects.filter(fecha__gte=period.start, fecha__lt=cutoff)
    money_field = DecimalField(max_digits=18, decimal_places=2)
    paid = (Abonos.objects.filter(orden_id=OuterRef("pk"), fecha__lt=cutoff)
            .order_by().values("orden_id").annotate(total=Sum("valor")).values("total"))
    orders = (Ordenes.objects.filter(fecha__lt=cutoff)
              .exclude(estado__iexact="Cotización")
              .select_related("cliente")
              .annotate(finance_paid=Coalesce(Subquery(paid, output_field=money_field), Value(ZERO), output_field=money_field))
              .prefetch_related(Prefetch("detalleorden_set", queryset=DetalleOrden.objects.only(
                  "orden_id", "cantidad", "cantidad_entregada"), to_attr="finance_details")))
    monthly, previous_open, tracking = [], [], []
    buckets = {key: {"count": 0, "value": ZERO} for key in ("paid", "partial", "pending", "cancelled")}
    for order in orders:
        is_month = order.fecha >= period.start
        cancelled = order.estado.strip().casefold() == "cancelada"
        total = order.total_venta or ZERO
        received = order.finance_paid
        balance = max(ZERO, total - received) if not cancelled else ZERO
        # Delivery quantities have no event dates; these are current observations.
        delivery_pending = (any(d.cantidad_entregada < d.cantidad for d in order.finance_details)
                            if order.finance_details else order.estado.strip().casefold() not in ("entregada", "cancelada"))
        age = max(0, (close_date - timezone.localtime(order.fecha).date()).days)
        overdue = not cancelled and age > 10 and (balance > ZERO or delivery_pending)
        category = "cancelled" if cancelled else "paid" if balance == ZERO else "partial" if received > ZERO else "pending"
        row = {"id": order.pk, "number": order.numero_orden, "client": order.cliente.nombre,
               "total": total, "paid": received, "balance": balance, "state": order.estado,
               "delivery_pending": delivery_pending, "age": age, "overdue": overdue,
               "cancelled": cancelled, "category": category, "is_month": is_month}
        if is_month:
            monthly.append(row)
            buckets[category]["count"] += 1
            buckets[category]["value"] += total
        elif not cancelled and balance > ZERO:
            previous_open.append(row)
        if (is_month and (cancelled or balance > ZERO or delivery_pending)) or overdue:
            tracking.append(row)

    def total(rows, field):
        return sum((row[field] for row in rows), ZERO)

    active = [row for row in monthly if not row["cancelled"]]
    partial = [row for row in active if row["category"] == "partial"]
    unresolved = [row for row in active if row["balance"] > ZERO or row["delivery_pending"]]
    overdue = [row for row in tracking if row["overdue"]]
    receipt_rows = list(receipts.values("fecha", "valor", "orden__fecha", "orden__estado"))
    received = total(receipt_rows, "valor")
    received_current = total([r for r in receipt_rows if period.start <= r["orden__fecha"] < period.end], "valor")
    received_previous = total([r for r in receipt_rows if r["orden__fecha"] < period.start], "valor")
    received_other = received - received_current - received_previous
    daily = {}
    day = period.start.date()
    while day <= close_date and day < period.end.date():
        daily[day] = {"date": day, "current": ZERO, "previous": ZERO, "other": ZERO}
        day += timedelta(days=1)
    for row in receipt_rows:
        day = timezone.localtime(row["fecha"]).date()
        key = "previous" if row["orden__fecha"] < period.start else "current" if row["orden__fecha"] < period.end else "other"
        daily[day][key] += row["valor"]
    tracking.sort(key=lambda row: (not row["overdue"], not row["cancelled"], -row["age"], row["number"]))
    registered = total(monthly, "total")
    net_sales = registered - buckets["cancelled"]["value"]
    return {
        "period_label": period.label, "cutoff": cutoff, "close_date": close_date,
        "registered": registered, "order_count": len(monthly), "net_sales": net_sales,
        "cancelled_count": buckets["cancelled"]["count"], "cancelled_value": buckets["cancelled"]["value"],
        "received": received, "received_current": received_current, "received_previous": received_previous,
        "received_other": received_other,
        "receipts_on_cancelled": total([r for r in receipt_rows if r["orden__estado"].strip().casefold() == "cancelada"], "valor"),
        "pending": total(active, "balance"), "previous_pending": total(previous_open, "balance"),
        "partial_count": len(partial), "partial_paid": total(partial, "paid"), "partial_pending": total(partial, "balance"),
        "unresolved_count": len(unresolved), "unresolved_value": total(unresolved, "total"),
        "unresolved_balance": total(unresolved, "balance"),
        "overdue_count": len(overdue), "overdue_balance": total(overdue, "balance"),
        "paid_percent": (net_sales - total(active, "balance")) / net_sales * 100 if net_sales else ZERO,
        "buckets": buckets, "daily": list(daily.values()), "tracking": tracking,
    }

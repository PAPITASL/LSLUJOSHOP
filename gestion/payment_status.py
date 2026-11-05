"""Payment and delivery are independent; stored order labels are not receipts."""
from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest

from .models import Abonos


def with_payments(orders):
    money = DecimalField(max_digits=18, decimal_places=2)
    receipts = Abonos.objects.filter(orden_id=OuterRef("pk")).order_by()
    total = receipts.values("orden_id").annotate(value=Sum("valor")).values("value")
    return orders.annotate(
        received=Coalesce(Subquery(total, output_field=money), Value(Decimal("0")), output_field=money),
        last_payment=Subquery(receipts.order_by("-fecha", "-pk").values("fecha")[:1]),
    ).annotate(balance=Greatest(Value(Decimal("0")), F("total_venta")-F("received"), output_field=money))


def is_paid(order, received):
    return (order.estado.strip().casefold() not in ("cancelada", "cotización")
            and order.total_venta > 0 and received >= order.total_venta)


def payment_label(order, received):
    if order.estado.strip().casefold() in ("cancelada", "cotización"):
        return "No aplica"
    if order.total_venta <= 0:
        return "Sin valor de venta"
    return "Pagada" if is_paid(order, received) else "Abonada" if received > 0 else "Por pagar"


def delivery_label(order, details):
    if order.estado.strip().casefold() in ("cancelada", "cotización"):
        return order.estado
    details = list(details)
    total = sum(d.cantidad for d in details)
    delivered = sum(d.cantidad_entregada for d in details)
    return ("Sin productos" if total <= 0 else "Entregada" if delivered >= total
            else "Entrega parcial" if delivered else "Pendiente de entrega")

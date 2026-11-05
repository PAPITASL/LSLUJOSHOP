def stock_products():
    """Physical stock and outstanding commitments for each exact product ID."""
    from django.db.models import F, IntegerField, OuterRef, Subquery, Sum, Value
    from django.db.models.functions import Coalesce, Greatest
    from .models import DetalleOrden, Productos

    committed = (DetalleOrden.objects.filter(producto_id=OuterRef("pk"))
                 .exclude(orden__estado__iexact="Cancelada")
                 .exclude(orden__estado__iexact="Cotización")
                 .filter(cantidad__gt=F("cantidad_entregada"))
                 .order_by().values("producto_id")
                 .annotate(total=Sum(F("cantidad") - F("cantidad_entregada")))
                 .values("total"))
    return Productos.objects.annotate(
        stock_committed=Coalesce(Subquery(committed, output_field=IntegerField()), Value(0)),
    ).annotate(stock_free=Greatest(Value(0), F("cantidad_disponible") - F("stock_committed")))


def inventory_products():
    """Keep delivered, exhausted products only in sales history."""
    return stock_products().exclude(cantidad_disponible__lte=0, estado__iexact="Vendido")


def validate_inventory_selection(order, cleaned_lines, previous_details, locked_products):
    """Validate combined inventory quantities while the selected products are locked."""
    from django.core.exceptions import ValidationError
    from .models import DetalleOrden

    if order.estado.casefold() in {"cancelada", "cotización"}:
        return
    requested = {}
    previous = {}
    for detail in previous_details.values():
        if detail.producto_id and detail.origen_producto == "INVENTARIO":
            previous[detail.producto_id] = previous.get(detail.producto_id, 0) + max(
                0, detail.cantidad - detail.cantidad_entregada)
    for line in cleaned_lines:
        if not line or line.get("DELETE") or line.get("origen_producto") != "INVENTARIO":
            continue
        product = line.get("producto")
        if not product:
            continue
        old = previous_details.get(line["id"].pk) if line.get("id") else None
        pending = max(0, line["cantidad"] - (old.cantidad_entregada if old else 0))
        requested[product.pk] = requested.get(product.pk, 0) + pending
    for product_id, quantity in requested.items():
        product = locked_products[product_id]
        others = DetalleOrden.objects.filter(producto_id=product_id).exclude(
            orden_id=order.pk).exclude(orden__estado__iexact="Cancelada").exclude(
            orden__estado__iexact="Cotización")
        committed = sum(max(0, detail.cantidad - detail.cantidad_entregada) for detail in others)
        free = max(0, product.cantidad_disponible - committed)
        # Historical commitments may exceed physical stock; permit preserving
        # or reducing them, but never increase that shortage.
        if quantity > max(free, previous.get(product_id, 0)):
            raise ValidationError(
                f"Stock libre insuficiente del producto #{product.pk} ({product.nombre}): "
                f"solicitas {quantity} unidades pendientes y hay {free} libres. "
                "Las unidades comprometidas en otras órdenes no están disponibles."
            )


def summarize_inventory(product, details):
    """Physical stock leaves on delivery; pending sales commit available units."""
    product.order_links = []
    product.committed_units = 0
    product.delivered_units = 0
    for detail in details:
        state = detail.orden.estado.casefold()
        pending = max(0, detail.cantidad - detail.cantidad_entregada)
        committed = pending if state not in {"cancelada", "cotización"} else 0
        product.committed_units += committed
        product.delivered_units += detail.cantidad_entregada if state != "cancelada" else 0
        product.order_links.append({"detail": detail, "pending": pending, "committed": committed})
    product.free_units = max(0, product.cantidad_disponible - product.committed_units)
    product.missing_units = max(0, product.committed_units - product.cantidad_disponible)
    return product

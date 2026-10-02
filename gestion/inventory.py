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

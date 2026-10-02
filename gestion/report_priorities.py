"""Objective next-period actions; missing evidence never activates a rule.

Policy thresholds: receivables >30%, OTROS >10%, pending orders >=5,
category growth >=20% with >=10% participation in current detail sales.
These are operational review thresholds, not financial advice.
"""
from decimal import Decimal

RECEIVABLES_THRESHOLD = Decimal("30")
OTHERS_THRESHOLD = Decimal("10")
PENDING_ORDERS_THRESHOLD = 5
CATEGORY_GROWTH_THRESHOLD = Decimal("20")
CATEGORY_SHARE_THRESHOLD = Decimal("10")


def build_next_month_priorities(data):
    candidates = []

    def add(code, score, area, reason, action):
        candidates.append({"code": code, "score": score,
                           "priority": "high" if score >= 80 else "medium" if score >= 40 else "low",
                           "area": area, "reason": reason, "action": action})

    def percent(numerator, denominator):
        return Decimal(str(numerator)) / Decimal(str(denominator)) * 100

    def fmt(value):
        return f"{value:.1f}".replace(".", ",")

    sales, pending = data.get("total_sales"), data.get("pending_balance")
    if sales and sales > 0 and pending is not None and pending > 0:
        share = percent(pending, sales)
        if share > RECEIVABLES_THRESHOLD:
            add("receivables", 100, "cartera",
                f"El {fmt(share)}% del valor de las órdenes del período figura pendiente de recaudo en este informe.",
                "Priorizar el seguimiento de estos saldos, verificando los pagos posteriores antes de contactar a los clientes.")
    exhausted = data.get("exhausted_with_demand")
    if exhausted and exhausted > 0:
        add("restocking_review", 95, "inventario",
            f"{exhausted} referencias con pedidos en el período están actualmente agotadas.",
            f"Revisar las necesidades de reposición de esas {exhausted} referencias y las compras ya en tránsito.")
    orders = data.get("pending_delivery_orders")
    if orders is not None and orders >= PENDING_ORDERS_THRESHOLD:
        add("deliveries", 90, "operaciones",
            f"{orders} pedidos creados en el período continúan con unidades pendientes de entrega.",
            f"Dar seguimiento a esos {orders} pedidos y confirmar pendientes y fechas de entrega con cada cliente.")
    cash = data.get("cash_balance")
    if cash is not None and cash < 0:
        amount = "$ " + f"{abs(cash):,.0f}".replace(",", ".")
        add("cash_review", 85, "operaciones",
            f"Las salidas registradas superaron las entradas en {amount} durante el período.",
            "Revisar el detalle de entradas y salidas y los cobros pendientes antes de programar nuevos desembolsos.")

    categories = data.get("priority_categories") or []
    total = data.get("detail_sales_total")
    if total and total > 0:
        others = sum((row.get("sales") or 0 for row in categories
                      if str(row.get("categoria_reporte") or "").strip().upper() == "OTROS"), Decimal("0"))
        share = percent(others, total)
        if share > OTHERS_THRESHOLD:
            add("classification", 75, "ventas",
                f"OTROS concentra el {fmt(share)}% de las ventas de productos, antes de descuentos generales.",
                "Reclasificar los productos registrados como OTROS para identificar mejor qué categorías generan ventas.")

    change = data.get("sales_variation") or {}
    comparison = "mes anterior" if data.get("is_monthly") else "período anterior"
    if data.get("has_comparison") and change.get("value") is not None and change["value"] > 0 and change.get("icon") == "arrow-down":
        add("sales_decline", 70, "ventas",
            f"Las ventas disminuyeron {fmt(change['value'])}% frente al {comparison}.",
            "Comparar las ventas por categoría y cliente entre ambos períodos para identificar dónde se concentra la variación.")
    previous = data.get("previous_recurring_clients")
    current = data.get("recurring_clients")
    if data.get("has_comparison") and previous and previous > 0 and current is not None and current < previous:
        decline = percent(previous-current, previous)
        add("repeat_customers", 65, "clientes",
            f"Los compradores con órdenes anteriores al inicio de cada mes pasaron de {previous} a {current}, una disminución del {fmt(decline)}%.",
            "Revisar el seguimiento de recompra y los compradores que no volvieron a realizar pedidos en el mes.")
    if data.get("has_comparison") and total and total > 0:
        previous_categories = {row["categoria_reporte"]: row.get("sales") or 0
                               for row in data.get("previous_priority_categories") or []}
        growing = []
        for row in categories:
            label, value = row["categoria_reporte"], row.get("sales") or 0
            baseline = previous_categories.get(label, 0)
            if str(label).strip().upper() == "OTROS" or baseline <= 0 or value <= baseline:
                continue
            growth = percent(value-baseline, baseline)
            if growth >= CATEGORY_GROWTH_THRESHOLD and percent(value, total) >= CATEGORY_SHARE_THRESHOLD:
                growing.append((value-baseline, label, growth))
        if growing:
            _, label, growth = sorted(growing, key=lambda r: (-r[0], r[1]))[0]
            add("category_growth", 55, "ventas",
                f"{label} aumentó {fmt(growth)}% en ventas de productos frente al {comparison}, antes de descuentos generales.",
                f"Revisar la disponibilidad y las oportunidades de promoción de {label}, comprobando existencias y margen antes de decidir.")
    # Acquisition channels and ROAS are not stored: no marketing claims.
    return sorted(candidates, key=lambda item: (-item["score"], item["code"]))[:5]

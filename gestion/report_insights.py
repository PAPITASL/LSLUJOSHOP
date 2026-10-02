"""Deterministic, evidence-based report sentences. No external services.

Selection: four findings, or five when five high-priority findings exist.
Thresholds: high receivables >=30%; significant variation >=10%;
dominant category/brand >=30% of detail sales before order discounts.
"""
from decimal import Decimal


def build_monthly_insights(data):
    findings = []

    def add(code, score, text):
        findings.append({"code": code, "score": score,
                         "priority": "HIGH" if score >= 80 else "MEDIUM" if score >= 40 else "LOW",
                         "text": text})

    def pct(value):
        return f"{value:.1f}".replace(".", ",")

    def money(value):
        return "$ " + f"{value:,.0f}".replace(",", ".")

    sales = data.get("total_sales")
    pending = data.get("pending_balance")
    cash = data.get("cash_balance")
    if cash is not None and cash < 0:
        add("negative_cash", 100, f"Las salidas superaron las entradas en {money(abs(cash))} durante el período.")
    if sales is not None and sales > 0 and pending is not None and pending > 0:
        share = Decimal(str(pending)) / Decimal(str(sales)) * 100
        add("receivables", 95 if share >= 30 else 45,
            f"El {pct(share)}% del valor de las órdenes seleccionadas continúa pendiente de recaudo.")
    exhausted = data.get("exhausted_with_demand")
    if exhausted:
        add("exhausted_demand", 90, f"{exhausted} referencias con pedidos en el período están actualmente agotadas.")
    undelivered = data.get("pending_delivery_orders")
    if undelivered:
        add("pending_deliveries", 85, f"{undelivered} órdenes creadas en el período tienen actualmente unidades pendientes de entrega.")

    change = data.get("sales_variation") or {}
    comparison = "mes anterior" if data.get("is_monthly") else "período anterior"
    if data.get("has_comparison") and change.get("value") is not None:
        value = change["value"]
        verb = "aumentaron" if change["icon"] == "arrow-up" else "disminuyeron"
        text = f"Las ventas {verb} {pct(value)}% frente al {comparison}." if value else f"Las ventas no cambiaron frente al {comparison}."
        add("sales_change", 75 if value >= 10 else 35, text)
    elif sales is not None:
        add("sales_change", 35, f"Se registraron {money(sales)} en ventas; no hay base para una comparación porcentual.")

    previous_clients = data.get("previous_active_clients")
    clients = data.get("active_clients")
    if data.get("has_comparison") and previous_clients and clients is not None and clients > previous_clients:
        growth = Decimal(clients - previous_clients) / Decimal(previous_clients) * 100
        add("client_growth", 65 if growth >= 10 else 40,
            f"Se atendieron {clients} clientes compradores, {pct(growth)}% más que el {comparison}.")

    # Use the complete detail-sales denominator, never discounted order totals
    # or the truncated on-screen ranking, so percentages remain comparable.
    total = data.get("detail_sales_total")
    if total is not None and total > 0:
        for key, field, code in (("top_products", "categoria_reporte", "category_share"), ("brands", "marca_reporte", "brand_share")):
            rows = data.get(key) or []
            if rows:
                leader = max(rows, key=lambda r: r.get("sales") or 0)
                label = leader.get(field)
                share = Decimal(str(leader.get("sales") or 0)) / Decimal(str(total)) * 100
                if label and label not in {"Sin marca", "OTROS"} and 30 <= share <= 100:
                    add(code, 60 if code == "category_share" else 55,
                        f"{label} representó el {pct(share)}% de las ventas de productos del período, antes de descuentos generales.")

    if clients is not None and not any(f["code"] == "client_growth" for f in findings):
        add("clients", 20, f"Se atendieron {clients} clientes compradores en el período.")
    received = data.get("payments_total")
    if received is not None:
        add("receipts", 25, f"Se recibieron {money(received)} en abonos durante el período.")
    orders = data.get("orders_count")
    if orders is not None:
        add("orders", 15, f"Se registraron {orders} órdenes en el período.")
    findings.sort(key=lambda item: (-item["score"], item["code"]))
    limit = 5 if sum(item["priority"] == "HIGH" for item in findings) >= 5 else 4
    return findings[:limit]

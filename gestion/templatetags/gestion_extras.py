from django import template
from datetime import date, datetime
from decimal import Decimal

register = template.Library()


@register.filter
def subtract(value, arg):
    try:
        return value - arg
    except (TypeError, ValueError):
        return 0

@register.filter
def money_cop(value):
    """Presenta valores monetarios con separador colombiano."""
    try:
        return "$ " + format(Decimal(value), ",.0f").replace(",", ".")
    except (TypeError, ValueError, ArithmeticError):
        return "$ 0"

@register.filter
def get_attr(value, name):
    result = getattr(value, name, "")
    if isinstance(result, bool):
        return "Sí" if result else "No"
    money_fields = {
        "costo_pesos", "precio_venta_sugerido", "subtotal_venta", "total_venta",
        "saldo_pendiente", "total_abonado", "ganancia_neta", "precio_venta_unitario",
        "ganancia_producto", "valor", "valor_comision", "total_recibo", "valor_pesos",
    }
    if name in money_fields and result is not None:
        return "$ " + format(result, ",.0f").replace(",", ".") + " COP"
    if isinstance(result, datetime):
        return result.strftime("%d/%m/%Y %H:%M")
    if isinstance(result, date):
        return result.strftime("%d/%m/%Y")
    if isinstance(result, Decimal):
        return format(result, ",.2f").replace(",", "X").replace(".", ",").replace("X", ".")
    return result if result is not None else "—"


@register.filter
def form_field(form, name):
    """Obtiene un BoundField sin confundirlo con atributos del modelo."""
    try:
        return form[name]
    except KeyError:
        return ""

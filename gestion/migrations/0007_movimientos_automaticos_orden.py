from decimal import Decimal

from django.db import migrations


def create_existing_movements(apps, schema_editor):
    # Los modelos iniciales fueron inspeccionados con managed=False y su estado
    # histórico no conserva las FK; los modelos reales sí reflejan esas columnas.
    from gestion.models import Abonos, DetalleOrden, MovimientosDinero as Movimientos, Ordenes

    for order in Ordenes.objects.all():
        for detail in DetalleOrden.objects.filter(orden_id=order.pk):
            product_cost = (detail.costo_unitario_pesos or 0) * (detail.cantidad or 0)
            freight_cost = (detail.flete_unitario_pesos or 0) * (detail.cantidad or 0)
            common = {
                "fecha": order.fecha, "tipo_movimiento": "EGRESO", "moneda": "COP",
                "tasa_dolar": order.tasa_dolar or Decimal("0"), "orden_id": order.pk,
                "vendedor_id": order.vendedor_id, "registrado_por": "Sistema",
            }
            Movimientos.objects.update_or_create(
                referencia=f"AUTO-COMPRA-{detail.pk}",
                defaults={**common, "categoria": "COMPRA DE PRODUCTO",
                    "descripcion": f"Compra de {detail.cantidad} × {detail.descripcion_producto} · Orden {order.numero_orden}",
                    "valor_moneda_original": product_cost, "valor_pesos": product_cost,
                    "observaciones": "Generado automáticamente desde el costo del producto en la orden."},
            )
            if freight_cost > 0:
                Movimientos.objects.update_or_create(
                    referencia=f"AUTO-FLETE-{detail.pk}",
                    defaults={**common, "categoria": "PAGO DE FLETE",
                        "descripcion": f"Flete de {detail.descripcion_producto} · Orden {order.numero_orden}",
                        "valor_moneda_original": freight_cost, "valor_pesos": freight_cost,
                        "observaciones": "Generado automáticamente desde el flete del producto en la orden."},
                )
        payments = list(Abonos.objects.filter(orden_id=order.pk).order_by("fecha", "pk"))
        for index, payment in enumerate(payments):
            fully_paid = order.saldo_pendiente <= 0 and index == len(payments) - 1
            category = "PRODUCTO PAGADO" if fully_paid else "ABONO"
            Movimientos.objects.update_or_create(
                referencia=f"AUTO-ABONO-{payment.pk}",
                defaults={"fecha": payment.fecha, "tipo_movimiento": "INGRESO", "categoria": category,
                    "descripcion": f"{category.title()} · Orden {order.numero_orden}",
                    "valor_moneda_original": payment.valor, "moneda": "COP",
                    "tasa_dolar": order.tasa_dolar or Decimal("0"), "valor_pesos": payment.valor,
                    "orden_id": order.pk, "vendedor_id": order.vendedor_id,
                    "metodo_pago": payment.metodo_pago, "registrado_por": "Sistema",
                    "observaciones": f"Generado automáticamente desde el abono #{payment.pk}."},
            )


class Migration(migrations.Migration):
    dependencies = [("gestion", "0006_flujo_automatico_comisiones")]
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE movimientos_dinero DROP CONSTRAINT IF EXISTS movimiento_tipo_valido;
                ALTER TABLE movimientos_dinero ADD CONSTRAINT movimiento_tipo_valido
                CHECK (tipo_movimiento IN ('INGRESO', 'EGRESO', 'ENTRADA', 'SALIDA'));
            """,
            reverse_sql="""
                UPDATE movimientos_dinero SET tipo_movimiento = 'INGRESO'
                WHERE tipo_movimiento = 'ENTRADA';
                UPDATE movimientos_dinero SET tipo_movimiento = 'EGRESO'
                WHERE tipo_movimiento = 'SALIDA';
                ALTER TABLE movimientos_dinero DROP CONSTRAINT IF EXISTS movimiento_tipo_valido;
                ALTER TABLE movimientos_dinero ADD CONSTRAINT movimiento_tipo_valido
                CHECK (tipo_movimiento IN ('INGRESO', 'EGRESO'));
            """,
        ),
        migrations.RunPython(create_existing_movements, migrations.RunPython.noop),
    ]

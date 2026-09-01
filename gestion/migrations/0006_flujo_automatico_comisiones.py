from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0005_flete_producto_dolares")]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE comisiones DROP CONSTRAINT IF EXISTS comision_estado_valido;
                ALTER TABLE comisiones ADD CONSTRAINT comision_estado_valido
                CHECK (estado_pago IN ('EN ESPERA', 'PENDIENTE POR PAGAR', 'PAGADA'));

                INSERT INTO comisiones (
                    orden_id, vendedor_id, porcentaje, base_comision,
                    valor_comision, estado_pago, fecha_pago, observaciones, creado_en
                )
                SELECT
                    o.id, o.vendedor_id, v.porcentaje_comision,
                    GREATEST(o.ganancia_bruta, 0),
                    GREATEST(o.ganancia_bruta, 0) * v.porcentaje_comision / 100,
                    CASE WHEN o.saldo_pendiente <= 0 THEN 'PENDIENTE POR PAGAR' ELSE 'EN ESPERA' END,
                    NULL, 'Generada automáticamente desde la orden.', CURRENT_TIMESTAMP
                FROM ordenes o
                JOIN vendedores v ON v.id = o.vendedor_id
                WHERE o.vendedor_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM comisiones c WHERE c.orden_id = o.id);

                UPDATE comisiones c SET estado_pago = CASE
                    WHEN c.estado_pago = 'PAGADA' THEN 'PAGADA'
                    WHEN o.saldo_pendiente <= 0 THEN 'PENDIENTE POR PAGAR'
                    ELSE 'EN ESPERA' END
                FROM ordenes o WHERE o.id = c.orden_id;
            """,
            reverse_sql="""
                UPDATE comisiones SET estado_pago = 'PENDIENTE'
                WHERE estado_pago IN ('EN ESPERA', 'PENDIENTE POR PAGAR');
                ALTER TABLE comisiones DROP CONSTRAINT IF EXISTS comision_estado_valido;
                ALTER TABLE comisiones ADD CONSTRAINT comision_estado_valido
                CHECK (estado_pago IN ('PENDIENTE', 'PAGADA'));
            """,
        ),
    ]

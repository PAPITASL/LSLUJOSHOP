from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0007_movimientos_automaticos_orden")]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE movimientos_dinero SET tipo_movimiento = 'ENTRADA'
                WHERE tipo_movimiento = 'INGRESO';
                UPDATE movimientos_dinero SET tipo_movimiento = 'SALIDA'
                WHERE tipo_movimiento = 'EGRESO';
                ALTER TABLE movimientos_dinero DROP CONSTRAINT IF EXISTS movimiento_tipo_valido;
                ALTER TABLE movimientos_dinero ADD CONSTRAINT movimiento_tipo_valido
                CHECK (tipo_movimiento IN ('ENTRADA', 'SALIDA'));
            """,
            reverse_sql="""
                UPDATE movimientos_dinero SET tipo_movimiento = 'INGRESO'
                WHERE tipo_movimiento = 'ENTRADA';
                UPDATE movimientos_dinero SET tipo_movimiento = 'EGRESO'
                WHERE tipo_movimiento = 'SALIDA';
                ALTER TABLE movimientos_dinero DROP CONSTRAINT IF EXISTS movimiento_tipo_valido;
                ALTER TABLE movimientos_dinero ADD CONSTRAINT movimiento_tipo_valido
                CHECK (tipo_movimiento IN ('INGRESO', 'EGRESO', 'ENTRADA', 'SALIDA'));
            """,
        ),
    ]

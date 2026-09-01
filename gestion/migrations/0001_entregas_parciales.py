from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE detalle_orden
                ADD COLUMN IF NOT EXISTS cantidad_entregada integer NOT NULL DEFAULT 0;

                UPDATE detalle_orden
                SET cantidad_entregada = cantidad
                WHERE cantidad_entregada = 0;

                ALTER TABLE detalle_orden
                DROP CONSTRAINT IF EXISTS detalle_orden_cantidad_entregada_valida;
                ALTER TABLE detalle_orden
                ADD CONSTRAINT detalle_orden_cantidad_entregada_valida
                CHECK (cantidad_entregada >= 0 AND cantidad_entregada <= cantidad);
            """,
            reverse_sql="""
                ALTER TABLE detalle_orden
                DROP CONSTRAINT IF EXISTS detalle_orden_cantidad_entregada_valida;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS cantidad_entregada;
            """,
        ),
    ]

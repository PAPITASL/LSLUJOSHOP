from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0003_permitir_entrega_parcial")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                ALTER TABLE detalle_orden
                ADD COLUMN IF NOT EXISTS cantidad_recibida integer NOT NULL DEFAULT 0;
                ALTER TABLE detalle_orden
                ADD COLUMN IF NOT EXISTS flete_unitario_pesos numeric(16, 2) NOT NULL DEFAULT 0;

                UPDATE detalle_orden SET cantidad_recibida = cantidad
                WHERE cantidad_recibida = 0;

                ALTER TABLE detalle_orden
                DROP CONSTRAINT IF EXISTS detalle_orden_cantidad_recibida_valida;
                ALTER TABLE detalle_orden
                ADD CONSTRAINT detalle_orden_cantidad_recibida_valida
                CHECK (cantidad_recibida >= 0 AND cantidad_recibida <= cantidad);
                """,
                reverse_sql="""
                ALTER TABLE detalle_orden
                DROP CONSTRAINT IF EXISTS detalle_orden_cantidad_recibida_valida;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS flete_unitario_pesos;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS cantidad_recibida;
                """,
            )],
            state_operations=[
                migrations.AddField(
                    model_name="detalleorden",
                    name="cantidad_recibida",
                    field=models.IntegerField(default=0),
                ),
                migrations.AddField(
                    model_name="detalleorden",
                    name="flete_unitario_pesos",
                    field=models.DecimalField(decimal_places=2, default=0, max_digits=16),
                ),
            ],
        ),
    ]

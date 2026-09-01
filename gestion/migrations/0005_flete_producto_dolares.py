from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0004_recepcion_costos_y_flete_producto")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                    ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS
                    flete_unitario_dolares numeric(14, 2) NOT NULL DEFAULT 0;
                    UPDATE detalle_orden d SET flete_unitario_dolares =
                        CASE WHEN o.tasa_dolar > 0
                        THEN ROUND(d.flete_unitario_pesos / o.tasa_dolar, 2)
                        ELSE 0 END
                    FROM ordenes o WHERE d.orden_id = o.id;
                """,
                reverse_sql="ALTER TABLE detalle_orden DROP COLUMN IF EXISTS flete_unitario_dolares;",
            )],
            state_operations=[migrations.AddField(
                model_name="detalleorden",
                name="flete_unitario_dolares",
                field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
            )],
        ),
    ]

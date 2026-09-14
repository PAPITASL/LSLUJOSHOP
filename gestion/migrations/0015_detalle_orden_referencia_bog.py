from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0014_fecha_real_movimientos_costos")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="ALTER TABLE detalle_orden ADD COLUMN referencia_bog varchar(150) NOT NULL DEFAULT '';",
                reverse_sql="ALTER TABLE detalle_orden DROP COLUMN referencia_bog;",
            )],
            state_operations=[migrations.AddField(
                model_name="detalleorden",
                name="referencia_bog",
                field=models.CharField("BOG", max_length=150, blank=True, default=""),
            )],
        ),
    ]

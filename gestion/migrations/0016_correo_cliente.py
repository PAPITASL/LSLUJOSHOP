from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0015_detalle_orden_referencia_bog")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="ALTER TABLE clientes ADD COLUMN correo varchar(254) NULL;",
                reverse_sql="ALTER TABLE clientes DROP COLUMN correo;",
            )],
            state_operations=[migrations.AddField(
                model_name="clientes",
                name="correo",
                field=models.EmailField(blank=True, max_length=254, null=True),
            )],
        ),
    ]

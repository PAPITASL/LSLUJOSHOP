from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0016_correo_cliente")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunSQL(
            "ALTER TABLE ordenes ADD COLUMN costos_completos boolean NOT NULL DEFAULT false;",
            "ALTER TABLE ordenes DROP COLUMN costos_completos;",
        )],
        state_operations=[migrations.AddField(
            model_name="ordenes", name="costos_completos",
            field=models.BooleanField(default=False),
        )],
    )]

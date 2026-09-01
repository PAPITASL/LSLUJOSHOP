from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0009_origen_producto_en_orden")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                ALTER TABLE productos ADD COLUMN IF NOT EXISTS categoria varchar(100) NULL;
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS categoria_producto varchar(100) NULL;
                UPDATE detalle_orden d SET categoria_producto = p.categoria
                FROM productos p WHERE d.producto_id = p.id AND d.categoria_producto IS NULL;
                """,
                reverse_sql="""
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS categoria_producto;
                ALTER TABLE productos DROP COLUMN IF EXISTS categoria;
                """,
            )],
            state_operations=[
                migrations.AddField(model_name="productos", name="categoria", field=models.CharField(blank=True, max_length=100, null=True)),
                migrations.AddField(model_name="detalleorden", name="categoria_producto", field=models.CharField(blank=True, max_length=100, null=True)),
            ],
        ),
    ]

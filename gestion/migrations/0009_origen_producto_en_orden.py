from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gestion", "0008_nombres_entrada_salida")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS origen_producto varchar(12) NOT NULL DEFAULT 'INVENTARIO';
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS marca_producto varchar(100) NULL;
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS modelo_producto varchar(100) NULL;
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS anio_inicio_producto smallint NULL;
                ALTER TABLE detalle_orden ADD COLUMN IF NOT EXISTS anio_fin_producto smallint NULL;

                UPDATE detalle_orden SET origen_producto = CASE WHEN producto_id IS NULL THEN 'EXTERNO' ELSE 'INVENTARIO' END;
                UPDATE detalle_orden d SET
                    marca_producto = p.marca,
                    modelo_producto = p.modelo,
                    anio_inicio_producto = p.anio_inicio,
                    anio_fin_producto = p.anio_fin
                FROM productos p WHERE d.producto_id = p.id;

                ALTER TABLE detalle_orden DROP CONSTRAINT IF EXISTS detalle_orden_origen_producto_valido;
                ALTER TABLE detalle_orden ADD CONSTRAINT detalle_orden_origen_producto_valido
                CHECK (origen_producto IN ('INVENTARIO', 'EXTERNO'));
                """,
                reverse_sql="""
                ALTER TABLE detalle_orden DROP CONSTRAINT IF EXISTS detalle_orden_origen_producto_valido;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS anio_fin_producto;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS anio_inicio_producto;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS modelo_producto;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS marca_producto;
                ALTER TABLE detalle_orden DROP COLUMN IF EXISTS origen_producto;
                """,
            )],
            state_operations=[
                migrations.AddField(model_name="detalleorden", name="origen_producto", field=models.CharField(default="INVENTARIO", max_length=12)),
                migrations.AddField(model_name="detalleorden", name="marca_producto", field=models.CharField(blank=True, max_length=100, null=True)),
                migrations.AddField(model_name="detalleorden", name="modelo_producto", field=models.CharField(blank=True, max_length=100, null=True)),
                migrations.AddField(model_name="detalleorden", name="anio_inicio_producto", field=models.SmallIntegerField(blank=True, null=True)),
                migrations.AddField(model_name="detalleorden", name="anio_fin_producto", field=models.SmallIntegerField(blank=True, null=True)),
            ],
        ),
    ]

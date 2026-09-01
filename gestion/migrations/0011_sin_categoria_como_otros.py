from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0010_categoria_productos")]

    operations = [
        migrations.RunSQL(
            sql="""
            UPDATE productos SET categoria = 'OTROS'
            WHERE categoria IS NULL OR BTRIM(categoria) = '';
            UPDATE detalle_orden SET categoria_producto = 'OTROS'
            WHERE categoria_producto IS NULL OR BTRIM(categoria_producto) = '';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

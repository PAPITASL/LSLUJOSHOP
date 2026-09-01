from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0011_sin_categoria_como_otros")]

    operations = [
        migrations.RunSQL(
            sql="""
            UPDATE productos SET marca = 'FORD', modelo = 'F-150 / LOBO'
            WHERE UPPER(REPLACE(BTRIM(COALESCE(modelo, '')), '_', '-'))
                IN ('LOBO', 'F-150', '150', 'LOBO 150', 'F150');

            UPDATE detalle_orden SET marca_producto = 'FORD', modelo_producto = 'F-150 / LOBO'
            WHERE UPPER(REPLACE(BTRIM(COALESCE(modelo_producto, '')), '_', '-'))
                IN ('LOBO', 'F-150', '150', 'LOBO 150', 'F150');
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

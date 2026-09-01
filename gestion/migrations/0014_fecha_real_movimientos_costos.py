from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0013_comisiones_sobre_total_factura")]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE movimientos_dinero
                SET fecha = creado_en
                WHERE (referencia LIKE 'AUTO-COMPRA-%'
                       OR referencia LIKE 'AUTO-FLETE-%')
                  AND creado_en IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

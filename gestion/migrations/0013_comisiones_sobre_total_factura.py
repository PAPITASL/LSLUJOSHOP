from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0012_unificar_ford_f150_lobo")]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE comisiones c
                SET base_comision = GREATEST(COALESCE(o.total_venta, 0), 0),
                    valor_comision = GREATEST(COALESCE(o.total_venta, 0), 0)
                                     * COALESCE(c.porcentaje, 0) / 100
                FROM ordenes o
                WHERE o.id = c.orden_id;

                UPDATE ordenes o
                SET comision_vendedor = GREATEST(COALESCE(o.total_venta, 0), 0)
                                           * COALESCE(v.porcentaje_comision, 0) / 100,
                    ganancia_neta = COALESCE(o.ganancia_bruta, 0)
                                    - (GREATEST(COALESCE(o.total_venta, 0), 0)
                                       * COALESCE(v.porcentaje_comision, 0) / 100)
                FROM vendedores v
                WHERE v.id = o.vendedor_id;

                UPDATE ordenes
                SET comision_vendedor = 0,
                    ganancia_neta = COALESCE(ganancia_bruta, 0)
                WHERE vendedor_id IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

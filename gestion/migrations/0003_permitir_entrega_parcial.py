from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("gestion", "0002_initial")]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE ordenes
                DROP CONSTRAINT IF EXISTS ordenes_estado_valido;

                ALTER TABLE ordenes
                ADD CONSTRAINT ordenes_estado_valido CHECK (
                    estado IN (
                        'Cotización', 'Pendiente', 'Abonada', 'Pagada',
                        'En proceso', 'Enviada', 'Entrega parcial',
                        'Entregada', 'Cancelada'
                    )
                );
            """,
            reverse_sql="""
                UPDATE ordenes SET estado = 'En proceso'
                WHERE estado = 'Entrega parcial';

                ALTER TABLE ordenes
                DROP CONSTRAINT IF EXISTS ordenes_estado_valido;

                ALTER TABLE ordenes
                ADD CONSTRAINT ordenes_estado_valido CHECK (
                    estado IN (
                        'Cotización', 'Pendiente', 'Abonada', 'Pagada',
                        'En proceso', 'Enviada', 'Entregada', 'Cancelada'
                    )
                );
            """,
        ),
    ]

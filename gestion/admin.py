from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    Clientes,
    Vendedores,
    Productos,
    Ordenes,
    DetalleOrden,
    Abonos,
    Comisiones,
    Recibos,
    MovimientosDinero,
)

admin.site.register(Clientes)
admin.site.register(Vendedores)
admin.site.register(Productos)
admin.site.register(Ordenes)
admin.site.register(DetalleOrden)
admin.site.register(Abonos)
admin.site.register(Comisiones)
admin.site.register(Recibos)
admin.site.register(MovimientosDinero)
# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.db import models


class Clientes(models.Model):
    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    direccion = models.CharField(max_length=250, blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'clientes'

    def __str__(self):
        return self.nombre


class Vendedores(models.Model):
    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30, blank=True, null=True)
    porcentaje_comision = models.DecimalField(max_digits=5, decimal_places=2)
    activo = models.BooleanField()
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'vendedores'

    def __str__(self):
        return self.nombre


class Productos(models.Model):
    id = models.BigAutoField(primary_key=True)
    nombre = models.CharField(max_length=200)
    categoria = models.CharField(max_length=100, blank=True, null=True)
    marca = models.CharField(max_length=100, blank=True, null=True)
    modelo = models.CharField(max_length=100, blank=True, null=True)
    anio_inicio = models.SmallIntegerField(blank=True, null=True)
    anio_fin = models.SmallIntegerField(blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    cantidad_disponible = models.IntegerField()
    costo_dolares = models.DecimalField(max_digits=14, decimal_places=2)
    costo_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    precio_venta_sugerido = models.DecimalField(max_digits=16, decimal_places=2)
    estado = models.CharField(max_length=30)
    imagen = models.CharField(max_length=500, blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'productos'

    def __str__(self):
        return self.nombre


class Ordenes(models.Model):
    id = models.BigAutoField(primary_key=True)
    numero_orden = models.CharField(unique=True, max_length=30)
    fecha = models.DateTimeField()
    cliente = models.ForeignKey(Clientes, models.DO_NOTHING)
    vendedor = models.ForeignKey(Vendedores, models.DO_NOTHING, blank=True, null=True)
    tasa_dolar = models.DecimalField(max_digits=12, decimal_places=4)
    flete_dolares = models.DecimalField(max_digits=14, decimal_places=2)
    flete_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    subtotal_venta = models.DecimalField(max_digits=16, decimal_places=2)
    costo_productos_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    otros_costos_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    costo_total_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    descuento = models.DecimalField(max_digits=16, decimal_places=2)
    total_venta = models.DecimalField(max_digits=16, decimal_places=2)
    ganancia_bruta = models.DecimalField(max_digits=16, decimal_places=2)
    comision_vendedor = models.DecimalField(max_digits=16, decimal_places=2)
    ganancia_neta = models.DecimalField(max_digits=16, decimal_places=2)
    total_abonado = models.DecimalField(max_digits=16, decimal_places=2)
    saldo_pendiente = models.DecimalField(max_digits=16, decimal_places=2)
    estado = models.CharField(max_length=30)
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = 'ordenes'

    def __str__(self):
        return self.numero_orden


class DetalleOrden(models.Model):
    id = models.BigAutoField(primary_key=True)
    orden = models.ForeignKey(Ordenes, models.DO_NOTHING)
    producto = models.ForeignKey(Productos, models.DO_NOTHING, blank=True, null=True)
    descripcion_producto = models.CharField(max_length=250)
    categoria_producto = models.CharField(max_length=100, blank=True, null=True)
    origen_producto = models.CharField(max_length=12, default="INVENTARIO")
    marca_producto = models.CharField(max_length=100, blank=True, null=True)
    modelo_producto = models.CharField(max_length=100, blank=True, null=True)
    anio_inicio_producto = models.SmallIntegerField(blank=True, null=True)
    anio_fin_producto = models.SmallIntegerField(blank=True, null=True)
    cantidad = models.IntegerField()
    cantidad_entregada = models.IntegerField(default=0)
    cantidad_recibida = models.IntegerField(default=0)
    costo_unitario_dolares = models.DecimalField(max_digits=14, decimal_places=2)
    costo_unitario_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    flete_unitario_dolares = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    flete_unitario_pesos = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    precio_venta_unitario = models.DecimalField(max_digits=16, decimal_places=2)
    total_costo_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    total_venta = models.DecimalField(max_digits=16, decimal_places=2)
    ganancia_producto = models.DecimalField(max_digits=16, decimal_places=2)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'detalle_orden'

    def __str__(self):
        return f'{self.orden} - {self.descripcion_producto}'


class Abonos(models.Model):
    id = models.BigAutoField(primary_key=True)
    orden = models.ForeignKey(Ordenes, models.DO_NOTHING)
    fecha = models.DateTimeField()
    valor = models.DecimalField(max_digits=16, decimal_places=2)
    metodo_pago = models.CharField(max_length=50, blank=True, null=True)
    referencia = models.CharField(max_length=150, blank=True, null=True)
    comprobante = models.CharField(max_length=500, blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'abonos'

    def __str__(self):
        return f'Abono #{self.pk} - {self.orden}'


class Comisiones(models.Model):
    id = models.BigAutoField(primary_key=True)
    orden = models.ForeignKey(Ordenes, models.DO_NOTHING)
    vendedor = models.ForeignKey(Vendedores, models.DO_NOTHING)
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
    base_comision = models.DecimalField(max_digits=16, decimal_places=2)
    valor_comision = models.DecimalField(max_digits=16, decimal_places=2)
    estado_pago = models.CharField(max_length=20)
    fecha_pago = models.DateTimeField(blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'comisiones'

    def __str__(self):
        return f'{self.vendedor} - {self.orden}'


class Recibos(models.Model):
    id = models.BigAutoField(primary_key=True)
    orden = models.ForeignKey(Ordenes, models.DO_NOTHING)
    numero_recibo = models.CharField(unique=True, max_length=30)
    fecha_generacion = models.DateTimeField()
    total_recibo = models.DecimalField(max_digits=16, decimal_places=2)
    ruta_pdf = models.CharField(max_length=500, blank=True, null=True)
    generado_por = models.CharField(max_length=150, blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'recibos'

    def __str__(self):
        return self.numero_recibo


class MovimientosDinero(models.Model):
    id = models.BigAutoField(primary_key=True)
    fecha = models.DateTimeField()
    tipo_movimiento = models.CharField(max_length=10)
    categoria = models.CharField(max_length=60)
    descripcion = models.TextField()
    valor_moneda_original = models.DecimalField(max_digits=16, decimal_places=2)
    moneda = models.CharField(max_length=3)
    tasa_dolar = models.DecimalField(max_digits=12, decimal_places=4)
    valor_pesos = models.DecimalField(max_digits=16, decimal_places=2)
    orden = models.ForeignKey(Ordenes, models.DO_NOTHING, blank=True, null=True)
    vendedor = models.ForeignKey(Vendedores, models.DO_NOTHING, blank=True, null=True)
    metodo_pago = models.CharField(max_length=50, blank=True, null=True)
    referencia = models.CharField(max_length=150, blank=True, null=True)
    comprobante = models.CharField(max_length=500, blank=True, null=True)
    registrado_por = models.CharField(max_length=150, blank=True, null=True)
    observaciones = models.TextField(blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = 'movimientos_dinero'

    def __str__(self):
        return f'{self.tipo_movimiento} - {self.descripcion[:50]}'

from datetime import timedelta

from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from .models import (
    Abonos, Clientes, Comisiones, DetalleOrden, MovimientosDinero,
    Ordenes, Productos, Recibos, Vendedores,
)


PRODUCT_CATEGORIES = (
    "FAROLAS", "STOPS", "PERSIANAS / PARRILLAS", "EXPLORADORAS",
    "LUCES Y DIRECCIONALES", "CARROCERÍA", "INTERIOR", "ELÉCTRICO",
    "SUSPENSIÓN", "ESCAPE", "EMBLEMAS Y ACCESORIOS", "OTROS",
)


def normalize_vehicle(brand, model):
    normalized = (model or "").strip().upper().replace("_", "-")
    if normalized in {"LOBO", "F-150", "150", "LOBO 150", "F150"}:
        return "FORD", "F-150 / LOBO"
    return (brand or "").strip() or None, (model or "").strip() or None


class BaseGestionForm(forms.ModelForm):
    """Estilo y validaciones comunes para los formularios de gestión."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3
            if isinstance(field.widget, forms.DateTimeInput):
                field.widget.input_type = "datetime-local"
                field.widget.format = "%Y-%m-%dT%H:%M"
                field.input_formats = ["%Y-%m-%dT%H:%M"]


class OrdenForm(BaseGestionForm):
    ESTADOS = (
        ("Cotización", "Cotización"), ("Pendiente", "Pendiente"),
        ("Abonada", "Abonada"), ("Pagada", "Pagada"),
        ("En proceso", "En proceso"), ("Enviada", "Enviada"),
        ("Entrega parcial", "Entrega parcial"),
        ("Entregada", "Entregada"), ("Cancelada", "Cancelada"),
    )
    estado = forms.ChoiceField(choices=ESTADOS, initial="Pendiente")

    class Meta:
        model = Ordenes
        fields = (
            "fecha", "cliente", "vendedor", "tasa_dolar",
            "otros_costos_pesos", "descuento", "estado", "observaciones",
        )
        labels = {
            "tasa_dolar": "TRM del dólar",
            "otros_costos_pesos": "Otros costos (COP)",
        }

    def __init__(self, *args, **kwargs):
        historical_cost_only = kwargs.pop("historical_cost_only", False)
        super().__init__(*args, **kwargs)
        self.fields["tasa_dolar"].required = False
        if not self.is_bound and not self.instance.pk:
            self.fields["fecha"].initial = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
            self.fields["tasa_dolar"].initial = 0
            self.fields["otros_costos_pesos"].initial = 0
            self.fields["descuento"].initial = 0
        if not self.instance.pk:
            today = timezone.localdate()
            month_start = today.replace(day=1).strftime("%Y-%m-%dT00:00")
            next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            month_end = (next_month - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
            self.fields["fecha"].widget.attrs.update({"min": month_start, "max": month_end})
        if historical_cost_only:
            for field in self.fields.values():
                field.disabled = True

    def clean_fecha(self):
        value = self.cleaned_data["fecha"]
        if not self.instance.pk:
            local_value = timezone.localtime(value) if timezone.is_aware(value) else value
            today = timezone.localdate()
            if (local_value.year, local_value.month) != (today.year, today.month):
                raise forms.ValidationError("Las órdenes nuevas solo pueden registrarse en el mes actual.")
        return value

    def clean_tasa_dolar(self):
        return self.cleaned_data.get("tasa_dolar") or 0


class ProductoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, product):
        details = " · ".join(value for value in (product.marca, product.modelo) if value)
        details = f" · {details}" if details else ""
        price = f"${product.precio_venta_sugerido:,.0f}".replace(",", ".")
        return f"{product.nombre}{details} · Stock: {product.cantidad_disponible} · {price}"


class DetalleOrdenForm(BaseGestionForm):
    producto = ProductoChoiceField(queryset=Productos.objects.all().order_by("nombre"), label="Producto del inventario", required=False)

    class Meta:
        model = DetalleOrden
        fields = (
            "producto", "descripcion_producto", "categoria_producto", "origen_producto", "marca_producto",
            "modelo_producto", "anio_inicio_producto", "anio_fin_producto", "cantidad", "costo_unitario_dolares",
            "costo_unitario_pesos", "flete_unitario_dolares",
            "flete_unitario_pesos", "precio_venta_unitario",
        )
        labels = {
            "costo_unitario_dolares": "Costo (USD)",
            "costo_unitario_pesos": "Costo unitario (COP)",
            "flete_unitario_dolares": "Flete (USD)",
            "flete_unitario_pesos": "Flete unitario (COP)",
            "precio_venta_unitario": "Precio de venta (COP)",
        }
        widgets = {
            "descripcion_producto": forms.HiddenInput(), "categoria_producto": forms.HiddenInput(), "origen_producto": forms.HiddenInput(),
            "marca_producto": forms.HiddenInput(), "modelo_producto": forms.HiddenInput(),
            "anio_inicio_producto": forms.HiddenInput(), "anio_fin_producto": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        historical_cost_only = kwargs.pop("historical_cost_only", False)
        super().__init__(*args, **kwargs)
        self.fields["descripcion_producto"].required = False
        if not self.is_bound and not self.instance.pk:
            self.fields["origen_producto"].initial = "INVENTARIO"
        self.fields["cantidad"].widget.attrs["min"] = 1
        self.fields["costo_unitario_dolares"].widget.attrs.update({"min": 0, "step": "0.01"})
        self.fields["costo_unitario_pesos"].widget.attrs.update({"min": 0, "step": "1"})
        self.fields["flete_unitario_dolares"].widget.attrs.update({"min": 0, "step": "0.01"})
        self.fields["flete_unitario_pesos"].widget.attrs.update({"min": 0, "step": "1"})
        self.fields["precio_venta_unitario"].widget.attrs.update({"min": 0, "step": "1"})
        for field_name in (
            "costo_unitario_dolares", "costo_unitario_pesos",
            "flete_unitario_dolares", "flete_unitario_pesos",
        ):
            self.fields[field_name].required = False
        if not self.is_bound and not self.instance.pk:
            self.fields["flete_unitario_dolares"].initial = 0
            self.fields["flete_unitario_pesos"].initial = 0
        if historical_cost_only:
            editable_costs = {
                "costo_unitario_dolares", "costo_unitario_pesos",
                "flete_unitario_dolares", "flete_unitario_pesos",
            }
            for field_name, field in self.fields.items():
                if field_name not in editable_costs:
                    field.disabled = True

    def clean_producto(self):
        product = self.cleaned_data.get("producto")
        origin = self.data.get(self.add_prefix("origen_producto"), self.initial.get("origen_producto", "INVENTARIO"))
        if origin == "INVENTARIO" and not product:
            raise forms.ValidationError("Selecciona o crea un producto.")
        return product

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("origen_producto") == "EXTERNO" and not (cleaned.get("descripcion_producto") or "").strip():
            self.add_error("descripcion_producto", "Escribe el nombre del producto externo.")
        if cleaned.get("origen_producto") == "EXTERNO" and not (cleaned.get("categoria_producto") or "").strip():
            self.add_error("categoria_producto", "Selecciona o escribe la categoría del producto.")
        brand, model = normalize_vehicle(cleaned.get("marca_producto"), cleaned.get("modelo_producto"))
        cleaned["marca_producto"], cleaned["modelo_producto"] = brand, model
        return cleaned

    def clean_costo_unitario_dolares(self):
        return self.cleaned_data.get("costo_unitario_dolares") or 0

    def clean_costo_unitario_pesos(self):
        return self.cleaned_data.get("costo_unitario_pesos") or 0

    def clean_flete_unitario_dolares(self):
        return self.cleaned_data.get("flete_unitario_dolares") or 0

    def clean_flete_unitario_pesos(self):
        return self.cleaned_data.get("flete_unitario_pesos") or 0

DetalleOrdenFormSet = inlineformset_factory(
    Ordenes, DetalleOrden, form=DetalleOrdenForm,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)


class ProductoForm(BaseGestionForm):
    categoria = forms.ChoiceField(
        choices=(("", "Selecciona una categoría"), *((value, value) for value in PRODUCT_CATEGORIES)),
        label="Categoría",
    )
    ESTADOS = (
        ("Disponible", "Disponible"),
        ("Reservado", "Reservado"),
        ("Vendido", "Vendido"),
        ("Por pedir", "Por pedir"),
        ("Agotado", "Agotado"),
    )
    estado = forms.ChoiceField(choices=ESTADOS, initial="Disponible")

    class Meta:
        model = Productos
        exclude = ("creado_en", "actualizado_en")
        labels = {
            "costo_dolares": "Costo (USD)",
            "costo_pesos": "Costo (COP)",
            "precio_venta_sugerido": "Precio de venta (COP)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = True
        for field_name in ("costo_dolares", "costo_pesos"):
            self.fields[field_name].required = False
            if not self.is_bound and not self.instance.pk:
                self.fields[field_name].initial = 0
        self.fields["costo_pesos"].widget.attrs["step"] = "1"
        self.fields["precio_venta_sugerido"].widget.attrs["step"] = "1"

    def clean_costo_dolares(self):
        return self.cleaned_data.get("costo_dolares") or 0

    def clean_costo_pesos(self):
        return self.cleaned_data.get("costo_pesos") or 0

    def clean(self):
        cleaned = super().clean()
        brand, model = normalize_vehicle(cleaned.get("marca"), cleaned.get("modelo"))
        cleaned["marca"], cleaned["modelo"] = brand, model
        return cleaned


class ClienteForm(BaseGestionForm):
    class Meta:
        model = Clientes
        exclude = ("creado_en", "actualizado_en")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["telefono"].required = False
        self.fields["telefono"].widget.attrs["placeholder"] = "Opcional"

    def clean_telefono(self):
        return self.cleaned_data.get("telefono") or "Sin registrar"


class ComisionForm(BaseGestionForm):
    estado_pago = forms.ChoiceField(choices=(
        ("EN ESPERA", "En espera del pago del cliente"),
        ("PENDIENTE POR PAGAR", "Pendiente por pagar"),
        ("PAGADA", "Pagada"),
    ))

    class Meta:
        model = Comisiones
        exclude = ("creado_en",)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("estado_pago") == "PAGADA" and not cleaned.get("fecha_pago"):
            cleaned["fecha_pago"] = timezone.now()
        elif cleaned.get("estado_pago") != "PAGADA":
            cleaned["fecha_pago"] = None
        return cleaned


class MovimientoForm(BaseGestionForm):
    tipo_movimiento = forms.ChoiceField(label="Tipo de movimiento", choices=(
        ("ENTRADA", "Entrada"),
        ("SALIDA", "Salida"),
    ))

    class Meta:
        model = MovimientosDinero
        fields = ("fecha", "tipo_movimiento", "descripcion", "valor_pesos")
        labels = {
            "tipo_movimiento": "Tipo de movimiento",
            "descripcion": "Descripción u observaciones",
            "valor_pesos": "Valor (COP)",
        }

    def save(self, commit=True):
        movement = super().save(commit=False)
        movement.categoria = movement.categoria or "MOVIMIENTO MANUAL"
        movement.valor_moneda_original = movement.valor_pesos
        movement.moneda = "COP"
        movement.tasa_dolar = 0
        movement.registrado_por = movement.registrado_por or "Registro manual"
        if commit:
            movement.save()
            self.save_m2m()
        return movement


def form_for(model, excluded=()):
    meta = type("Meta", (), {"model": model, "exclude": ("creado_en", "actualizado_en", *excluded)})
    return type(f"{model.__name__}Form", (BaseGestionForm,), {"Meta": meta})


FORM_CLASSES = {
    "clientes": ClienteForm,
    "vendedores": form_for(Vendedores),
    "productos": ProductoForm,
    "ordenes": OrdenForm,
    "detalles": form_for(DetalleOrden),
    "abonos": form_for(Abonos),
    "comisiones": ComisionForm,
    "recibos": form_for(Recibos),
    "movimientos": MovimientoForm,
}

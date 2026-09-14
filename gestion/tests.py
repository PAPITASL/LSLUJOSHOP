from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone
from unittest.mock import patch

from .views import (
    _next_order_number, _order_receipt_filename, _upsert_expense_movement,
    _valid_month_period, record_list,
)
from .forms import DetalleOrdenForm, MovimientoForm, OrdenForm


class OrderMonthlyPeriodTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_month_period_validation(self):
        self.assertEqual(_valid_month_period("2026-08"), "2026-08")
        self.assertEqual(_valid_month_period("2026-13"), "")
        self.assertEqual(_valid_month_period("cualquier-cosa"), "")

    def test_orders_without_period_redirect_to_current_month(self):
        request = self.factory.get("/ordenes/")
        request.user = type("AuthenticatedUser", (), {"is_authenticated": True})()

        response = record_list(request, "ordenes")

        expected_month = timezone.localdate().strftime("%Y-%m")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/ordenes/?periodo={expected_month}")

    def test_invalid_order_period_is_replaced_and_keeps_search(self):
        request = self.factory.get("/ordenes/", {"periodo": "2026-99", "q": "301"})
        request.user = type("AuthenticatedUser", (), {"is_authenticated": True})()

        response = record_list(request, "ordenes")

        expected_month = timezone.localdate().strftime("%Y-%m")
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"periodo={expected_month}", response.url)
        self.assertIn("q=301", response.url)

    def test_movements_without_period_redirect_to_current_month(self):
        request = self.factory.get("/gestion/movimientos/")
        request.user = type("AuthenticatedUser", (), {"is_authenticated": True})()

        response = record_list(request, "movimientos")

        expected_month = timezone.localdate().strftime("%Y-%m")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/gestion/movimientos/?periodo={expected_month}")


class OrderNumberTests(SimpleTestCase):
    @patch("gestion.views.Ordenes.objects.values_list", return_value=[])
    def test_first_order_starts_at_275(self, _values_list):
        self.assertEqual(_next_order_number(), "275")

    @patch("gestion.views.Ordenes.objects.values_list", return_value=["275", "texto", "276"])
    def test_order_number_continues_after_existing_numeric_value(self, _values_list):
        self.assertEqual(_next_order_number(), "277")


class OrderReceiptFilenameTests(SimpleTestCase):
    def test_filename_contains_client_name(self):
        self.assertEqual(_order_receipt_filename("Juan Perez"), "Orden - Juan Perez.pdf")

    def test_filename_removes_unsupported_characters(self):
        self.assertEqual(_order_receipt_filename('Ana / Torres: Norte'), "Orden - Ana Torres Norte.pdf")


class ExternalOrderProductTests(SimpleTestCase):
    def test_external_product_can_exist_only_on_invoice_without_costs(self):
        form = DetalleOrdenForm({
            "producto": "", "descripcion_producto": "Producto externo",
            "categoria_producto": "Farolas",
            "origen_producto": "EXTERNO", "marca_producto": "Ford",
            "modelo_producto": "Lobo", "cantidad": "1",
            "costo_unitario_dolares": "", "costo_unitario_pesos": "",
            "flete_unitario_dolares": "", "flete_unitario_pesos": "",
            "precio_venta_unitario": "380000",
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertIsNone(form.cleaned_data["producto"])
        self.assertEqual(form.cleaned_data["costo_unitario_pesos"], 0)


class HistoricalOrderCostFormTests(SimpleTestCase):
    def test_only_order_observations_are_editable(self):
        form = OrdenForm(historical_cost_only=True)
        editable = {name for name, field in form.fields.items() if not field.disabled}
        self.assertEqual(editable, {"observaciones"})

    def test_only_product_cost_fields_are_editable(self):
        form = DetalleOrdenForm(historical_cost_only=True)
        editable = {name for name, field in form.fields.items() if not field.disabled}
        self.assertEqual(editable, {
            "referencia_bog",
            "costo_unitario_dolares", "costo_unitario_pesos",
            "flete_unitario_dolares", "flete_unitario_pesos",
        })


class ExpenseMovementDateTests(SimpleTestCase):
    @patch("gestion.views.MovimientosDinero.objects.update_or_create")
    def test_new_movement_uses_registration_date_only_when_created(self, update_or_create):
        registration_date = timezone.now()
        defaults = {"valor_pesos": 50000, "tipo_movimiento": "SALIDA"}

        _upsert_expense_movement("AUTO-COMPRA-1", registration_date, defaults)

        update_or_create.assert_called_once_with(
            referencia="AUTO-COMPRA-1",
            defaults=defaults,
            create_defaults={**defaults, "fecha": registration_date},
        )
        self.assertNotIn("fecha", update_or_create.call_args.kwargs["defaults"])


class ManualMovementFormTests(SimpleTestCase):
    def test_form_only_requests_manual_movement_data(self):
        form = MovimientoForm()
        self.assertEqual(
            list(form.fields),
            ["fecha", "tipo_movimiento", "descripcion", "valor_pesos"],
        )

    def test_technical_values_are_filled_automatically(self):
        form = MovimientoForm({
            "fecha": "2026-09-01T10:30",
            "tipo_movimiento": "SALIDA",
            "descripcion": "Compra de bolsas",
            "valor_pesos": "25000",
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        movement = form.save(commit=False)
        self.assertEqual(movement.categoria, "MOVIMIENTO MANUAL")
        self.assertEqual(movement.valor_moneda_original, movement.valor_pesos)
        self.assertEqual(movement.moneda, "COP")
        self.assertEqual(movement.tasa_dolar, 0)

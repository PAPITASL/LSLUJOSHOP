from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import OrdenForm
from .inventory import summarize_inventory
from .models import Clientes, DetalleOrden, Ordenes, Productos


class InventoryStateTests(SimpleTestCase):
    def test_manual_delivery_and_cancellation_require_inventory_workflow(self):
        for state in ("Entregada", "Entrega parcial", "Cancelada"):
            form = OrdenForm(instance=Ordenes(pk=1, estado="Pendiente"))
            form.cleaned_data = {"estado": state}
            with self.assertRaises(ValidationError):
                form.clean_estado()

    def test_existing_delivery_state_can_be_preserved_for_cost_edits(self):
        form = OrdenForm(instance=Ordenes(pk=1, estado="Entregada"))
        form.cleaned_data = {"estado": "Entregada"}
        self.assertEqual(form.clean_estado(), "Entregada")

    def test_commitments_exclude_quotes_and_cancelled_orders(self):
        product = Productos(cantidad_disponible=5)
        details = [DetalleOrden(orden=Ordenes(estado=state), cantidad=quantity, cantidad_entregada=delivered)
                   for state, quantity, delivered in [
                       ("Pendiente", 4, 1), ("Pagada", 3, 0),
                       ("Cotización", 10, 0), ("Cancelada", 7, 0), ("Entregada", 2, 2),
                   ]]
        summarize_inventory(product, details)
        self.assertEqual((product.committed_units, product.free_units, product.missing_units), (6, 0, 1))
        self.assertEqual(product.delivered_units, 3)
        self.assertEqual(len(product.order_links), 5)


@skipUnless(connection.vendor == "sqlite", "Use --settings=config.test_settings for isolated inventory tests")
class InventoryWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # Production tables predate Django and are unmanaged. Build only the
        # isolated test schema, without executing PostgreSQL data migrations.
        cls.shop_models = list(apps.get_app_config("gestion").get_models())
        with connection.schema_editor() as editor:
            for model in cls.shop_models:
                editor.create_model(model)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with connection.schema_editor() as editor:
            for model in reversed(cls.shop_models):
                editor.delete_model(model)

    def create_record(self, model, **values):
        for field in model._meta.fields:
            if isinstance(field, models.DecimalField):
                values.setdefault(field.name, Decimal("0"))
        return model.objects.create(**values)

    def setUp(self):
        self.client.force_login(User.objects.create_user(username="inventory-test"))
        self.customer = Clientes.objects.create(nombre="Cliente de prueba", telefono="123")
        self.product = self.create_record(Productos, nombre="Farola", cantidad_disponible=5, estado="Disponible")
        self.order = self.create_record(Ordenes, numero_orden="TEST-1", fecha=timezone.now(), cliente=self.customer, estado="Pendiente")
        self.detail = self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                                          descripcion_producto="Farola", cantidad=4)
        self.commission_patch = patch("gestion.views._sync_order_commission")
        self.commission_patch.start()
        self.addCleanup(self.commission_patch.stop)

    def deliver(self, quantity):
        return self.client.post(reverse("order_delivery", args=[self.order.pk]), {
            f"entregar_{self.detail.pk}": quantity, "abono": "0",
        })

    def test_partial_then_full_delivery_subtracts_only_delivered_units(self):
        self.assertEqual(self.deliver(2).status_code, 302)
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 3)
        self.assertEqual(self.order.estado, "Entrega parcial")
        self.assertEqual(self.deliver(2).status_code, 302)
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 1)
        self.assertEqual(self.order.estado, "Entregada")
        self.deliver(2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 1)

    def test_insufficient_stock_rolls_back(self):
        self.product.cantidad_disponible = 1
        self.product.save()
        self.assertEqual(self.deliver(2).status_code, 200)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 1)
        self.assertEqual(self.detail.cantidad_entregada, 0)

    def test_cancel_returns_delivered_units_only_once(self):
        self.deliver(2)
        url = reverse("order_cancel", args=[self.order.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 5)
        self.assertEqual(self.detail.cantidad_entregada, 0)

    def test_inventory_shows_linked_order_and_free_units(self):
        response = self.client.get(reverse("record_list", args=["productos"]))
        self.assertContains(response, "TEST-1")
        product = response.context["records"][0]
        self.assertEqual((product.committed_units, product.free_units), (4, 1))
        self.assertContains(response, reverse("order_delivery", args=[self.order.pk]))

    def test_pending_stock_is_not_counted_twice_for_same_product(self):
        self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                           descripcion_producto="Otra farola", cantidad=4)
        response = self.client.get(reverse("pending_deliveries"))
        self.assertEqual(response.context["ready_units"], 5)
        self.assertEqual(response.context["total_units"], 8)

    def test_complete_report_download_is_pdf(self):
        response = self.client.get(reverse("reports_dashboard"), {"formato": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))

    def test_priorities_use_history_for_recurrence_and_all_categories(self):
        from .report_periods import ReportMonth
        period = ReportMonth(2026, 10)
        self.order.fecha = period.start
        self.order.save()
        self.detail.categoria_producto = "OTROS"
        self.detail.total_venta = 100
        self.detail.save()
        self.create_record(Ordenes, numero_orden="PRIOR", fecha=period.previous.start,
                           cliente=self.customer, estado="Pendiente")
        response = self.client.get(reverse("reports_dashboard"), {"meses": "2026-10"})
        self.assertEqual(response.context["recurring_clients"], 1)
        self.assertEqual(response.context["previous_recurring_clients"], 0)
        priorities = response.context["next_month_priorities"]
        self.assertEqual(priorities[0]["code"], "classification")
        self.assertIn("100,0%", priorities[0]["reason"])

    def test_insights_demand_is_distinct_and_limited_to_selected_period(self):
        from .report_periods import ReportMonth
        period = ReportMonth(2026, 10)
        self.order.fecha = period.start
        self.order.save()
        self.product.cantidad_disponible = 0
        self.product.save()
        self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                           descripcion_producto="Otra línea", cantidad=1)
        other = self.create_record(Productos, nombre="Anterior", cantidad_disponible=0, estado="Agotado")
        old = self.create_record(Ordenes, numero_orden="PREVIOUS", fecha=period.previous.start,
                                 cliente=self.customer, estado="Pendiente")
        self.create_record(DetalleOrden, orden=old, producto=other, descripcion_producto="Anterior", cantidad=1)
        response = self.client.get(reverse("reports_dashboard"), {"meses": "2026-10"})
        self.assertEqual(response.context["exhausted_with_demand"], 1)
        self.assertEqual(response.context["pending_delivery_orders"], 1)
        self.assertEqual(response.context["previous_active_clients"], 1)
        self.assertLessEqual(len(response.context["monthly_insights"]), 5)

    def test_monthly_close_boundaries_and_later_payments(self):
        from datetime import timedelta
        from .report_periods import ReportMonth
        from .models import Abonos, MovimientosDinero
        period = ReportMonth(2026, 10)
        self.order.fecha = period.start
        self.order.total_venta = 100
        self.order.total_abonado = 100
        self.order.saldo_pendiente = 0
        self.order.save()
        for index, moment in enumerate([period.start - timedelta(microseconds=1), period.end - timedelta(microseconds=1), period.end]):
            self.create_record(Ordenes, numero_orden=f"BOUNDARY-{index}", fecha=moment,
                               cliente=self.customer, estado="Pendiente", total_venta=100)
        Abonos.objects.create(orden=self.order, fecha=period.end - timedelta(microseconds=1), valor=30)
        Abonos.objects.create(orden=self.order, fecha=period.end, valor=70)
        for moment, amount in [(period.start - timedelta(microseconds=1), 500), (period.start, 20),
                               (period.end - timedelta(microseconds=1), 30), (period.end, 900)]:
            self.create_record(MovimientosDinero, fecha=moment, tipo_movimiento="ENTRADA", valor_pesos=amount)
            self.create_record(MovimientosDinero, fecha=moment, tipo_movimiento="SALIDA", valor_pesos=amount)
        response = self.client.get(reverse("reports_dashboard"), {"meses": "2026-10"})
        data = response.context
        self.assertEqual(data["total_sales"], 200)
        self.assertEqual(data["orders_count"], 2)
        self.assertEqual(data["total_paid"], 30)
        self.assertEqual(data["pending_balance"], 170)
        self.assertEqual(data["payments_total"], 30)
        self.assertEqual(data["income"], 50)
        self.assertEqual(data["expenses"], 50)
        self.assertEqual(data["comparison_label"], "Septiembre 2026")
        self.assertEqual(data["sales_variation"]["value"], 100)
        self.assertContains(response, "01/10/2026")
        self.assertContains(response, "Existencias registradas al momento de generar este informe.")
        self.order.refresh_from_db()
        self.assertEqual(self.order.total_abonado, 100)

    def test_invalid_month_does_not_export_entire_history(self):
        response = self.client.get(reverse("reports_dashboard"), {"meses": "2026-13", "formato": "pdf"})
        self.assertEqual(response.status_code, 400)

    def test_monthly_pdf_uses_selected_month_and_cutoff_balance(self):
        from io import BytesIO
        from .report_periods import ReportMonth
        from .models import Abonos
        period = ReportMonth(2027, 1)
        self.order.fecha = period.start
        self.order.total_venta = 100
        self.order.total_abonado = 100
        self.order.saldo_pendiente = 0
        self.order.save()
        Abonos.objects.create(orden=self.order, fecha=period.end, valor=100)
        with patch("gestion.views.build_full_report", return_value=BytesIO(b"%PDF-test")) as builder:
            response = self.client.get(reverse("reports_dashboard"), {"meses": "2027-01", "formato": "pdf"})
            data, orders = builder.call_args.args
            self.assertEqual(data["comparison_label"], "Diciembre 2026")
            self.assertEqual(data["report_title"], "CIERRE MENSUAL")
            self.assertEqual(orders[0].total_abonado, 0)
            self.assertEqual(orders[0].saldo_pendiente, 100)
            self.assertIn("cierre-mensual-2027-01.pdf", response["Content-Disposition"])
            response.close()

    def test_complete_report_keeps_selected_months_and_excludes_other_orders(self):
        from io import BytesIO
        from datetime import datetime
        self.order.fecha = timezone.make_aware(datetime(2026, 1, 10))
        self.order.save()
        self.create_record(Ordenes, numero_orden="OUTSIDE", fecha=timezone.make_aware(datetime(2026, 2, 10)),
                           cliente=self.customer, estado="Pendiente")
        with patch("gestion.views.build_full_report", return_value=BytesIO(b"%PDF-test")) as builder:
            response = self.client.get(reverse("reports_dashboard"), {"formato": "pdf", "meses": "2026-01,2026-03"})
            context, orders = builder.call_args.args
            self.assertEqual(context["selected_periods"], ["2026-01", "2026-03"])
            self.assertEqual(list(orders.values_list("numero_orden", flat=True)), ["TEST-1"])
            self.assertEqual(context["orders_count"], 1)
            response.close()

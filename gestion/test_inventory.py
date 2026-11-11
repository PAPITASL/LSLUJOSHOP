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
from .models import Abonos, Clientes, DetalleOrden, Ordenes, Productos


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

    def test_release_product_frees_stock_and_recalculates_order(self):
        from .inventory import stock_products
        from .models import MovimientosDinero
        self.detail.origen_producto = "EXTERNO"
        self.detail.cantidad_recibida = 4
        self.detail.costo_unitario_pesos = 10
        self.detail.total_costo_pesos = 40
        self.detail.total_venta = 100
        self.detail.save()
        self.order.total_venta = 100
        self.order.save()
        Abonos.objects.create(orden=self.order, fecha=timezone.now(), valor=50)
        url = reverse("order_release_product", args=[self.order.pk, self.detail.pk])
        self.assertContains(self.client.get(url), "Confirmar paso a inventario")
        self.assertTrue(DetalleOrden.objects.filter(pk=self.detail.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)
        self.order.refresh_from_db()
        product = stock_products().get(pk=self.product.pk)
        self.assertEqual((product.cantidad_disponible, product.stock_free), (5, 5))
        self.assertEqual((self.order.total_venta, self.order.costo_productos_pesos, self.order.saldo_pendiente), (0, 0, 0))
        self.assertEqual(self.order.total_abonado, 50)
        self.assertIn("pasa a inventario libre", self.order.observaciones)
        purchase = MovimientosDinero.objects.get(referencia=f"AUTO-INVENTARIO-COMPRA-{self.detail.pk}")
        self.assertIsNone(purchase.orden_id)
        self.assertEqual(purchase.valor_pesos, 40)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 5)

    def test_release_rejects_delivered_or_unpurchased_product(self):
        url = reverse("order_release_product", args=[self.order.pk, self.detail.pk])
        self.detail.cantidad_entregada = 1
        self.detail.save()
        self.client.post(url)
        self.assertTrue(DetalleOrden.objects.filter(pk=self.detail.pk).exists())
        self.detail.cantidad_entregada = 0
        self.detail.producto = None
        self.detail.save()
        self.client.post(url)
        self.assertTrue(DetalleOrden.objects.filter(pk=self.detail.pk).exists())

    def test_release_keeps_other_order_products_reserved(self):
        from .inventory import stock_products
        other = self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                                   descripcion_producto="Segunda línea", cantidad=1, total_venta=200)
        self.client.post(reverse("order_release_product", args=[self.order.pk, self.detail.pk]))
        self.order.refresh_from_db()
        self.assertTrue(DetalleOrden.objects.filter(pk=other.pk).exists())
        self.assertEqual(self.order.total_venta, 200)
        self.assertEqual(stock_products().get(pk=self.product.pk).stock_free, 4)

    def test_pending_costs_lists_only_uncosted_products_in_active_orders(self):
        priced_detail = self.create_record(
            DetalleOrden, orden=self.order, producto=self.product,
            descripcion_producto="Producto con costo", cantidad=1,
            costo_unitario_dolares=Decimal("10"),
        )
        cancelled_order = self.create_record(
            Ordenes, numero_orden="TEST-2", fecha=timezone.now(),
            cliente=self.customer, estado="Cancelada",
        )
        self.create_record(
            DetalleOrden, orden=cancelled_order, producto=self.product,
            descripcion_producto="Producto cancelado", cantidad=1,
        )
        previous_month_order = self.create_record(
            Ordenes, numero_orden="TEST-3",
            fecha=self.order.fecha.replace(year=2000, month=1),
            cliente=self.customer, estado="Pendiente",
        )
        self.create_record(
            DetalleOrden, orden=previous_month_order, producto=self.product,
            descripcion_producto="Producto de otro mes", cantidad=1,
        )

        response = self.client.get(reverse("pending_costs"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Farola")
        self.assertContains(response, "Registrar costos")
        self.assertContains(response, priced_detail.descripcion_producto)
        group = response.context["order_groups"][0]
        self.assertEqual([item.pk for item in group["details"]], [self.detail.pk])
        self.assertEqual([item.pk for item in group["purchased_details"]], [priced_detail.pk])
        self.assertEqual((group["pending_count"], group["purchased_count"], group["progress"]), (1, 1, 50))
        searched = self.client.get(reverse("pending_costs"), {"q": "Farola"})
        self.assertContains(searched, priced_detail.descripcion_producto)
        self.assertNotContains(response, "Producto cancelado")
        self.assertNotContains(response, "Producto de otro mes")
        self.assertEqual(response.context["orders_count"], 1)
        self.assertEqual(response.context["items_count"], 1)
        self.assertEqual(response.context["periodo"], timezone.localdate().strftime("%Y-%m"))

        previous_month = self.client.get(
            reverse("pending_costs"), {"periodo": "2000-01"},
        )
        self.assertContains(previous_month, "Producto de otro mes")
        self.assertNotContains(previous_month, "Farola")

    def test_october_orders_are_temporarily_editable_without_unlocking_other_past_months(self):
        self.order.fecha = self.order.fecha.replace(year=2026, month=10, day=1)
        self.order.save()

        listing = self.client.get(
            reverse("record_list", args=["ordenes"]), {"periodo": "2026-10"},
        )
        self.assertEqual(listing.status_code, 200)
        listed_order = listing.context["records"][0]
        self.assertTrue(listed_order.can_edit_order)
        self.assertFalse(listed_order.can_manage_order)

        editor = self.client.get(reverse("record_update", args=["ordenes", self.order.pk]))
        self.assertEqual(editor.status_code, 200)
        self.assertFalse(editor.context["historical_cost_only"])
        self.assertTrue(editor.context["temporarily_editable_historical"])
        self.assertFalse(editor.context["form"].fields["fecha"].disabled)
        self.assertFalse(editor.context["formset"].forms[0].fields["cantidad"].disabled)
        self.assertContains(editor, "Octubre de 2026 está habilitado temporalmente")

        self.order.fecha = self.order.fecha.replace(month=9)
        self.order.save()
        locked_editor = self.client.get(reverse("record_update", args=["ordenes", self.order.pk]))
        self.assertTrue(locked_editor.context["historical_cost_only"])
        self.assertFalse(locked_editor.context["temporarily_editable_historical"])

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

    def test_last_physical_unit_can_be_delivered_even_when_committed(self):
        self.product.cantidad_disponible = 1
        self.product.save()
        response = self.client.get(reverse("order_delivery", args=[self.order.pk]))
        self.assertEqual(response.context["details"][0].ready_quantity, 1)
        self.assertEqual(self.deliver(1).status_code, 302)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 0)
        self.assertEqual(self.detail.cantidad_entregada, 1)

    def test_delivery_screen_does_not_repeat_available_unit(self):
        self.product.cantidad_disponible = 1
        self.product.save()
        self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                           descripcion_producto="Otra línea", cantidad=1)
        response = self.client.get(reverse("order_delivery", args=[self.order.pk]))
        self.assertEqual([d.ready_quantity for d in response.context["details"]], [1, 0])

    def test_stock_choice_distinguishes_physical_from_free(self):
        from .inventory import stock_products
        from .forms import ProductoChoiceField
        self.product.cantidad_disponible = 1
        self.product.save()
        product = stock_products().get(pk=self.product.pk)
        self.assertEqual((product.cantidad_disponible, product.stock_free, product.stock_committed), (1, 0, 4))
        label = ProductoChoiceField(queryset=stock_products()).label_from_instance(product)
        self.assertIn(f"#{self.product.pk}", label)
        self.assertIn("Libres: 0", label)

    def test_reset_later_line_can_supply_earlier_delivery(self):
        self.product.cantidad_disponible = 0
        self.product.save()
        later = self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                                  descripcion_producto="Entrega a corregir", cantidad=1, cantidad_entregada=1)
        response = self.client.post(reverse("order_delivery", args=[self.order.pk]), {
            f"entregar_{self.detail.pk}": "1", f"estado_entrega_{later.pk}": "no_entregado", "abono": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual((self.product.cantidad_disponible, self.detail.cantidad_entregada, later.cantidad_entregada), (0, 1, 0))

    def test_new_product_choices_exclude_sold_empty_and_fully_committed(self):
        from .forms import DetalleOrdenForm
        sold = self.create_record(Productos, nombre="Vendido", cantidad_disponible=0, estado="Vendido")
        empty = self.create_record(Productos, nombre="Agotado", cantidad_disponible=0, estado="Agotado")
        self.product.cantidad_disponible = 4
        self.product.save()
        available = self.create_record(Productos, nombre="Libre", cantidad_disponible=1, estado="Disponible")
        ids = set(DetalleOrdenForm().fields["producto"].queryset.values_list("pk", flat=True))
        self.assertIn(available.pk, ids)
        self.assertTrue(ids.isdisjoint({sold.pk, empty.pk, self.product.pk}))

    def test_inventory_selection_combines_lines_and_excludes_other_orders(self):
        from .inventory import validate_inventory_selection
        new_order = Ordenes(estado="Pendiente")
        line = {"producto": self.product, "origen_producto": "INVENTARIO", "cantidad": 1}
        products = {self.product.pk: self.product}
        validate_inventory_selection(new_order, [line], {}, products)
        with self.assertRaisesMessage(ValidationError, "hay 1 libres"):
            validate_inventory_selection(new_order, [line, line], {}, products)

    def test_inventory_selection_preserves_current_order_commitment(self):
        from .inventory import validate_inventory_selection
        line = {"id": self.detail, "producto": self.product,
                "origen_producto": "INVENTARIO", "cantidad": 5}
        products = {self.product.pk: self.product}
        previous = {self.detail.pk: self.detail}
        validate_inventory_selection(self.order, [line], previous, products)
        line["cantidad"] = 6
        with self.assertRaises(ValidationError):
            validate_inventory_selection(self.order, [line], previous, products)

    def test_partially_committed_product_remains_selectable(self):
        from .forms import DetalleOrdenForm
        product = DetalleOrdenForm().fields["producto"].queryset.get(pk=self.product.pk)
        self.assertEqual(product.stock_free, 1)

    def test_existing_sold_product_remains_only_on_original_line(self):
        from .forms import DetalleOrdenForm, DetalleOrdenFormSet
        self.product.cantidad_disponible = 0
        self.product.estado = "Vendido"
        self.product.save()
        existing = DetalleOrdenForm(instance=self.detail)
        self.assertTrue(existing.fields["producto"].queryset.filter(pk=self.product.pk).exists())
        new_line = DetalleOrdenFormSet(instance=self.order).empty_form
        self.assertFalse(new_line.fields["producto"].queryset.filter(pk=self.product.pk).exists())

    def test_inventory_list_includes_products_beyond_old_200_limit(self):
        for index in range(201):
            self.create_record(Productos, nombre=f"Disponible {index}", cantidad_disponible=1, estado="Disponible")
        response = self.client.get(reverse("record_list", args=["productos"]))
        self.assertEqual(len(response.context["records"]), 202)
        self.assertIn(self.product.pk, [item.pk for item in response.context["records"]])

    def test_insufficient_stock_rolls_back(self):
        self.product.cantidad_disponible = 1
        self.product.save()
        self.assertEqual(self.deliver(2).status_code, 200)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 1)
        self.assertEqual(self.detail.cantidad_entregada, 0)

    def test_delivery_can_be_reset_and_delivered_again_without_stock_drift(self):
        self.deliver(4)
        url = reverse("order_delivery", args=[self.order.pk])
        self.assertContains(self.client.get(url), "Cambiar a no entregado")
        data = {f"estado_entrega_{self.detail.pk}": "no_entregado", "abono": "0"}
        for _ in range(2):
            self.assertEqual(self.client.post(url, data).status_code, 302)
            self.product.refresh_from_db()
            self.detail.refresh_from_db()
            self.order.refresh_from_db()
            self.assertEqual(self.product.cantidad_disponible, 5)
            self.assertEqual(self.detail.cantidad_entregada, 0)
            self.assertEqual(self.order.estado, "Pagada")
        self.assertContains(self.client.get(reverse("pending_deliveries")), "TEST-1")
        self.assertEqual(self.deliver(4).status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 1)

    def test_reset_partial_delivery_preserves_pending_balance(self):
        self.order.total_venta = Decimal("100")
        self.order.saldo_pendiente = Decimal("100")
        self.order.save()
        self.deliver(2)
        response = self.client.post(reverse("order_delivery", args=[self.order.pk]), {
            f"estado_entrega_{self.detail.pk}": "no_entregado",
        })
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 5)
        self.assertEqual(self.order.estado, "Pendiente")
        self.assertEqual(self.order.saldo_pendiente, Decimal("100"))

    def test_reset_and_delivery_of_same_product_is_rejected(self):
        self.deliver(2)
        response = self.client.post(reverse("order_delivery", args=[self.order.pk]), {
            f"estado_entrega_{self.detail.pk}": "no_entregado",
            f"entregar_{self.detail.pk}": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.detail.refresh_from_db()
        self.assertEqual(self.product.cantidad_disponible, 3)
        self.assertEqual(self.detail.cantidad_entregada, 2)

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

    def test_exhausted_delivery_leaves_inventory_and_return_restores_it(self):
        self.product.cantidad_disponible = 4
        self.product.save()
        self.assertEqual(self.deliver(4).status_code, 302)
        response = self.client.get(reverse("record_list", args=["productos"]))
        self.assertEqual(response.context["records"], [])
        self.detail.refresh_from_db()
        self.assertEqual(self.detail.cantidad_entregada, 4)
        self.assertEqual(self.detail.producto_id, self.product.pk)
        report = self.client.get(reverse("reports_dashboard"))
        self.assertEqual(report.context["inventory_products"], 0)
        self.assertEqual(report.context["exhausted_count"], 0)
        self.client.post(reverse("order_delivery", args=[self.order.pk]), {
            f"estado_entrega_{self.detail.pk}": "no_entregado",
        })
        response = self.client.get(reverse("record_list", args=["productos"]))
        self.assertEqual([item.pk for item in response.context["records"]], [self.product.pk])

    def test_delivery_keeps_remaining_stock_in_inventory(self):
        self.deliver(4)
        response = self.client.get(reverse("record_list", args=["productos"]))
        self.assertEqual(response.context["records"][0].cantidad_disponible, 1)

    def test_pending_stock_is_not_counted_twice_for_same_product(self):
        self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                           descripcion_producto="Otra farola", cantidad=4)
        response = self.client.get(reverse("pending_deliveries"))
        self.assertEqual(response.context["ready_units"], 5)
        self.assertEqual(response.context["total_units"], 8)

    def test_pending_deliveries_filter_purchase_by_cost_in_either_currency(self):
        dollars = self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                                    descripcion_producto="Comprado USD", cantidad=1, costo_unitario_dolares=10)
        pesos = self.create_record(DetalleOrden, orden=self.order, producto=self.product,
                                  descripcion_producto="Comprado COP", cantidad=1, costo_unitario_pesos=100)
        self.detail.flete_unitario_pesos = 50
        self.detail.save()
        url = reverse("pending_deliveries")
        def ids(response):
            return {d.pk for group in response.context["order_groups"] for d in group["details"]}
        missing = self.client.get(url, {"compra": "sin_comprar"})
        self.assertEqual(ids(missing), {self.detail.pk})
        self.assertEqual(missing.context["total_units"], 4)
        self.assertEqual(ids(self.client.get(url, {"compra": "comprados"})), {dollars.pk, pesos.pk})
        self.assertEqual(ids(self.client.get(url)), {self.detail.pk, dollars.pk, pesos.pk})
        self.assertEqual(ids(self.client.get(url, {"compra": "comprados", "q": "USD"})), {dollars.pk})

    def test_complete_report_download_is_pdf(self):
        response = self.client.get(reverse("reports_dashboard"), {"formato": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF-"))

    def test_report_separates_actual_delivery_and_payment_status(self):
        self.order.total_venta = Decimal("100")
        self.order.estado = "Pendiente"
        self.order.save()

        delivered_order = self.create_record(
            Ordenes, numero_orden="DELIVERED", fecha=timezone.now(),
            cliente=self.customer, estado="Pendiente", total_venta=100,
        )
        self.create_record(
            DetalleOrden, orden=delivered_order, producto=self.product,
            descripcion_producto="Entregado", cantidad=1, cantidad_entregada=1,
        )
        Abonos.objects.create(orden=delivered_order, fecha=timezone.now(), valor=100)

        unpaid_order = self.create_record(
            Ordenes, numero_orden="UNPAID", fecha=timezone.now(),
            cliente=self.customer, estado="Pagada", total_venta=50,
        )
        self.create_record(
            DetalleOrden, orden=unpaid_order, producto=self.product,
            descripcion_producto="No entregado", cantidad=2,
        )

        response = self.client.get(reverse("reports_dashboard"))

        self.assertEqual(response.status_code, 200)
        delivery_counts = {row["label"]: row["value"] for row in response.context["status_chart"]}
        payment_counts = {row["label"]: row["value"] for row in response.context["payment_chart"]}
        self.assertEqual(delivery_counts["Entregada"], 1)
        self.assertEqual(delivery_counts["Pendiente de entrega"], 2)
        self.assertEqual(payment_counts["Pagadas"], 1)
        self.assertEqual(payment_counts["Por pagar"], 2)

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
            self.assertEqual([order.numero_orden for order in orders], ["TEST-1"])
            self.assertEqual(context["orders_count"], 1)
            response.close()

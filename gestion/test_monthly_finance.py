from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.apps import apps
from django.db import connection, models
from django.test import RequestFactory, TestCase
from django.utils import timezone
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate

from .executive_pdf import build_executive_report
from .models import Abonos, Clientes, DetalleOrden, MovimientosDinero, Ordenes
from .monthly_finance import build_monthly_finance
from .report_periods import ReportMonth
from .views import bog_list, record_list, reports_dashboard


def local(year, month, day, hour=12):
    return timezone.make_aware(datetime(year, month, day, hour), timezone.get_default_timezone())


class MonthlyFinanceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "sqlite":
            raise RuntimeError("Run with --settings=config.test_settings")
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

    def setUp(self):
        self.period = ReportMonth(2026, 9)
        self.as_of = local(2026, 10, 21)
        self.customer = Clientes.objects.create(nombre="Cliente financiero", telefono="3001234567")

    def record(self, model, **values):
        for field in model._meta.fields:
            if isinstance(field, models.DecimalField):
                values.setdefault(field.name, Decimal("0"))
        return model.objects.create(**values)

    def order(self, total=1000, day=1, month=9, state="Pendiente"):
        return self.record(Ordenes, numero_orden=str(Ordenes.objects.count()+1), cliente=self.customer,
                           fecha=local(2026, month, day), total_venta=total, estado=state)

    def receipt(self, order, value, day=5, month=9):
        return Abonos.objects.create(orden=order, fecha=local(2026, month, day), valor=value)

    def result(self):
        return build_monthly_finance(self.period, as_of=self.as_of)

    def test_month_receipts_previous_sales_cancelled_and_partial_are_distinct(self):
        current = self.order()
        self.receipt(current, 400)
        previous = self.order(total=2000, month=8)
        self.receipt(previous, 500)
        self.order(total=500, state="Cancelada")
        self.order(total=99999, state="Cotización")
        paid = self.order(total=800, state="Entregada")
        self.receipt(paid, 800)
        result = self.result()
        self.assertEqual(result["registered"], 2300)
        self.assertEqual(result["cancelled_value"], 500)
        self.assertEqual(result["received"], 1700)
        self.assertEqual(result["received_current"], 1200)
        self.assertEqual(result["received_previous"], 500)
        self.assertEqual(result["pending"], 600)
        self.assertEqual(result["previous_pending"], 1500)
        self.assertEqual((result["partial_paid"], result["partial_pending"]), (400, 600))
        self.assertEqual([result["buckets"][k]["count"] for k in ("paid", "partial", "pending", "cancelled")], [1, 1, 0, 1])
        self.assertEqual(sum(r["current"]+r["previous"]+r["other"] for r in result["daily"]), result["received"])

    def test_delivery_and_cached_paid_fields_never_prove_receipt(self):
        order = self.order(state="Entregada")
        Ordenes.objects.filter(pk=order.pk).update(total_abonado=1000, saldo_pendiente=0)
        self.receipt(order, 1000, month=10)
        result = self.result()
        self.assertEqual(result["received"], 0)
        self.assertEqual(result["pending"], 1000)
        self.assertEqual(result["buckets"]["pending"]["count"], 1)
        self.assertEqual(result["overdue_count"], 1)

    def test_auto_cash_movement_is_not_added_to_receipt(self):
        order = self.order()
        payment = self.receipt(order, 400)
        self.record(MovimientosDinero, fecha=payment.fecha, tipo_movimiento="ENTRADA", categoria="ABONO",
                    descripcion="Pago", valor_pesos=400, orden=order, moneda="COP", referencia=f"AUTO-ABONO-{payment.pk}")
        self.assertEqual(self.result()["received"], 400)

    def test_exclusive_month_boundaries_and_zero_days(self):
        order = self.order(month=8)
        Abonos.objects.create(orden=order, fecha=self.period.start, valor=100)
        Abonos.objects.create(orden=order, fecha=self.period.end, valor=900)
        result = self.result()
        self.assertEqual(result["received"], 100)
        self.assertEqual(len(result["daily"]), 30)
        self.assertEqual(result["daily"][0]["previous"], 100)
        self.assertEqual(result["daily"][-1]["previous"], 0)

    def test_strict_ten_day_threshold_and_delivery_without_collection(self):
        self.order(day=20)  # 10 days at September close: not overdue.
        self.order(day=19)  # 11 days: overdue.
        paid_not_delivered = self.order(day=1, state="Pagada")
        self.receipt(paid_not_delivered, 1000)
        self.record(DetalleOrden, orden=paid_not_delivered, cantidad=2, cantidad_entregada=1,
                    descripcion_producto="Producto")
        self.order(day=1, state="Cancelada")
        result = self.result()
        self.assertEqual(result["overdue_count"], 2)
        self.assertEqual(result["overdue_balance"], 1000)
        overdue = [r for r in result["tracking"] if r["overdue"]]
        self.assertIn(0, [r["balance"] for r in overdue])

    def test_receipts_on_cancelled_orders_remain_cash_but_not_receivables(self):
        cancelled = self.order(state="Cancelada")
        self.receipt(cancelled, 200)
        result = self.result()
        self.assertEqual((result["received"], result["receipts_on_cancelled"], result["pending"]), (200, 200, 0))

    def test_current_month_excludes_future_dates(self):
        self.as_of = local(2026, 9, 15)
        order = self.order(day=1)
        self.receipt(order, 400, day=14)
        self.receipt(order, 600, day=16)
        self.order(day=20)
        result = self.result()
        self.assertEqual((result["received"], result["pending"], result["order_count"]), (400, 600, 1))
        self.assertEqual(len(result["daily"]), 15)

    def test_empty_and_future_period_have_no_invented_data(self):
        self.period = ReportMonth(2027, 1)
        result = self.result()
        self.assertEqual((result["registered"], result["received"], result["pending"]), (0, 0, 0))
        self.assertEqual(result["daily"], [])

    def context(self, months="2026-09"):
        request = RequestFactory().get("/reportes/", {"meses": months, "formato": "pdf"})
        request.user = type("User", (), {"is_authenticated": True})()
        with patch("gestion.views.build_full_report", return_value=BytesIO(b"pdf")) as render:
            response = reports_dashboard(request)
        response.close()
        context, orders = render.call_args.args
        return context, list(orders)

    def test_appendix_only_added_for_single_month_pdf(self):
        self.assertIn("monthly_finance", self.context()[0])
        self.assertNotIn("monthly_finance", self.context("")[0])
        self.assertNotIn("monthly_finance", self.context("2026-08,2026-09")[0])

    def test_report_uses_actual_receipts_to_calculate_paid_orders_and_balance(self):
        paid = self.order(total=1000, state="Entregada")
        self.receipt(paid, 1000)
        partial = self.order(total=1000)
        self.receipt(partial, 400)
        Ordenes.objects.filter(pk=paid.pk).update(total_abonado=0, saldo_pendiente=1000)
        Ordenes.objects.filter(pk=partial.pk).update(total_abonado=1000, saldo_pendiente=0)

        context, orders = self.context("")

        self.assertEqual(context["total_paid"], 1400)
        self.assertEqual(context["pending_balance"], 600)
        self.assertEqual(context["paid_orders_count"], 1)
        self.assertEqual(context["pending_orders_count"], 1)
        self.assertEqual(context["payment_chart"][0]["label"], "Pagadas")
        paid_report_order = next(order for order in orders if order.pk == paid.pk)
        self.assertEqual(paid_report_order.estado, "Entregada")
        self.assertEqual(paid_report_order.payment_status, "Pagada")
        self.assertEqual(paid_report_order.display_status, "Sin productos · Pagada")

    def test_orders_list_shows_paid_and_delivery_status_together(self):
        order = self.order(total=1000, state="Entregada")
        self.receipt(order, 1000)
        request = RequestFactory().get(
            "/gestion/ordenes/", {"periodo": "2026-09"}
        )
        request.user = type("User", (), {"is_authenticated": True})()

        with patch("gestion.views.render") as render:
            record_list(request, "ordenes")

        records = render.call_args.args[2]["records"]
        self.assertNotIn(order.pk, [item.pk for item in records])

    def test_bog_directory_uses_actual_receipts_for_order_payment_status(self):
        paid = self.order(total=1000, state="Entregada")
        self.receipt(paid, 1000)
        Ordenes.objects.filter(pk=paid.pk).update(total_abonado=0, saldo_pendiente=1000)
        detail = self.record(
            DetalleOrden, orden=paid, referencia_bog="BOG-PAGADO",
            descripcion_producto="Producto con BOG", cantidad=1,
        )
        request = RequestFactory().get("/bog/")
        request.user = type("User", (), {"is_authenticated": True})()

        with patch("gestion.views.render") as render:
            bog_list(request)

        context = render.call_args.args[2]
        self.assertEqual(context["paid_orders"], 1)
        self.assertEqual(context["due_orders"], 0)
        self.assertEqual(context["details"][0].pk, detail.pk)
        self.assertEqual(context["details"][0].order_paid, Decimal("1000"))

    def test_zero_invoice_is_not_automatically_paid(self):
        self.order(total=0, state="Entregada")
        context, orders = self.context("")
        self.assertEqual(context["paid_orders_count"], 0)
        self.assertEqual(context["pending_orders_count"], 1)
        self.assertEqual(orders[0].payment_status, "Sin valor de venta")

    def test_paid_list_uses_payment_month_and_keeps_delivery_separate(self):
        from .finance_views import paid_list
        order = self.order(month=8, state="Pagada")
        self.receipt(order, 400, month=8)
        self.receipt(order, 600, month=9)
        self.record(DetalleOrden, orden=order, descripcion_producto="Producto", cantidad=2, cantidad_entregada=1)
        request = RequestFactory().get("/pagadas/", {"periodo": "2026-09"})
        request.user = type("User", (), {"is_authenticated": True})()
        with patch("gestion.finance_views.render") as render:
            paid_list(request)
        rows = render.call_args.args[2]["orders"]
        self.assertEqual([row.pk for row in rows], [order.pk])
        self.assertEqual(rows[0].delivery_status, "Entrega parcial")
        self.assertEqual(timezone.localtime(rows[0].last_payment).month, 9)

    def test_financial_report_counts_cash_once_and_excludes_provisional_profit(self):
        from .finance_views import financial_report
        from .views import _refresh_order_balance
        confirmed = self.order(total=1000)
        provisional = self.order(total=1000)
        self.receipt(confirmed, 1000)
        self.receipt(provisional, 1000)
        _refresh_order_balance(confirmed)
        _refresh_order_balance(provisional)
        Ordenes.objects.filter(pk=confirmed.pk).update(costos_completos=True, ganancia_neta=300)
        Ordenes.objects.filter(pk=provisional.pk).update(ganancia_neta=1000)
        self.record(MovimientosDinero, fecha=local(2026,9,7), tipo_movimiento="SALIDA", categoria="MOVIMIENTO MANUAL", descripcion="Gasto", valor_pesos=50, moneda="COP")
        request = RequestFactory().get("/reporte-financiero/", {"periodo": "2026-09"})
        request.user = type("User", (), {"is_authenticated": True})()
        with patch("gestion.finance_views.render") as render:
            financial_report(request)
        context = render.call_args.args[2]
        self.assertEqual(context["incoming"], 2000)
        self.assertEqual(context["confirmed_profit"], 300)
        self.assertEqual(context["result"], 250)
        self.assertEqual(context["provisional"], 1)
        charts = context["financial_charts"]
        self.assertEqual(sum(charts["daily_in"]), context["incoming"])
        self.assertEqual(sum(charts["daily_out"]), context["outgoing"])
        self.assertEqual(len(charts["daily_in"]), 30)
        self.assertEqual(charts["cash"], [2000, 50, 1950])
        self.assertEqual(charts["profit"], [300, 50, 250])
        self.assertEqual((charts["confirmed"], charts["provisional"]), (1, 1))

    def test_movement_receipt_updates_order_once_and_rejects_overpayment(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .views import record_form
        order = self.order(total=1000)
        def submit(value):
            request = RequestFactory().post("/gestion/movimientos/nuevo/", {
                "fecha": "2026-09-05T12:00", "tipo_movimiento": "ENTRADA", "orden": order.pk,
                "valor_pesos": value, "descripcion": "Pago del cliente", "metodo_pago": "Transferencia",
            })
            request.user = type("User", (), {"is_authenticated": True})()
            request.session = {}
            request._messages = FallbackStorage(request)
            return record_form(request, "movimientos")
        self.assertEqual(submit(400).status_code, 302)
        order.refresh_from_db()
        self.assertEqual((order.total_abonado, order.saldo_pendiente), (400, 600))
        self.assertEqual(Abonos.objects.filter(orden=order).count(), 1)
        self.assertEqual(MovimientosDinero.objects.filter(orden=order).count(), 1)
        self.assertEqual(submit(700).status_code, 200)
        self.assertEqual(Abonos.objects.filter(orden=order).count(), 1)
        self.assertEqual(MovimientosDinero.objects.filter(orden=order).count(), 1)
        self.assertEqual(submit(600).status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.saldo_pendiente, 0)

    def test_new_pages_render_and_legacy_receipts_count_without_movements(self):
        from .finance_views import financial_report, paid_list
        from .views import order_preview
        order = self.order()
        self.receipt(order, 1000)
        request = RequestFactory().get("/", {"periodo": "2026-09", "historial": "1"})
        request.user = type("User", (), {"is_authenticated": True})()
        self.assertEqual(paid_list(request).status_code, 200)
        self.assertEqual(financial_report(request).status_code, 200)
        self.assertEqual(order_preview(request, order.pk).status_code, 200)
        with patch("gestion.finance_views.render") as render:
            financial_report(request)
        self.assertEqual(render.call_args.args[2]["incoming"], 1000)
        invalid = RequestFactory().get("/", {"periodo": "2026-13"})
        invalid.user = request.user
        self.assertEqual(paid_list(invalid).status_code, 200)

    def test_exactly_one_new_page_and_all_original_drawing_commands_unchanged(self):
        # Exercise real ReportLab pagination, including a long orders appendix.
        for i in range(35):
            self.order(day=1, state="Cancelada" if i % 5 == 0 else "Pendiente")
        context, orders = self.context()
        original = {k: v for k, v in context.items() if k != "monthly_finance"}

        def render_pages(data):
            pages = []

            class RecordingCanvas(Canvas):
                def showPage(self):
                    pages.append(tuple(self._code))
                    super().showPage()

            class RecordingDoc(SimpleDocTemplate):
                def build(self, *args, **kwargs):
                    kwargs["canvasmaker"] = RecordingCanvas
                    return super().build(*args, **kwargs)

            with patch("gestion.executive_pdf.SimpleDocTemplate", RecordingDoc):
                build_executive_report(data, orders)
            return pages

        before, after = render_pages(original), render_pages(context)
        self.assertEqual(len(after), len(before)+1)
        self.assertEqual(after[:-1], before)
        self.assertTrue(any("Control financiero" in code for code in after[-1]))

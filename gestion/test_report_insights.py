from django.test import SimpleTestCase
from .report_insights import build_monthly_insights


class MonthlyInsightsTests(SimpleTestCase):
    def data(self, **overrides):
        return dict({"is_monthly": True, "has_comparison": True,
                     "total_sales": 1000, "pending_balance": 0, "cash_balance": 100,
                     "active_clients": 10, "previous_active_clients": 10,
                     "orders_count": 12, "payments_total": 500,
                     "sales_variation": {"value": 14, "icon": "arrow-down"}}, **overrides)

    def test_high_priority_problems_displace_lower_findings(self):
        result = build_monthly_insights(self.data(cash_balance=-50, pending_balance=500,
                                                 exhausted_with_demand=2, pending_delivery_orders=3))
        self.assertEqual([r["code"] for r in result],
                         ["negative_cash", "receivables", "exhausted_demand", "pending_deliveries"])
        self.assertTrue(all(r["priority"] == "HIGH" for r in result))
        self.assertIn("50,0%", result[1]["text"])
        self.assertIn("actualmente", result[2]["text"])

    def test_sales_direction_and_zero_baseline(self):
        for icon, word in (("arrow-up", "aumentaron"), ("arrow-down", "disminuyeron")):
            result = build_monthly_insights(self.data(sales_variation={"value": 14, "icon": icon}))
            self.assertIn(f"{word} 14,0%", result[0]["text"])
        result = build_monthly_insights(self.data(sales_variation={"value": None}))
        self.assertIn("no hay base", result[0]["text"])

    def test_concentration_uses_complete_detail_sales_not_order_sales(self):
        result = build_monthly_insights(self.data(total_sales=100, detail_sales_total=1000,
            top_products=[{"categoria_reporte": "FAROLAS", "sales": 400}],
            brands=[{"marca_reporte": "FORD", "sales": 500}]))
        texts = {r["code"]: r["text"] for r in result}
        self.assertIn("40,0%", texts["category_share"])
        self.assertIn("50,0%", texts["brand_share"])
        self.assertIn("antes de descuentos", texts["brand_share"])

    def test_client_growth_and_no_duplicate_client_sentence(self):
        result = build_monthly_insights(self.data(previous_active_clients=5))
        self.assertIn("100,0%", next(r["text"] for r in result if r["code"] == "client_growth"))
        self.assertNotIn("clients", [r["code"] for r in result])

    def test_missing_data_is_not_invented(self):
        self.assertEqual(build_monthly_insights({}), [])
        result = build_monthly_insights(self.data(total_sales=0, pending_balance=0, payments_total=0,
                                                 active_clients=0, orders_count=0, sales_variation={"value": None}))
        self.assertLessEqual(len(result), 5)
        self.assertGreaterEqual(len(result), 3)
        self.assertFalse(any("porque" in r["text"] for r in result))

    def test_thresholds_and_deterministic_selection(self):
        data = self.data(pending_balance=299, detail_sales_total=1000,
                         brands=[{"marca_reporte": "FORD", "sales": 299}])
        result = build_monthly_insights(data)
        self.assertEqual(result, build_monthly_insights(data))
        self.assertEqual(next(r["priority"] for r in result if r["code"] == "receivables"), "MEDIUM")
        self.assertNotIn("brand_share", [r["code"] for r in result])

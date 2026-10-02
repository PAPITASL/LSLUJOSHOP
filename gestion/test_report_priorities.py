from django.test import SimpleTestCase
from .report_priorities import build_next_month_priorities


class NextMonthPriorityTests(SimpleTestCase):
    def test_limit_order_and_required_structure(self):
        data = {"total_sales": 1000, "pending_balance": 500, "exhausted_with_demand": 2,
                "pending_delivery_orders": 8, "cash_balance": -100, "detail_sales_total": 1000,
                "priority_categories": [{"categoria_reporte": "OTROS", "sales": 200}],
                "has_comparison": True, "sales_variation": {"value": 20, "icon": "arrow-down"},
                "recurring_clients": 1, "previous_recurring_clients": 3}
        result = build_next_month_priorities(data)
        self.assertEqual(len(result), 5)
        self.assertEqual([r["code"] for r in result],
                         ["receivables", "restocking_review", "deliveries", "cash_review", "classification"])
        for row in result:
            self.assertTrue({"priority", "area", "reason", "action"}.issubset(row))
            self.assertIn(row["priority"], {"high", "medium", "low"})
        self.assertEqual(result, build_next_month_priorities(data))

    def test_thresholds_are_strict_and_no_filler(self):
        self.assertEqual(build_next_month_priorities({}), [])
        self.assertEqual(build_next_month_priorities({"total_sales": 1000, "pending_balance": 300,
            "pending_delivery_orders": 4, "detail_sales_total": 1000,
            "priority_categories": [{"categoria_reporte": "OTROS", "sales": 100}]}), [])
        result = build_next_month_priorities({"total_sales": 1000, "pending_balance": 301})
        self.assertEqual(len(result), 1)
        self.assertIn("pagos posteriores", result[0]["action"])

    def test_stock_without_demand_never_triggers_restocking(self):
        self.assertEqual(build_next_month_priorities({"exhausted_count": 100, "exhausted_with_demand": 0}), [])
        result = build_next_month_priorities({"exhausted_with_demand": 2})
        self.assertIn("Revisar", result[0]["action"])
        self.assertNotIn("Comprar", result[0]["action"])

    def test_growth_requires_positive_baseline_and_material_share(self):
        data = {"has_comparison": True, "detail_sales_total": 1000,
                "priority_categories": [{"categoria_reporte": "FAROLAS", "sales": 400}],
                "previous_priority_categories": [{"categoria_reporte": "FAROLAS", "sales": 200}]}
        result = build_next_month_priorities(data)
        self.assertEqual(result[0]["code"], "category_growth")
        self.assertIn("100,0%", result[0]["reason"])
        data["previous_priority_categories"][0]["sales"] = 0
        self.assertEqual(build_next_month_priorities(data), [])

    def test_recurring_decline_and_sales_decline_do_not_assert_causes(self):
        result = build_next_month_priorities({"has_comparison": True, "is_monthly": True,
            "previous_recurring_clients": 10, "recurring_clients": 8,
            "sales_variation": {"value": 14, "icon": "arrow-down"}})
        self.assertEqual([r["code"] for r in result], ["sales_decline", "repeat_customers"])
        self.assertIn("20,0%", result[1]["reason"])
        self.assertTrue(all("porque" not in r["reason"] for r in result))

    def test_missing_marketing_data_never_produces_advice(self):
        self.assertEqual(build_next_month_priorities({"brands": [{"sales": 10000}],
                                                     "active_clients": 10}), [])

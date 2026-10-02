from datetime import timedelta

from django.test import SimpleTestCase

from .report_periods import ReportMonth


class MonthlyPeriodTests(SimpleTestCase):
    def test_calendar_months_and_previous_period(self):
        cases = [
            (2026, 9, 30, (2026, 8)), (2026, 10, 31, (2026, 9)),
            (2026, 11, 30, (2026, 10)), (2026, 12, 31, (2026, 11)),
            (2027, 1, 31, (2026, 12)), (2027, 2, 28, (2027, 1)),
            (2028, 2, 29, (2028, 1)), (2100, 2, 28, (2100, 1)),
        ]
        for year, month, days, previous in cases:
            with self.subTest(year=year, month=month):
                period = ReportMonth(year, month)
                self.assertEqual((period.end - period.start).days, days)
                self.assertEqual((period.previous.year, period.previous.month), previous)
                self.assertEqual(period.previous.end, period.start)
                self.assertEqual((period.start.day, period.start.hour, period.end.day, period.end.hour), (1, 0, 1, 0))
                self.assertEqual(period.start.utcoffset(), timedelta(hours=-5))

    def test_dynamic_spanish_metadata(self):
        period = ReportMonth(2027, 1)
        self.assertEqual(period.label, "Enero 2027")
        self.assertEqual(period.previous.label, "Diciembre 2026")
        self.assertEqual(period.date_range, "01/01/2027 – 31/01/2027")

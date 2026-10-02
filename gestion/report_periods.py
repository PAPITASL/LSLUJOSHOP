"""Calendar periods for reports, using inclusive starts and exclusive ends."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone, translation
from django.utils.formats import date_format


@dataclass(frozen=True)
class ReportMonth:
    year: int
    month: int

    @property
    def start(self):
        return timezone.make_aware(datetime(self.year, self.month, 1), timezone.get_default_timezone())

    @property
    def end(self):
        year, month = (self.year + 1, 1) if self.month == 12 else (self.year, self.month + 1)
        return timezone.make_aware(datetime(year, month, 1), timezone.get_default_timezone())

    @property
    def previous(self):
        return ReportMonth(self.year - 1, 12) if self.month == 1 else ReportMonth(self.year, self.month - 1)

    @property
    def label(self):
        with translation.override("es"):
            return date_format(self.start, "F Y").capitalize()

    @property
    def date_range(self):
        return f"{self.start:%d/%m/%Y} – {self.end - timedelta(days=1):%d/%m/%Y}"


def period_query(field, periods):
    query = Q()
    for year, month in periods:
        period = ReportMonth(year, month)
        query |= Q(**{f"{field}__gte": period.start, f"{field}__lt": period.end})
    return query

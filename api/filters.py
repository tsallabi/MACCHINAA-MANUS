"""MACCHINAA-EVOLVED — API Filters"""
import django_filters
from core.models import AuctionVehicle


class VehicleFilter(django_filters.FilterSet):
    source = django_filters.CharFilter(field_name="source_auction", lookup_expr="iexact")
    make = django_filters.CharFilter(lookup_expr="icontains")
    model = django_filters.CharFilter(lookup_expr="icontains")
    year_min = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_max = django_filters.NumberFilter(field_name="year", lookup_expr="lte")
    max_price = django_filters.NumberFilter(field_name="normalized_price_usd", lookup_expr="lte")
    min_price = django_filters.NumberFilter(field_name="normalized_price_usd", lookup_expr="gte")
    min_quality = django_filters.NumberFilter(field_name="quality_score", lookup_expr="gte")

    class Meta:
        model = AuctionVehicle
        fields = [
            "source_auction", "source_country", "make", "model",
            "year", "title_type", "status", "has_keys", "runs_drives",
            "fuel_type", "drive_type",
        ]

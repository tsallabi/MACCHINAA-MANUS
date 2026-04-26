"""
MACCHINAA-EVOLVED — API Views
================================
REST API endpoints for MACCHINAA-EVOLVED platform.

Endpoints:
  GET  /api/v1/vehicles/              — قائمة السيارات مع فلترة متقدمة
  GET  /api/v1/vehicles/{id}/         — تفاصيل سيارة
  GET  /api/v1/vehicles/{id}/import-cost/ — حساب تكلفة الاستيراد
  GET  /api/v1/stats/                 — إحصائيات المنصة
  GET  /api/v1/makes/                 — قائمة الماركات المتاحة
  POST /api/v1/sync/trigger/          — تشغيل مزامنة يدوية
  GET  /api/v1/sync-runs/             — سجل عمليات المزامنة
  CRUD /api/v1/alerts/                — تنبيهات الأسعار
"""
from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from django.db.models import Avg, Count, Max, Min, Q
from django.utils import timezone
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import AuctionVehicle, AuctionSource, PriceAlert, SyncRun
from .serializers import (
    AuctionVehicleSerializer,
    AuctionVehicleDetailSerializer,
    PriceAlertSerializer,
    SyncRunSerializer,
)
from .filters import VehicleFilter

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
#  VEHICLE VIEWSET
# ══════════════════════════════════════════════════════════════════════════

class VehicleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    قائمة وتفاصيل السيارات من كل المزادات.

    الفلاتر المتاحة:
      ?source=COPART,IAAI,BCA,JAPAN,GOVDEALS,MANHEIM,ADESA
      ?make=Toyota&model=Camry
      ?year_min=2018&year_max=2023
      ?title_type=clean,salvage
      ?max_price=5000
      ?min_quality=70
      ?status=active
      ?search=Toyota Land Cruiser
      ?ordering=-quality_score,-normalized_price_usd
    """
    queryset = (
        AuctionVehicle.objects
        .filter(is_deleted=False)
        .select_related()
        .order_by("-first_seen_at")
    )
    permission_classes = [permissions.AllowAny]
    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    search_fields = ["make", "model", "trim", "vin", "lot_number", "damage_primary"]
    ordering_fields = [
        "normalized_price_usd", "quality_score", "year",
        "odometer_km", "auction_date", "first_seen_at",
    ]
    ordering = ["-first_seen_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AuctionVehicleDetailSerializer
        return AuctionVehicleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        # Source filter
        sources = params.get("source")
        if sources:
            source_list = [s.strip().upper() for s in sources.split(",")]
            qs = qs.filter(source_auction__in=source_list)

        # Make/Model filter
        make = params.get("make")
        if make:
            qs = qs.filter(make__icontains=make)

        model = params.get("model")
        if model:
            qs = qs.filter(model__icontains=model)

        # Year range
        year_min = params.get("year_min")
        if year_min:
            qs = qs.filter(year__gte=int(year_min))

        year_max = params.get("year_max")
        if year_max:
            qs = qs.filter(year__lte=int(year_max))

        # Price range
        max_price = params.get("max_price")
        if max_price:
            qs = qs.filter(normalized_price_usd__lte=float(max_price))

        min_price = params.get("min_price")
        if min_price:
            qs = qs.filter(normalized_price_usd__gte=float(min_price))

        # Title type
        title_types = params.get("title_type")
        if title_types:
            tt_list = [t.strip() for t in title_types.split(",")]
            qs = qs.filter(title_type__in=tt_list)

        # Quality score
        min_quality = params.get("min_quality")
        if min_quality:
            qs = qs.filter(quality_score__gte=int(min_quality))

        # Status
        status_filter = params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Country
        country = params.get("country")
        if country:
            qs = qs.filter(source_country__iexact=country)

        # Runs & drives
        runs = params.get("runs_drives")
        if runs is not None:
            qs = qs.filter(runs_drives=(runs.lower() in ("true", "1", "yes")))

        # Has keys
        keys = params.get("has_keys")
        if keys is not None:
            qs = qs.filter(has_keys=(keys.lower() in ("true", "1", "yes")))

        return qs

    @action(detail=True, methods=["get"])
    def import_cost(self, request, pk=None):
        """Calculate full import cost to Libya for a specific vehicle."""
        vehicle = self.get_object()
        port = request.query_params.get("port", "misrata")
        include_customs = request.query_params.get("customs", "true").lower() != "false"

        breakdown = vehicle.calculate_import_cost(
            destination_port=port,
            include_customs=include_customs,
        )
        vehicle.save(update_fields=["import_cost_estimate", "import_cost_breakdown"])

        return Response({
            "vehicle_id": vehicle.id,
            "vehicle": f"{vehicle.year} {vehicle.make} {vehicle.model}",
            "auction_source": vehicle.source_auction,
            "breakdown": breakdown,
        })

    @action(detail=False, methods=["get"])
    def hot_deals(self, request):
        """Return top 20 best value vehicles (high quality, low price)."""
        qs = (
            self.get_queryset()
            .filter(
                quality_score__gte=60,
                normalized_price_usd__gt=0,
                normalized_price_usd__lte=10000,
                status="active",
            )
            .order_by("-quality_score", "normalized_price_usd")[:20]
        )
        serializer = AuctionVehicleSerializer(qs, many=True)
        return Response(serializer.data)


# ══════════════════════════════════════════════════════════════════════════
#  IMPORT COST VIEW
# ══════════════════════════════════════════════════════════════════════════

class ImportCostView(APIView):
    """Calculate import cost for a vehicle to Libya."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        try:
            vehicle = AuctionVehicle.objects.get(pk=pk, is_deleted=False)
        except AuctionVehicle.DoesNotExist:
            return Response({"error": "السيارة غير موجودة"}, status=404)

        port = request.query_params.get("port", "misrata")
        include_customs = request.query_params.get("customs", "true").lower() != "false"

        breakdown = vehicle.calculate_import_cost(
            destination_port=port,
            include_customs=include_customs,
        )
        vehicle.save(update_fields=["import_cost_estimate", "import_cost_breakdown"])

        return Response({
            "vehicle_id": vehicle.id,
            "vehicle": f"{vehicle.year} {vehicle.make} {vehicle.model}",
            "lot_number": vehicle.lot_number,
            "source": vehicle.source_auction,
            "breakdown": breakdown,
        })


# ══════════════════════════════════════════════════════════════════════════
#  SYNC VIEWS
# ══════════════════════════════════════════════════════════════════════════

class SyncRunViewSet(viewsets.ReadOnlyModelViewSet):
    """سجل عمليات المزامنة."""
    queryset = SyncRun.objects.all().order_by("-started_at")
    serializer_class = SyncRunSerializer
    permission_classes = [permissions.IsAdminUser]


class TriggerSyncView(APIView):
    """تشغيل مزامنة يدوية من API."""
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        source = request.data.get("source", "copart")
        make = request.data.get("make")
        max_pages = int(request.data.get("max_pages", 5))

        if source not in ["copart", "iaai", "bca", "japan", "govdeals", "manheim", "adesa", "all"]:
            return Response(
                {"error": f"مصدر غير معروف: {source}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build command
        cmd = [sys.executable, "manage.py", "sync_auction", f"--source={source}",
               f"--max-pages={max_pages}"]
        if make:
            cmd.append(f"--make={make}")

        try:
            # Run in background
            subprocess.Popen(cmd, cwd="/app")
            return Response({
                "message": f"تم تشغيل مزامنة {source.upper()} في الخلفية",
                "source": source,
                "make": make,
                "max_pages": max_pages,
            })
        except Exception as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# ══════════════════════════════════════════════════════════════════════════
#  STATS VIEW
# ══════════════════════════════════════════════════════════════════════════

class StatsView(APIView):
    """إحصائيات المنصة الشاملة."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = AuctionVehicle.objects.filter(is_deleted=False)

        # Overall stats
        total = qs.count()
        active = qs.filter(status="active").count()

        # By source
        by_source = list(
            qs.values("source_auction")
            .annotate(count=Count("id"), avg_price=Avg("normalized_price_usd"))
            .order_by("-count")
        )

        # Price stats
        price_stats = qs.filter(normalized_price_usd__gt=0).aggregate(
            avg=Avg("normalized_price_usd"),
            min=Min("normalized_price_usd"),
            max=Max("normalized_price_usd"),
        )

        # Top makes
        top_makes = list(
            qs.values("make")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        # Quality distribution
        quality_dist = {
            "excellent": qs.filter(quality_score__gte=80).count(),
            "good": qs.filter(quality_score__gte=60, quality_score__lt=80).count(),
            "fair": qs.filter(quality_score__gte=40, quality_score__lt=60).count(),
            "poor": qs.filter(quality_score__lt=40).count(),
        }

        # Recent sync runs
        recent_syncs = list(
            SyncRun.objects.order_by("-started_at")[:5]
            .values("source", "status", "vehicles_created", "vehicles_updated", "started_at")
        )

        return Response({
            "total_vehicles": total,
            "active_vehicles": active,
            "by_source": by_source,
            "price_stats_usd": price_stats,
            "top_makes": top_makes,
            "quality_distribution": quality_dist,
            "recent_syncs": recent_syncs,
            "last_updated": timezone.now().isoformat(),
        })


# ══════════════════════════════════════════════════════════════════════════
#  MAKES LIST VIEW
# ══════════════════════════════════════════════════════════════════════════

class MakesListView(APIView):
    """قائمة الماركات المتاحة مع عدد السيارات."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        makes = list(
            AuctionVehicle.objects
            .filter(is_deleted=False, make__gt="")
            .values("make")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(makes)


# ══════════════════════════════════════════════════════════════════════════
#  PRICE ALERT VIEWSET
# ══════════════════════════════════════════════════════════════════════════

class PriceAlertViewSet(viewsets.ModelViewSet):
    """إدارة تنبيهات الأسعار."""
    serializer_class = PriceAlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

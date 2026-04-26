"""MACCHINAA-EVOLVED — Dashboard Views"""
from django.db.models import Avg, Count, Max, Min, Q
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView, TemplateView

from core.models import AuctionVehicle, AuctionSource, SyncRun


class HomeView(TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = AuctionVehicle.objects.filter(is_deleted=False, status="active")
        ctx["total_vehicles"] = qs.count()
        ctx["by_source"] = list(
            qs.values("source_auction")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        ctx["recent_vehicles"] = qs.order_by("-first_seen_at")[:12]
        ctx["hot_deals"] = (
            qs.filter(quality_score__gte=70, normalized_price_usd__lte=8000)
            .order_by("-quality_score", "normalized_price_usd")[:6]
        )
        ctx["recent_syncs"] = SyncRun.objects.order_by("-started_at")[:5]
        return ctx


class DashboardView(TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = AuctionVehicle.objects.filter(is_deleted=False)

        ctx["stats"] = {
            "total": qs.count(),
            "active": qs.filter(status="active").count(),
            "avg_price": qs.filter(normalized_price_usd__gt=0).aggregate(
                avg=Avg("normalized_price_usd")
            )["avg"],
            "by_source": list(
                qs.values("source_auction")
                .annotate(count=Count("id"), avg_price=Avg("normalized_price_usd"))
                .order_by("-count")
            ),
            "by_title": list(
                qs.values("title_type")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
            "top_makes": list(
                qs.values("make")
                .annotate(count=Count("id"))
                .order_by("-count")[:10]
            ),
        }
        ctx["recent_syncs"] = SyncRun.objects.order_by("-started_at")[:10]
        return ctx


class VehicleListView(ListView):
    model = AuctionVehicle
    template_name = "dashboard/vehicle_list.html"
    context_object_name = "vehicles"
    paginate_by = 24

    def get_queryset(self):
        qs = AuctionVehicle.objects.filter(is_deleted=False)
        params = self.request.GET

        if params.get("source"):
            qs = qs.filter(source_auction=params["source"].upper())
        if params.get("make"):
            qs = qs.filter(make__icontains=params["make"])
        if params.get("model"):
            qs = qs.filter(model__icontains=params["model"])
        if params.get("title_type"):
            qs = qs.filter(title_type=params["title_type"])
        if params.get("max_price"):
            qs = qs.filter(normalized_price_usd__lte=float(params["max_price"]))
        if params.get("q"):
            q = params["q"]
            qs = qs.filter(
                Q(make__icontains=q) | Q(model__icontains=q) |
                Q(vin__icontains=q) | Q(lot_number__icontains=q)
            )

        sort = params.get("sort", "-first_seen_at")
        return qs.order_by(sort)


class VehicleDetailView(DetailView):
    model = AuctionVehicle
    template_name = "dashboard/vehicle_detail.html"
    context_object_name = "vehicle"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vehicle = self.object
        ctx["import_cost"] = vehicle.calculate_import_cost()
        ctx["similar_vehicles"] = (
            AuctionVehicle.objects
            .filter(
                make=vehicle.make,
                model=vehicle.model,
                is_deleted=False,
            )
            .exclude(pk=vehicle.pk)
            .order_by("-quality_score")[:6]
        )
        return ctx


class SyncDashboardView(TemplateView):
    template_name = "dashboard/sync_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sync_runs"] = SyncRun.objects.order_by("-started_at")[:20]
        ctx["sources"] = [
            {"id": "copart",   "name": "Copart (USA)",        "flag": "🇺🇸"},
            {"id": "iaai",     "name": "IAAI (USA)",           "flag": "🇺🇸"},
            {"id": "manheim",  "name": "Manheim (USA)",        "flag": "🇺🇸"},
            {"id": "adesa",    "name": "ADESA/OpenLane (USA)", "flag": "🇺🇸"},
            {"id": "govdeals", "name": "GovDeals/GSA (USA)",   "flag": "🇺🇸"},
            {"id": "bca",      "name": "BCA Europe",           "flag": "🇪🇺"},
            {"id": "japan",    "name": "Japan Auctions",       "flag": "🇯🇵"},
        ]
        return ctx


class CalculatorView(TemplateView):
    template_name = "dashboard/calculator.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.conf import settings
        ctx["ports"] = settings.LIBYAN_PORTS
        ctx["customs_rate"] = settings.LIBYAN_CUSTOMS_RATE
        return ctx

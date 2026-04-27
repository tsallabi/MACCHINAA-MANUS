"""
dashboard/views.py — MACCHINAA-EVOLVED Dashboard Views
"""
from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Count, Q

from core.models import AuctionVehicle


def home(request):
    """الصفحة الرئيسية — عرض السيارات مع فلاتر."""
    qs = AuctionVehicle.objects.filter(is_deleted=False)

    # ── فلاتر البحث ──────────────────────────────────────────────────────────
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(make__icontains=q) |
            Q(model__icontains=q) |
            Q(vin__icontains=q) |
            Q(trim__icontains=q) |
            Q(lot_number__icontains=q)
        )

    source = request.GET.get("source", "").strip().upper()
    if source:
        qs = qs.filter(sync_source=source)

    make = request.GET.get("make", "").strip()
    if make:
        qs = qs.filter(make__icontains=make)

    max_price = request.GET.get("max_price", "").strip()
    if max_price:
        try:
            qs = qs.filter(current_bid__lte=float(max_price))
        except ValueError:
            pass

    # ── الترتيب ──────────────────────────────────────────────────────────────
    sort = request.GET.get("sort", "-last_synced_at")
    valid_sorts = [
        "current_bid", "-current_bid",
        "-year", "year",
        "-last_synced_at", "last_synced_at",
    ]
    if sort not in valid_sorts:
        sort = "-last_synced_at"
    qs = qs.order_by(sort)

    # ── الإحصائيات ───────────────────────────────────────────────────────────
    source_stats = (
        AuctionVehicle.objects
        .filter(is_deleted=False)
        .values("sync_source")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    total_count = AuctionVehicle.objects.filter(is_deleted=False).count()

    last_obj = (
        AuctionVehicle.objects
        .filter(is_deleted=False)
        .order_by("-last_synced_at")
        .first()
    )
    last_sync = (
        last_obj.last_synced_at.strftime("%Y-%m-%d %H:%M")
        if last_obj and last_obj.last_synced_at else None
    )

    # ── Pagination ───────────────────────────────────────────────────────────
    paginator = Paginator(qs, 60)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(request, "dashboard/home.html", {
        "page_obj":     page_obj,
        "source_stats": source_stats,
        "total_count":  total_count,
        "last_sync":    last_sync,
    })

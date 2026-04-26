"""MACCHINAA-EVOLVED — Django Admin Configuration"""
from django.contrib import admin
from django.utils.html import format_html
from .models import AuctionVehicle, SyncRun, PriceAlert


@admin.register(AuctionVehicle)
class AuctionVehicleAdmin(admin.ModelAdmin):
    list_display = [
        "thumbnail_preview", "year", "make", "model", "trim",
        "source_auction", "title_type", "quality_badge",
        "price_usd", "odometer_km", "status", "last_synced_at",
    ]
    list_filter = [
        "source_auction", "title_type", "status",
        "has_keys", "runs_drives", "fuel_type",
        "source_country",
    ]
    search_fields = ["make", "model", "vin", "lot_number", "location_city"]
    readonly_fields = [
        "lot_number", "dedup_key", "quality_score",
        "normalized_price_usd", "odometer_km",
        "import_cost_estimate", "import_cost_breakdown",
        "first_seen_at", "last_synced_at",
    ]
    ordering = ["-first_seen_at"]
    list_per_page = 50

    fieldsets = (
        ("الهوية", {
            "fields": ("lot_number", "vin", "dedup_key", "source_auction",
                       "source_country", "source_url")
        }),
        ("معلومات السيارة", {
            "fields": ("year", "make", "model", "trim", "body_style",
                       "color", "interior_color")
        }),
        ("المحرك", {
            "fields": ("engine", "cylinders", "fuel_type", "transmission", "drive_type")
        }),
        ("الحالة", {
            "fields": ("odometer", "odometer_unit", "odometer_km",
                       "title_type", "damage_primary", "damage_secondary",
                       "has_keys", "runs_drives", "auction_grade",
                       "quality_score")
        }),
        ("التسعير", {
            "fields": ("current_bid", "buy_now_price", "estimated_retail_value",
                       "currency", "normalized_price_usd",
                       "import_cost_estimate", "import_cost_breakdown")
        }),
        ("الموقع والمزاد", {
            "fields": ("location_city", "location_state", "location_country",
                       "auction_date", "status", "bid_count")
        }),
        ("الوسائط", {
            "fields": ("primary_image", "images_json", "has_360_view"),
            "classes": ("collapse",),
        }),
        ("المزامنة", {
            "fields": ("first_seen_at", "last_synced_at", "sync_source", "is_deleted"),
        }),
    )

    def thumbnail_preview(self, obj):
        if obj.primary_image:
            return format_html(
                '<img src="{}" style="height:50px;border-radius:4px;" />',
                obj.primary_image,
            )
        return "—"
    thumbnail_preview.short_description = "صورة"

    def quality_badge(self, obj):
        score = obj.quality_score or 0
        if score >= 80:
            color = "#27ae60"
            label = f"ممتاز ({score})"
        elif score >= 60:
            color = "#f39c12"
            label = f"جيد ({score})"
        elif score >= 40:
            color = "#e67e22"
            label = f"متوسط ({score})"
        else:
            color = "#e74c3c"
            label = f"ضعيف ({score})"
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;'
            'border-radius:12px;font-size:11px;">{}</span>',
            color, label,
        )
    quality_badge.short_description = "الجودة"

    def price_usd(self, obj):
        if obj.normalized_price_usd:
            return f"${obj.normalized_price_usd:,.0f}"
        return "—"
    price_usd.short_description = "السعر (USD)"


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = [
        "source", "status", "vehicles_created", "vehicles_updated",
        "errors_count", "pages_fetched", "started_at", "duration_display",
    ]
    list_filter = ["source", "status"]
    readonly_fields = [f.name for f in SyncRun._meta.get_fields() if hasattr(f, 'name')]
    ordering = ["-started_at"]

    def duration_display(self, obj):
        d = obj.duration_seconds
        if d is None:
            return "جارٍ..."
        return f"{d:.0f}s"
    duration_display.short_description = "المدة"


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = [
        "user", "make", "model", "max_price_usd",
        "is_active", "trigger_count", "last_triggered_at",
    ]
    list_filter = ["is_active", "notify_whatsapp", "notify_email"]
    search_fields = ["user__username", "make", "model"]

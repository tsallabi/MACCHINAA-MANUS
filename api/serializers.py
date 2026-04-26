"""MACCHINAA-EVOLVED — API Serializers"""
from rest_framework import serializers
from core.models import AuctionVehicle, PriceAlert, SyncRun


class AuctionVehicleSerializer(serializers.ModelSerializer):
    """Compact serializer for list views."""

    class Meta:
        model = AuctionVehicle
        fields = [
            "id", "lot_number", "vin",
            "source_auction", "source_country", "source_url",
            "year", "make", "model", "trim", "body_style", "color",
            "fuel_type", "transmission", "drive_type",
            "odometer_km", "title_type",
            "damage_primary", "has_keys", "runs_drives",
            "quality_score",
            "current_bid", "currency", "normalized_price_usd",
            "import_cost_estimate",
            "status", "auction_date",
            "location_city", "location_state",
            "primary_image",
            "first_seen_at", "last_synced_at",
        ]
        read_only_fields = fields


class AuctionVehicleDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views — includes all fields."""
    import_cost_breakdown = serializers.JSONField()
    images_json = serializers.JSONField()

    class Meta:
        model = AuctionVehicle
        exclude = ["raw_data", "is_deleted"]
        read_only_fields = [f.name for f in AuctionVehicle._meta.get_fields()
                            if hasattr(f, 'name')]


class SyncRunSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = SyncRun
        fields = "__all__"

    def get_duration_seconds(self, obj):
        return obj.duration_seconds


class PriceAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAlert
        exclude = ["user"]
        read_only_fields = ["created_at", "last_triggered_at", "trigger_count"]

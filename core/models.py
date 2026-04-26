"""
MACCHINAA-EVOLVED — Core Models
=================================
نموذج موحّد لجميع السيارات من كل المزادات العالمية.

التحسينات الرئيسية على النسخة الأصلية:
  1. حقل source_auction واضح لكل مصدر
  2. normalized_price_usd — تحويل تلقائي لكل العملات
  3. quality_score — تقييم جودة السيارة (0-100)
  4. import_cost_estimate — تقدير تكلفة الاستيراد الكاملة
  5. dedup_key — مفتاح إزالة التكرار بالـ VIN
  6. sync_metadata — تتبع آخر مزامنة لكل سيارة
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════
#  CHOICES
# ══════════════════════════════════════════════════════════════════════════

class AuctionSource(models.TextChoices):
    COPART   = "COPART",   "Copart (USA)"
    IAAI     = "IAAI",     "IAAI (USA)"
    MANHEIM  = "MANHEIM",  "Manheim (USA)"
    ADESA    = "ADESA",    "ADESA/OpenLane (USA)"
    ACV      = "ACV",      "ACV Auctions (USA)"
    BCA      = "BCA",      "BCA Europe"
    JAPAN    = "JAPAN",    "Japan Auctions (USS/JAA)"
    GOVDEALS = "GOVDEALS", "GovDeals/GSA (USA)"
    ENCAR    = "ENCAR",    "Encar (Korea)"
    KCAR     = "KCAR",     "KCar (Korea)"
    MANUAL   = "MANUAL",   "Manual Entry"


class VehicleStatus(models.TextChoices):
    ACTIVE    = "active",    _("مزاد مفتوح")
    SOLD      = "sold",      _("مباع")
    UPCOMING  = "upcoming",  _("قادم")
    EXPIRED   = "expired",   _("منتهي")
    CANCELLED = "cancelled", _("ملغى")


class TitleType(models.TextChoices):
    CLEAN        = "clean",        _("Clean Title")
    SALVAGE      = "salvage",      _("Salvage Title")
    REBUILT      = "rebuilt",      _("Rebuilt Title")
    PARTS_ONLY   = "parts_only",   _("Parts Only")
    CERTIFICATE  = "certificate",  _("Certificate of Title")
    LIEN         = "lien",         _("Lien Title")
    UNKNOWN      = "unknown",      _("Unknown")


class FuelType(models.TextChoices):
    PETROL   = "petrol",   _("بنزين")
    DIESEL   = "diesel",   _("ديزل")
    HYBRID   = "hybrid",   _("هجين")
    ELECTRIC = "electric", _("كهربائي")
    OTHER    = "other",    _("أخرى")


class DriveType(models.TextChoices):
    FWD  = "fwd",  "FWD"
    RWD  = "rwd",  "RWD"
    AWD  = "awd",  "AWD"
    FOUR = "4wd",  "4WD"


# ══════════════════════════════════════════════════════════════════════════
#  MAIN VEHICLE MODEL
# ══════════════════════════════════════════════════════════════════════════

class AuctionVehicle(models.Model):
    """
    النموذج الموحّد لجميع السيارات من كل المزادات.

    كل سيارة تأتي من أي مزاد تُخزَّن هنا بنفس الهيكل،
    مما يسهّل البحث والمقارنة والتحليل.
    """

    # ── Identity ──────────────────────────────────────────────────────────
    lot_number = models.CharField(
        max_length=128, unique=True, db_index=True,
        verbose_name=_("رقم اللوت"),
        help_text="Unique: {lot_id}-{SOURCE}-{COUNTRY}"
    )
    vin = models.CharField(
        max_length=17, blank=True, null=True, db_index=True,
        verbose_name=_("رقم الهيكل (VIN)"),
    )
    dedup_key = models.CharField(
        max_length=64, blank=True, null=True, db_index=True,
        verbose_name=_("مفتاح إزالة التكرار"),
        help_text="VIN if available, else lot_number. Used to prevent duplicates across sources.",
    )

    # ── Source ────────────────────────────────────────────────────────────
    source_auction = models.CharField(
        max_length=16, choices=AuctionSource.choices,
        default=AuctionSource.MANUAL, db_index=True,
        verbose_name=_("المزاد المصدر"),
    )
    source_country = models.CharField(
        max_length=4, blank=True, default="US",
        verbose_name=_("دولة المزاد"),
    )
    source_url = models.URLField(
        blank=True, null=True,
        verbose_name=_("رابط السيارة في المزاد"),
    )

    # ── Vehicle Info ──────────────────────────────────────────────────────
    year = models.PositiveSmallIntegerField(
        null=True, blank=True, db_index=True,
        verbose_name=_("سنة الصنع"),
    )
    make = models.CharField(
        max_length=64, blank=True, db_index=True,
        verbose_name=_("الماركة"),
    )
    model = models.CharField(
        max_length=128, blank=True, db_index=True,
        verbose_name=_("الموديل"),
    )
    trim = models.CharField(
        max_length=128, blank=True,
        verbose_name=_("الفئة (Trim)"),
    )
    body_style = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("نوع الهيكل"),
    )
    color = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("اللون"),
    )
    interior_color = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("لون الداخلية"),
    )

    # ── Powertrain ────────────────────────────────────────────────────────
    engine = models.CharField(
        max_length=128, blank=True,
        verbose_name=_("المحرك"),
    )
    cylinders = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name=_("عدد الأسطوانات"),
    )
    fuel_type = models.CharField(
        max_length=16, choices=FuelType.choices,
        blank=True, default="",
        verbose_name=_("نوع الوقود"),
    )
    transmission = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("ناقل الحركة"),
    )
    drive_type = models.CharField(
        max_length=8, choices=DriveType.choices,
        blank=True, default="",
        verbose_name=_("نوع الدفع"),
    )

    # ── Condition ─────────────────────────────────────────────────────────
    odometer = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name=_("عداد المسافة"),
    )
    odometer_unit = models.CharField(
        max_length=4, default="mi",
        choices=[("mi", "Miles"), ("km", "Kilometers")],
        verbose_name=_("وحدة العداد"),
    )
    odometer_km = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name=_("عداد المسافة (كم)"),
        help_text="Auto-calculated from odometer + unit",
    )
    title_type = models.CharField(
        max_length=16, choices=TitleType.choices,
        default=TitleType.UNKNOWN, db_index=True,
        verbose_name=_("نوع الصك"),
    )
    damage_primary = models.CharField(
        max_length=256, blank=True,
        verbose_name=_("الضرر الرئيسي"),
    )
    damage_secondary = models.CharField(
        max_length=256, blank=True,
        verbose_name=_("الضرر الثانوي"),
    )
    has_keys = models.BooleanField(
        null=True, blank=True,
        verbose_name=_("يوجد مفاتيح"),
    )
    runs_drives = models.BooleanField(
        null=True, blank=True,
        verbose_name=_("يعمل ويسير"),
    )
    auction_grade = models.CharField(
        max_length=8, blank=True,
        verbose_name=_("درجة المزاد"),
        help_text="Japanese grade: 5=Excellent, 4=Good, 3=Average",
    )

    # ── Quality Score (Manus innovation) ─────────────────────────────────
    quality_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name=_("نقاط الجودة (0-100)"),
        help_text=(
            "Auto-calculated score: "
            "title_type(30) + runs_drives(20) + has_keys(10) + "
            "odometer(20) + damage(20)"
        ),
    )

    # ── Pricing ───────────────────────────────────────────────────────────
    current_bid = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("المزايدة الحالية"),
    )
    buy_now_price = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("سعر الشراء الفوري"),
    )
    estimated_retail_value = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("القيمة التجزئة التقديرية"),
    )
    currency = models.CharField(
        max_length=4, default="USD",
        verbose_name=_("العملة"),
    )
    normalized_price_usd = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True, db_index=True,
        verbose_name=_("السعر بالدولار (موحّد)"),
        help_text="Auto-converted to USD from any currency",
    )

    # ── Import Cost Estimate (Libya-specific) ─────────────────────────────
    import_cost_estimate = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("تقدير تكلفة الاستيراد الكاملة (USD)"),
        help_text="bid + auction_fees + shipping + customs + port_fees",
    )
    import_cost_breakdown = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("تفاصيل تكلفة الاستيراد"),
    )

    # ── Location & Auction ────────────────────────────────────────────────
    location_city = models.CharField(
        max_length=128, blank=True,
        verbose_name=_("المدينة"),
    )
    location_state = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("الولاية/المنطقة"),
    )
    location_country = models.CharField(
        max_length=4, blank=True, default="US",
        verbose_name=_("الدولة"),
    )
    auction_date = models.DateTimeField(
        null=True, blank=True, db_index=True,
        verbose_name=_("تاريخ المزاد"),
    )
    status = models.CharField(
        max_length=16, choices=VehicleStatus.choices,
        default=VehicleStatus.UPCOMING, db_index=True,
        verbose_name=_("الحالة"),
    )
    bid_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("عدد المزايدات"),
    )

    # ── Media ─────────────────────────────────────────────────────────────
    primary_image = models.URLField(
        blank=True, null=True,
        verbose_name=_("الصورة الرئيسية"),
    )
    images_json = models.JSONField(
        default=list, blank=True,
        verbose_name=_("قائمة الصور"),
    )
    has_360_view = models.BooleanField(
        default=False,
        verbose_name=_("يوجد عرض 360°"),
    )

    # ── Raw Data ──────────────────────────────────────────────────────────
    raw_data = models.JSONField(
        default=dict, blank=True,
        verbose_name=_("البيانات الخام من المصدر"),
    )

    # ── Sync Metadata ─────────────────────────────────────────────────────
    first_seen_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("أول ظهور"),
    )
    last_synced_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("آخر مزامنة"),
    )
    sync_source = models.CharField(
        max_length=64, blank=True,
        verbose_name=_("مصدر المزامنة"),
        help_text="e.g. 'salvagebid', 'direct', 'bidcars', 'beforward'",
    )
    is_deleted = models.BooleanField(
        default=False, db_index=True,
        verbose_name=_("محذوف (soft delete)"),
    )

    class Meta:
        db_table = "auction_vehicle"
        verbose_name = _("سيارة مزاد")
        verbose_name_plural = _("سيارات المزادات")
        ordering = ["-first_seen_at"]
        indexes = [
            models.Index(fields=["source_auction", "status"]),
            models.Index(fields=["make", "model", "year"]),
            models.Index(fields=["normalized_price_usd"]),
            models.Index(fields=["title_type", "quality_score"]),
            models.Index(fields=["auction_date"]),
        ]

    def __str__(self):
        return f"{self.year} {self.make} {self.model} [{self.source_auction}] #{self.lot_number}"

    # ── Auto-calculations ─────────────────────────────────────────────────

    def save(self, *args, **kwargs):
        """Override save to auto-calculate derived fields."""
        self._set_dedup_key()
        self._convert_odometer()
        self._calculate_quality_score()
        self._normalize_price_usd()
        super().save(*args, **kwargs)

    def _set_dedup_key(self):
        """Use VIN as dedup key if valid, else lot_number."""
        if self.vin and len(self.vin) == 17 and self.vin.isalnum():
            self.dedup_key = self.vin.upper()
        else:
            self.dedup_key = self.lot_number

    def _convert_odometer(self):
        """Convert odometer to km if in miles."""
        if self.odometer and self.odometer_unit == "mi":
            self.odometer_km = round(self.odometer * 1.60934)
        elif self.odometer and self.odometer_unit == "km":
            self.odometer_km = self.odometer

    def _calculate_quality_score(self):
        """
        Calculate quality score (0-100) based on:
        - Title type: clean=30, salvage=10, rebuilt=20, parts_only=0
        - Runs & drives: yes=20, no=0, unknown=10
        - Has keys: yes=10, no=0, unknown=5
        - Odometer: <50k mi=20, <100k=15, <150k=10, >150k=5
        - No damage: 20, minor=10, major=0
        """
        score = 0

        # Title type (max 30)
        title_scores = {
            TitleType.CLEAN: 30,
            TitleType.REBUILT: 20,
            TitleType.SALVAGE: 10,
            TitleType.CERTIFICATE: 25,
            TitleType.LIEN: 15,
            TitleType.PARTS_ONLY: 0,
            TitleType.UNKNOWN: 10,
        }
        score += title_scores.get(self.title_type, 10)

        # Runs & drives (max 20)
        if self.runs_drives is True:
            score += 20
        elif self.runs_drives is None:
            score += 10

        # Has keys (max 10)
        if self.has_keys is True:
            score += 10
        elif self.has_keys is None:
            score += 5

        # Odometer (max 20)
        odo_km = self.odometer_km or 0
        if odo_km < 80000:
            score += 20
        elif odo_km < 150000:
            score += 15
        elif odo_km < 200000:
            score += 10
        else:
            score += 5

        # Damage (max 20)
        damage = (self.damage_primary or "").lower()
        if not damage or damage in ("none", "no damage", "normal wear"):
            score += 20
        elif any(w in damage for w in ("minor", "light", "small")):
            score += 10
        elif any(w in damage for w in ("front", "rear", "side")):
            score += 8
        else:
            score += 0

        self.quality_score = min(score, 100)

    def _normalize_price_usd(self):
        """Convert current_bid to USD using approximate rates."""
        if not self.current_bid:
            return

        fx = {
            "USD": 1.0,
            "GBP": 1.27,
            "EUR": 1.08,
            "JPY": 0.0067,
            "SEK": 0.096,
            "AED": 0.272,
            "SAR": 0.267,
            "LYD": 0.207,
        }
        rate = fx.get(self.currency.upper(), 1.0)
        self.normalized_price_usd = round(float(self.current_bid) * rate, 2)

    def calculate_import_cost(
        self,
        destination_port: str = "misrata",
        include_customs: bool = True,
    ) -> Dict[str, Any]:
        """
        Calculate full import cost to Libya.

        Returns breakdown dict:
          auction_price, buyer_fee, shipping, port_fee,
          customs_duty, total_usd, total_lyd
        """
        from django.conf import settings

        price = float(self.normalized_price_usd or 0)
        source = self.source_auction

        # Auction buyer fees (varies by auction)
        buyer_fee_rates = {
            "COPART":  0.10,   # ~10% of bid
            "IAAI":    0.10,
            "MANHEIM": 0.08,
            "ADESA":   0.08,
            "ACV":     0.07,
            "BCA":     0.05,
            "JAPAN":   0.05,
            "GOVDEALS": 0.05,
        }
        buyer_fee_rate = buyer_fee_rates.get(source, 0.10)
        buyer_fee = round(price * buyer_fee_rate, 2)

        # Shipping cost by source country
        shipping_costs = {
            "US":  {"misrata": 1200, "tripoli": 1100, "benghazi": 1300},
            "GB":  {"misrata": 800,  "tripoli": 750,  "benghazi": 900},
            "DE":  {"misrata": 850,  "tripoli": 800,  "benghazi": 950},
            "JP":  {"misrata": 1800, "tripoli": 1750, "benghazi": 1900},
            "FR":  {"misrata": 820,  "tripoli": 780,  "benghazi": 920},
        }
        country = self.source_country or "US"
        port_costs = shipping_costs.get(country, shipping_costs["US"])
        shipping = port_costs.get(destination_port, 1200)

        # Port fees (Libya)
        port_fee = 200

        # CIF value = price + buyer_fee + shipping
        cif = price + buyer_fee + shipping

        # Customs duty (Libya: ~30% of CIF)
        customs = round(cif * settings.LIBYAN_CUSTOMS_RATE, 2) if include_customs else 0

        # Total
        total_usd = round(price + buyer_fee + shipping + port_fee + customs, 2)

        # Convert to LYD (approx 1 USD = 4.83 LYD)
        total_lyd = round(total_usd * 4.83, 2)

        breakdown = {
            "auction_price_usd": price,
            "buyer_fee_usd": buyer_fee,
            "buyer_fee_rate": f"{buyer_fee_rate*100:.0f}%",
            "shipping_usd": shipping,
            "port_fee_usd": port_fee,
            "customs_duty_usd": customs,
            "total_usd": total_usd,
            "total_lyd": total_lyd,
            "destination_port": destination_port,
            "note_ar": (
                f"السعر الكلي يشمل: سعر المزاد + رسوم المشتري + الشحن إلى "
                f"ميناء {destination_port} + رسوم الميناء + الجمارك"
            ),
        }

        # Cache in model
        self.import_cost_estimate = total_usd
        self.import_cost_breakdown = breakdown

        return breakdown

    def to_api_dict(self) -> Dict[str, Any]:
        """Return a clean dict for API responses."""
        return {
            "id": self.id,
            "lot_number": self.lot_number,
            "vin": self.vin,
            "source": self.source_auction,
            "source_country": self.source_country,
            "source_url": self.source_url,
            "year": self.year,
            "make": self.make,
            "model": self.model,
            "trim": self.trim,
            "body_style": self.body_style,
            "color": self.color,
            "engine": self.engine,
            "fuel_type": self.fuel_type,
            "transmission": self.transmission,
            "drive_type": self.drive_type,
            "odometer_km": self.odometer_km,
            "title_type": self.title_type,
            "damage_primary": self.damage_primary,
            "has_keys": self.has_keys,
            "runs_drives": self.runs_drives,
            "quality_score": self.quality_score,
            "current_bid_usd": float(self.normalized_price_usd or 0),
            "currency_original": self.currency,
            "current_bid_original": float(self.current_bid or 0),
            "status": self.status,
            "auction_date": self.auction_date.isoformat() if self.auction_date else None,
            "location": f"{self.location_city}, {self.location_state}".strip(", "),
            "primary_image": self.primary_image,
            "images": self.images_json,
            "import_cost_estimate": float(self.import_cost_estimate or 0),
            "last_synced": self.last_synced_at.isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════
#  SYNC RUN LOG
# ══════════════════════════════════════════════════════════════════════════

class SyncRun(models.Model):
    """Tracks every sync operation — useful for monitoring and debugging."""

    source = models.CharField(
        max_length=16, choices=AuctionSource.choices,
        db_index=True,
        verbose_name=_("المصدر"),
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("running", "Running"),
            ("success", "Success"),
            ("partial", "Partial"),
            ("failed",  "Failed"),
        ],
        default="running",
    )
    pages_fetched = models.PositiveIntegerField(default=0)
    vehicles_created = models.PositiveIntegerField(default=0)
    vehicles_updated = models.PositiveIntegerField(default=0)
    vehicles_skipped = models.PositiveIntegerField(default=0)
    vehicles_deleted = models.PositiveIntegerField(default=0)
    errors_count = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    options_used = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "sync_run"
        ordering = ["-started_at"]

    def __str__(self):
        return f"SyncRun({self.source}, {self.status}, {self.started_at:%Y-%m-%d %H:%M})"

    def finish(self, status: str = "success"):
        self.finished_at = dj_timezone.now()
        self.status = status
        self.save(update_fields=["finished_at", "status"])

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


# ══════════════════════════════════════════════════════════════════════════
#  PRICE ALERT
# ══════════════════════════════════════════════════════════════════════════

class PriceAlert(models.Model):
    """
    User-defined price alerts.
    When a vehicle matching the criteria appears below max_price,
    the user gets notified via WhatsApp/email.
    """
    user = models.ForeignKey(
        "auth.User", on_delete=models.CASCADE,
        related_name="price_alerts",
        verbose_name=_("المستخدم"),
    )
    make = models.CharField(max_length=64, blank=True, verbose_name=_("الماركة"))
    model = models.CharField(max_length=128, blank=True, verbose_name=_("الموديل"))
    year_min = models.PositiveSmallIntegerField(null=True, blank=True)
    year_max = models.PositiveSmallIntegerField(null=True, blank=True)
    max_price_usd = models.DecimalField(max_digits=10, decimal_places=2)
    title_types = models.JSONField(
        default=list, blank=True,
        help_text="List of acceptable title types e.g. ['clean', 'salvage']",
    )
    sources = models.JSONField(
        default=list, blank=True,
        help_text="List of sources to watch e.g. ['COPART', 'IAAI']",
    )
    is_active = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    trigger_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "price_alert"
        verbose_name = _("تنبيه سعر")
        verbose_name_plural = _("تنبيهات الأسعار")

    def __str__(self):
        return f"Alert: {self.make} {self.model} < ${self.max_price_usd} [{self.user}]"

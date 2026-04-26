"""
MACCHINAA-EVOLVED — sync_auction Management Command
======================================================
أمر Django لجلب ومزامنة السيارات من مزاد محدد.

الاستخدام:
    # جلب من Copart
    python manage.py sync_auction --source copart --max-pages 50

    # جلب Toyota من IAAI
    python manage.py sync_auction --source iaai --make Toyota --max-pages 20

    # جلب من BCA أوروبا
    python manage.py sync_auction --source bca --country uk

    # جلب النماذج الساخنة من اليابان
    python manage.py sync_auction --source japan --hot-models-only

    # جلب من GovDeals
    python manage.py sync_auction --source govdeals --max-pages 10

    # جلب من كل المصادر
    python manage.py sync_auction --source all
"""
import logging
import os
import sys
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

SUPPORTED_SOURCES = ["copart", "iaai", "bca", "japan", "govdeals", "manheim", "adesa", "all"]


class Command(BaseCommand):
    help = "جلب ومزامنة السيارات من مواقع المزادات العالمية"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="copart",
            choices=SUPPORTED_SOURCES,
            help="مصدر المزاد: copart, iaai, bca, japan, govdeals, manheim, adesa, all",
        )
        parser.add_argument(
            "--make",
            type=str,
            default=None,
            help="فلتر الماركة (مثال: Toyota, BMW)",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=None,
            help="فلتر الموديل (مثال: Camry, Land Cruiser)",
        )
        parser.add_argument(
            "--year-min",
            type=int,
            default=None,
            help="سنة الصنع الأدنى",
        )
        parser.add_argument(
            "--year-max",
            type=int,
            default=None,
            help="سنة الصنع الأعلى",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=settings.SCRAPER_MAX_PAGES_DEFAULT,
            help=f"عدد الصفحات الأقصى (الافتراضي: {settings.SCRAPER_MAX_PAGES_DEFAULT})",
        )
        parser.add_argument(
            "--country",
            type=str,
            default="uk",
            help="الدولة لـ BCA: uk, de, fr, nl, be",
        )
        parser.add_argument(
            "--hot-models-only",
            action="store_true",
            default=False,
            help="جلب النماذج الساخنة للسوق الليبي فقط (لليابان)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=settings.SCRAPER_DEFAULT_DELAY,
            help=f"التأخير بين الطلبات بالثواني (الافتراضي: {settings.SCRAPER_DEFAULT_DELAY})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="تشغيل تجريبي — جلب البيانات دون حفظها في قاعدة البيانات",
        )

    def handle(self, *args, **options):
        source = options["source"]
        make = options.get("make")
        model = options.get("model")
        year_min = options.get("year_min")
        year_max = options.get("year_max")
        max_pages = options["max_pages"]
        country = options.get("country", "uk")
        hot_models_only = options.get("hot_models_only", False)
        delay = options["delay"]
        dry_run = options["dry_run"]

        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"  MACCHINAA-EVOLVED — Sync Auction\n"
            f"  المصدر: {source.upper()}\n"
            f"  الماركة: {make or 'الكل'}\n"
            f"  الصفحات: {max_pages}\n"
            f"  وضع تجريبي: {'نعم' if dry_run else 'لا'}\n"
            f"{'='*60}\n"
        ))

        if source == "all":
            self._sync_all(options)
            return

        # Run single source
        total_created, total_updated = self._sync_source(source, options)

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ اكتملت المزامنة:\n"
            f"   جديد: {total_created}\n"
            f"   محدّث: {total_updated}\n"
        ))

    def _sync_all(self, options):
        """Sync from all sources sequentially."""
        sources = ["copart", "iaai", "govdeals", "bca", "japan"]
        total_created = total_updated = 0

        for source in sources:
            self.stdout.write(f"\n{'─'*40}")
            self.stdout.write(f"  ▶ بدء مزامنة: {source.upper()}")
            opts = dict(options)
            opts["source"] = source
            opts["max_pages"] = min(options["max_pages"], 20)  # Limit per source in "all" mode
            created, updated = self._sync_source(source, opts)
            total_created += created
            total_updated += updated

        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"✅ اكتملت مزامنة كل المصادر:\n"
            f"   إجمالي جديد: {total_created}\n"
            f"   إجمالي محدّث: {total_updated}\n"
            f"{'='*60}\n"
        ))

    def _sync_source(self, source: str, options: dict) -> tuple:
        """Sync from a specific source. Returns (created, updated)."""
        from core.models import AuctionVehicle, SyncRun

        make = options.get("make")
        model = options.get("model")
        year_min = options.get("year_min")
        year_max = options.get("year_max")
        max_pages = options["max_pages"]
        country = options.get("country", "uk")
        hot_models_only = options.get("hot_models_only", False)
        delay = options["delay"]
        dry_run = options["dry_run"]

        # Create sync run record
        sync_run = None
        if not dry_run:
            sync_run = SyncRun.objects.create(
                source=source.upper(),
                options_used=options,
            )

        # Initialize scraper
        scraper = self._get_scraper(source, delay)
        if not scraper:
            self.stderr.write(f"❌ مصدر غير معروف: {source}")
            return 0, 0

        # Fetch pages
        created = updated = errors = 0
        batch_num = 0

        try:
            pages_gen = self._get_pages_generator(
                scraper, source, make=make, model=model,
                year_min=year_min, year_max=year_max,
                max_pages=max_pages, country=country,
                hot_models_only=hot_models_only,
            )

            for batch in pages_gen:
                batch_num += 1
                self.stdout.write(
                    f"  📦 دفعة {batch_num}: {len(batch)} سيارة"
                )

                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] أول سيارة: "
                        f"{batch[0].get('year')} {batch[0].get('make')} {batch[0].get('model')}"
                    )
                    continue

                # Save to database
                batch_created, batch_updated, batch_errors = self._save_batch(batch)
                created += batch_created
                updated += batch_updated
                errors += batch_errors

                self.stdout.write(
                    f"    ✅ جديد: {batch_created} | محدّث: {batch_updated} | "
                    f"أخطاء: {batch_errors}"
                )

                # Update sync run stats
                if sync_run:
                    sync_run.pages_fetched = batch_num
                    sync_run.vehicles_created = created
                    sync_run.vehicles_updated = updated
                    sync_run.errors_count = errors
                    sync_run.save(update_fields=[
                        "pages_fetched", "vehicles_created",
                        "vehicles_updated", "errors_count",
                    ])

        except KeyboardInterrupt:
            self.stdout.write("\n⚠️ تم إيقاف المزامنة يدوياً")
            if sync_run:
                sync_run.finish("partial")
        except Exception as exc:
            self.stderr.write(f"❌ خطأ: {exc}")
            if sync_run:
                sync_run.error_log = str(exc)
                sync_run.finish("failed")
            raise
        else:
            if sync_run:
                sync_run.finish("success")

        return created, updated

    def _get_scraper(self, source: str, delay: float):
        """Initialize the appropriate scraper."""
        if source == "copart":
            from scrapers.copart.scraper import CopartScraper
            return CopartScraper(delay=delay)
        elif source == "iaai":
            from scrapers.iaai.scraper import IAAScraper
            return IAAScraper(delay=delay)
        elif source == "bca":
            from scrapers.bca.scraper import BCAScraper
            return BCAScraper(delay=delay)
        elif source == "japan":
            from scrapers.japan.scraper import JapanAuctionsScraper
            return JapanAuctionsScraper(delay=delay)
        elif source == "govdeals":
            from scrapers.govdeals.scraper import GovDealsScraper
            return GovDealsScraper(delay=delay)
        elif source == "manheim":
            from scrapers.manheim.scraper import ManheimScraper
            return ManheimScraper(
                client_id=settings.MANHEIM_CLIENT_ID,
                client_secret=settings.MANHEIM_CLIENT_SECRET,
                delay=delay,
            )
        elif source == "adesa":
            from scrapers.adesa.scraper import ADESAScraper
            return ADESAScraper(
                bearer_token=settings.ADESA_BEARER_TOKEN,
                dealer_id=settings.ADESA_DEALER_ID,
                delay=delay,
            )
        return None

    def _get_pages_generator(self, scraper, source, **kwargs):
        """Get the appropriate pages generator for each scraper."""
        make = kwargs.get("make")
        model = kwargs.get("model")
        year_min = kwargs.get("year_min")
        year_max = kwargs.get("year_max")
        max_pages = kwargs.get("max_pages", 50)
        country = kwargs.get("country", "uk")
        hot_models_only = kwargs.get("hot_models_only", False)

        if source == "copart":
            return scraper.fetch_pages(
                make=make, model=model,
                year_min=year_min, year_max=year_max,
                max_pages=max_pages,
            )
        elif source == "iaai":
            return scraper.fetch_pages(
                make=make, year_min=year_min, year_max=year_max,
                max_pages=max_pages,
            )
        elif source == "bca":
            return scraper.fetch_pages(
                country=country, make=make,
                year_min=year_min, year_max=year_max,
                max_pages=max_pages,
            )
        elif source == "japan":
            if hot_models_only:
                return scraper.fetch_hot_models(max_pages=max_pages)
            return scraper.fetch_pages(
                make=make, model=model,
                year_min=year_min, year_max=year_max,
                max_pages=max_pages,
            )
        elif source == "govdeals":
            return scraper.fetch_pages(max_pages=max_pages)
        elif source in ("manheim", "adesa"):
            return scraper.fetch_pages(
                make=make, year_min=year_min, year_max=year_max,
                max_pages=max_pages,
            )

        return iter([])  # Empty generator for unknown sources

    def _save_batch(self, batch: list) -> tuple:
        """Save a batch of normalized vehicles to the database."""
        from core.models import AuctionVehicle

        created = updated = errors = 0

        for vehicle_data in batch:
            try:
                lot_number = vehicle_data.get("lot_number")
                if not lot_number:
                    errors += 1
                    continue

                # Check for existing by lot_number
                existing = AuctionVehicle.objects.filter(
                    lot_number=lot_number
                ).first()

                # Also check by VIN (dedup across sources)
                vin = vehicle_data.get("vin")
                if not existing and vin and len(vin) == 17:
                    existing = AuctionVehicle.objects.filter(
                        vin=vin,
                        source_auction=vehicle_data.get("source_auction"),
                    ).first()

                # Prepare fields
                fields = {
                    k: v for k, v in vehicle_data.items()
                    if k not in ("agency", "description", "title_raw",
                                 "grade_numeric", "shipping_estimate_usd",
                                 "is_hot_model")
                    and hasattr(AuctionVehicle, k)
                }

                if existing:
                    # Update existing
                    for key, val in fields.items():
                        if key not in ("lot_number", "first_seen_at"):
                            setattr(existing, key, val)
                    existing.save()
                    updated += 1
                else:
                    # Create new
                    AuctionVehicle.objects.create(**fields)
                    created += 1

            except Exception as exc:
                logger.error("Error saving vehicle %s: %s", vehicle_data.get("lot_number"), exc)
                errors += 1

        return created, updated, errors

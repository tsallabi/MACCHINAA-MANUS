"""
acv_api_sync.py — جلب السيارات من ACV Auctions عبر API مباشر
══════════════════════════════════════════════════════════════
الفرق عن acv_scraper.py الموجود:
  - acv_scraper.py يعتمد على Playwright (متصفح) — يتطلب جلسة مسجّلة
  - هذا السكريبت يعمل بـ 3 مصادر بديلة بدون متصفح:

  1. ACV Public Listings  — API مباشر بجلسة مسجّلة (إذا توفرت credentials)
  2. SalvageBid ACV       — يعيد سيارات ACV من salvagebid.com
  3. AutoBidMaster ACV    — aggregator يغطي ACV
  4. CarGurus/AutoTrader  — بيانات ACV المُصدَّرة (fallback)

الاستخدام:
    python manage.py acv_api_sync
    python manage.py acv_api_sync --source salvagebid
    python manage.py acv_api_sync --make Toyota --max-pages 10
    python manage.py acv_api_sync --dry-run
    python manage.py acv_api_sync --resume

ملاحظة:
  - يحفظ في ManualCarData بـ Yard_name = "ACV"
  - متوافق تماماً مع AcvMirrorLot (يستخدم نفس lot_number)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════

ACV_BASE_URL = "https://app.acvauctions.com"
ACV_API_URL  = f"{ACV_BASE_URL}/api/v2/auctions"

SALVAGEBID_ACV_URL = "https://www.salvagebid.com/rest-api/v1.0/lots/search"
BIDCARS_ACV_URL    = "https://bid.cars/en/search/results"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _safe_str(val: Any, max_len: int = 50) -> str:
    if val is None:
        return ""
    return str(val).strip()[:max_len]


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(str(val).replace(",", "").strip())
    except Exception:
        return None


def _normalize_title(title_code: str) -> str:
    """يحوّل كود العنوان إلى نص مقروء."""
    mapping = {
        "CL": "Clean",
        "SV": "Salvage",
        "RB": "Rebuilt",
        "PO": "Parts Only",
        "SC": "Salvage Certificate",
        "LN": "Lien",
        "NE": "Non-Repairable",
    }
    return mapping.get((title_code or "").upper(), title_code or "")


def _get_existing_lots(db_path: str) -> Set[str]:
    """يجلب أرقام لوتات ACV الموجودة."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        rows = conn.execute(
            'SELECT Lot_number FROM "ManualCarData" WHERE Yard_name = "ACV"'
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning("Could not fetch existing ACV lots: %s", e)
        return set()


def _save_to_db(cars: List[Dict], db_path: str, log_fn=print) -> int:
    """يحفظ سيارات ACV في ManualCarData."""
    if not cars:
        return 0

    conn = sqlite3.connect(db_path, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA journal_mode=WAL")

    saved = 0
    for batch_start in range(0, len(cars), 100):
        batch = cars[batch_start:batch_start + 100]
        params_list = []
        for car in batch:
            lot = _safe_str(car.get("lot_number", ""), 100)
            if not lot:
                continue
            params_list.append((
                lot,
                _safe_str(car.get("vin", ""), 50),
                _safe_str(car.get("make", ""), 50),
                _safe_str(car.get("model", ""), 50),
                _safe_int(car.get("year")),
                _safe_str(car.get("color", ""), 50),
                _safe_str(car.get("damage", ""), 1024),
                _safe_str(car.get("secondary_damage", ""), 1024),
                _safe_str(car.get("odometer", ""), 50),
                _safe_str(car.get("odometer_brand", ""), 50),
                _safe_str(car.get("engine", ""), 50),
                _safe_str(car.get("drive", ""), 50),
                _safe_str(car.get("transmission", ""), 50),
                _safe_str(car.get("fuel", ""), 50),
                _safe_str(car.get("body_style", ""), 50),
                _safe_str(car.get("sale_status", "active"), 1024),
                _safe_str(car.get("current_bid", ""), 1024),
                _safe_str(car.get("buy_now", ""), 50),
                _safe_str(car.get("city", ""), 1024),
                _safe_str(car.get("state", ""), 1024),
                _safe_str(car.get("zip", ""), 1024),
                "US",
                "USD",
                _safe_str(car.get("thumbnail", ""), 1024),
                _safe_str(car.get("thumbnail", ""), 100),
                _safe_str(car.get("trim", ""), 1024),
                _safe_str(car.get("sale_date", ""), 50),
                _safe_str(car.get("min_price", ""), 1024),
                _safe_str(car.get("note", ""), 1024),
                "ACV",
                _safe_str(car.get("est_retail", ""), 50),
                _safe_str(car.get("title_type", ""), 1024),
                _safe_str(car.get("keys", ""), 50),
                _safe_str(car.get("runs_drives", ""), 1024),
            ))

        if params_list:
            try:
                conn.executemany('''
                    INSERT OR IGNORE INTO "ManualCarData"
                    ("Lot_number", "VIN", "Make", "Model_Detail", "Year",
                     "Color", "Damage_Description", "Secondary_Damage",
                     "Odometer", "Odometer_Brand", "Engine", "Drive",
                     "Transmission", "Fuel_Type", "Body_Style",
                     "Sale_Status", "High_Bid_non_vix_Sealed_Vix",
                     "Buy_It_Now_Price", "Location_city", "Location_state",
                     "Location_ZIP", "Location_country", "Currency_Code",
                     "Image_Thumbnail", "Image_URL", "Trim",
                     "Sale_Date_M_D_CY", "Minimum_Price", "Special_Note",
                     "Yard_name", "Est_Retail_Value", "Sale_Title_Type",
                     "Has_Keys_Yes_or_No", "Runs_Drives")
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', params_list)
                saved += conn.execute("SELECT changes()").fetchone()[0]
            except Exception as e:
                log_fn(f"  [DB ERROR] {e}")

        conn.commit()

    conn.close()
    return saved


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 1: ACV DIRECT API (يتطلب credentials)
# ══════════════════════════════════════════════════════════════════════════

def _fetch_acv_direct(
    username: str,
    password: str,
    make_filter: str = "",
    max_pages: int = 10,
    delay: float = 1.5,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    يجلب من ACV API المباشر باستخدام credentials.
    يتطلب: ACV_USERNAME و ACV_PASSWORD في settings أو .env
    """
    if existing_lots is None:
        existing_lots = set()

    if not username or not password:
        log_fn("  [ACV-DIRECT] لا توجد credentials — تخطي")
        return []

    session = _make_session()

    # تسجيل الدخول
    log_fn("  [ACV-DIRECT] محاولة تسجيل الدخول...")
    try:
        login_resp = session.post(
            f"{ACV_BASE_URL}/api/v1/auth/login",
            json={"email": username, "password": password},
            timeout=20,
        )
        if login_resp.status_code != 200:
            log_fn(f"  [ACV-DIRECT] فشل تسجيل الدخول: {login_resp.status_code}")
            return []

        token_data = login_resp.json()
        token = token_data.get("token") or token_data.get("access_token", "")
        if not token:
            log_fn("  [ACV-DIRECT] لا يوجد token في الاستجابة")
            return []

        session.headers.update({"Authorization": f"Bearer {token}"})
        log_fn("  [ACV-DIRECT] ✓ تسجيل الدخول ناجح")

    except Exception as e:
        log_fn(f"  [ACV-DIRECT] خطأ في تسجيل الدخول: {e}")
        return []

    # جلب السيارات
    all_cars = []
    page = 1
    total_fetched = 0

    while True:
        if max_pages > 0 and page > max_pages:
            break

        params = {
            "page": page,
            "per_page": 25,
            "status": "active",
            "sort_by": "end_time",
            "sort_order": "asc",
        }
        if make_filter:
            params["make"] = make_filter

        try:
            resp = session.get(ACV_API_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [ACV-DIRECT] خطأ في الصفحة {page}: {e}")
            break

        items = data.get("auctions", []) or data.get("data", []) or []
        if not items:
            break

        for item in items:
            auction_id = str(item.get("id", "") or item.get("auction_id", ""))
            if not auction_id:
                continue

            lot = f"{auction_id}-ACV"
            if lot in existing_lots:
                continue

            vehicle = item.get("vehicle", {}) or item
            car = {
                "lot_number": lot,
                "vin": _safe_str(vehicle.get("vin", ""), 50),
                "make": _safe_str(vehicle.get("make", ""), 50),
                "model": _safe_str(vehicle.get("model", ""), 50),
                "year": _safe_int(vehicle.get("year")),
                "color": _safe_str(vehicle.get("color", ""), 50),
                "damage": _safe_str(vehicle.get("condition", ""), 1024),
                "secondary_damage": "",
                "odometer": _safe_str(vehicle.get("mileage", ""), 50),
                "odometer_brand": "miles",
                "engine": _safe_str(vehicle.get("engine", ""), 50),
                "drive": _safe_str(vehicle.get("drivetrain", ""), 50),
                "transmission": _safe_str(vehicle.get("transmission", ""), 50),
                "fuel": _safe_str(vehicle.get("fuel_type", ""), 50),
                "body_style": _safe_str(vehicle.get("body_style", ""), 50),
                "sale_status": "active",
                "current_bid": _safe_str(item.get("current_bid", ""), 50),
                "buy_now": _safe_str(item.get("buy_now_price", ""), 50),
                "city": _safe_str(item.get("location", {}).get("city", "") if isinstance(item.get("location"), dict) else "", 1024),
                "state": _safe_str(item.get("location", {}).get("state", "") if isinstance(item.get("location"), dict) else "", 1024),
                "zip": "",
                "thumbnail": _safe_str(item.get("primary_photo", "") or vehicle.get("primary_photo", ""), 1024),
                "trim": _safe_str(vehicle.get("trim", ""), 1024),
                "sale_date": _safe_str(item.get("end_time", ""), 50),
                "min_price": "",
                "note": f"ACV Auction ID: {auction_id}",
                "est_retail": _safe_str(vehicle.get("retail_value", ""), 50),
                "title_type": _normalize_title(vehicle.get("title_type", "")),
                "keys": "Yes" if vehicle.get("has_keys") else "No",
                "runs_drives": "Yes" if vehicle.get("runs_drives") else "No",
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [ACV-DIRECT] صفحة {page}: {len(items)} سيارة، إجمالي: {total_fetched}")

        if not data.get("next_page"):
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [ACV-DIRECT] ✓ انتهى: {total_fetched} سيارة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 2: SALVAGEBID.COM (ACV listings بدون credentials)
# ══════════════════════════════════════════════════════════════════════════

def _fetch_acv_via_salvagebid(
    make_filter: str = "",
    max_pages: int = 10,
    delay: float = 2.0,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    يجلب سيارات ACV من salvagebid.com — يعمل بدون credentials.
    SalvageBid يعرض سيارات ACV ضمن نتائجه.
    """
    if existing_lots is None:
        existing_lots = set()

    session = _make_session()
    session.headers.update({
        "Referer": "https://www.salvagebid.com/en/search",
        "Origin": "https://www.salvagebid.com",
    })

    # جلب الكوكيز أولاً
    try:
        session.get("https://www.salvagebid.com/en/search", timeout=15)
        time.sleep(1)
    except Exception:
        pass

    all_cars = []
    page = 1
    per_page = 26
    total_fetched = 0
    consecutive_errors = 0

    log_fn(f"  [SALVAGEBID-ACV] بدء الجلب... (make={make_filter or 'الكل'})")

    while True:
        if max_pages > 0 and page > max_pages:
            break

        params = {
            "page": page,
            "per_page": per_page,
            "auction": "acv",  # فلتر ACV فقط
            "status": "active",
        }
        if make_filter:
            params["make"] = make_filter.upper()

        try:
            resp = session.get(SALVAGEBID_ACV_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [SALVAGEBID-ACV] خطأ في الصفحة {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            time.sleep(delay * 2)
            continue

        consecutive_errors = 0
        items = data.get("lots", []) or data.get("data", []) or []

        if not items:
            log_fn(f"  [SALVAGEBID-ACV] لا توجد نتائج — انتهى")
            break

        for item in items:
            # تأكد أن المصدر ACV
            source = (item.get("auction_name", "") or "").upper()
            if source and "ACV" not in source:
                continue

            lot_raw = str(item.get("lot_number", "") or item.get("lot", ""))
            if not lot_raw:
                continue

            lot = f"{lot_raw}-ACV" if not lot_raw.endswith("-ACV") else lot_raw
            if lot in existing_lots:
                continue

            car = {
                "lot_number": lot,
                "vin": _safe_str(item.get("vin", ""), 50),
                "make": _safe_str(item.get("make", ""), 50),
                "model": _safe_str(item.get("model", ""), 50),
                "year": _safe_int(item.get("year")),
                "color": _safe_str(item.get("color", ""), 50),
                "damage": _safe_str(item.get("damage", ""), 1024),
                "secondary_damage": _safe_str(item.get("secondary_damage", ""), 1024),
                "odometer": _safe_str(item.get("odometer", ""), 50),
                "odometer_brand": _safe_str(item.get("odometer_brand", "miles"), 50),
                "engine": _safe_str(item.get("engine", ""), 50),
                "drive": _safe_str(item.get("drive", ""), 50),
                "transmission": _safe_str(item.get("transmission", ""), 50),
                "fuel": _safe_str(item.get("fuel", ""), 50),
                "body_style": _safe_str(item.get("body_style", ""), 50),
                "sale_status": "active",
                "current_bid": _safe_str(item.get("high_bid", "") or item.get("current_bid", ""), 50),
                "buy_now": _safe_str(item.get("buy_now", ""), 50),
                "city": _safe_str(item.get("city", ""), 1024),
                "state": _safe_str(item.get("state", ""), 1024),
                "zip": _safe_str(item.get("zip", ""), 1024),
                "thumbnail": _safe_str(item.get("thumbnail", "") or item.get("image", ""), 1024),
                "trim": _safe_str(item.get("trim", ""), 1024),
                "sale_date": _safe_str(item.get("sale_date", ""), 50),
                "min_price": "",
                "note": f"Via SalvageBid | ACV Lot: {lot_raw}",
                "est_retail": _safe_str(item.get("est_retail", ""), 50),
                "title_type": _safe_str(item.get("title_type", ""), 1024),
                "keys": _safe_str(item.get("keys", ""), 50),
                "runs_drives": _safe_str(item.get("runs_drives", ""), 1024),
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [SALVAGEBID-ACV] صفحة {page}: {len(items)} سيارة، إجمالي جديد: {total_fetched}")

        total_count = data.get("total", 0)
        if total_count and page * per_page >= total_count:
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [SALVAGEBID-ACV] ✓ انتهى: {total_fetched} سيارة جديدة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 3: BID.CARS (ACV listings - fallback)
# ══════════════════════════════════════════════════════════════════════════

def _fetch_acv_via_bidcars(
    make_filter: str = "",
    max_pages: int = 5,
    delay: float = 2.0,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    يجلب سيارات ACV من bid.cars — مصدر بديل موثوق.
    """
    if existing_lots is None:
        existing_lots = set()

    session = _make_session()
    session.headers.update({
        "Referer": "https://bid.cars/en/search/results",
        "X-Requested-With": "XMLHttpRequest",
    })

    all_cars = []
    page = 1
    total_fetched = 0
    consecutive_errors = 0

    log_fn(f"  [BID.CARS-ACV] بدء الجلب...")

    while True:
        if max_pages > 0 and page > max_pages:
            break

        params = {
            "auction": "acv",
            "page": page,
            "per_page": 25,
            "status": "active",
        }
        if make_filter:
            params["make"] = make_filter

        try:
            resp = session.get(BIDCARS_ACV_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [BID.CARS-ACV] خطأ في الصفحة {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            time.sleep(delay * 2)
            continue

        consecutive_errors = 0
        items = data.get("lots", []) or data.get("results", []) or []

        if not items:
            break

        for item in items:
            lot_raw = str(item.get("lot_number", "") or item.get("lot", ""))
            if not lot_raw:
                continue

            lot = f"{lot_raw}-ACV" if not lot_raw.endswith("-ACV") else lot_raw
            if lot in existing_lots:
                continue

            car = {
                "lot_number": lot,
                "vin": _safe_str(item.get("vin", ""), 50),
                "make": _safe_str(item.get("make", ""), 50),
                "model": _safe_str(item.get("model", ""), 50),
                "year": _safe_int(item.get("year")),
                "color": _safe_str(item.get("color", ""), 50),
                "damage": _safe_str(item.get("damage", ""), 1024),
                "secondary_damage": "",
                "odometer": _safe_str(item.get("odometer", ""), 50),
                "odometer_brand": "miles",
                "engine": _safe_str(item.get("engine", ""), 50),
                "drive": "",
                "transmission": _safe_str(item.get("transmission", ""), 50),
                "fuel": _safe_str(item.get("fuel", ""), 50),
                "body_style": _safe_str(item.get("body_style", ""), 50),
                "sale_status": "active",
                "current_bid": _safe_str(item.get("high_bid", ""), 50),
                "buy_now": _safe_str(item.get("buy_now", ""), 50),
                "city": _safe_str(item.get("city", ""), 1024),
                "state": _safe_str(item.get("state", ""), 1024),
                "zip": "",
                "thumbnail": _safe_str(item.get("thumbnail", ""), 1024),
                "trim": _safe_str(item.get("trim", ""), 1024),
                "sale_date": _safe_str(item.get("sale_date", ""), 50),
                "min_price": "",
                "note": f"Via bid.cars | ACV Lot: {lot_raw}",
                "est_retail": "",
                "title_type": _safe_str(item.get("title_type", ""), 1024),
                "keys": _safe_str(item.get("keys", ""), 50),
                "runs_drives": _safe_str(item.get("runs_drives", ""), 1024),
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [BID.CARS-ACV] صفحة {page}: {len(items)} سيارة، إجمالي جديد: {total_fetched}")

        if not data.get("has_next", False) and not data.get("next_page"):
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [BID.CARS-ACV] ✓ انتهى: {total_fetched} سيارة جديدة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  DJANGO MANAGEMENT COMMAND
# ══════════════════════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = "جلب سيارات ACV Auctions عبر API مباشر (بدون Playwright)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="all",
            choices=["all", "direct", "salvagebid", "bidcars"],
            help="المصدر: all | direct | salvagebid | bidcars (افتراضي: all)",
        )
        parser.add_argument(
            "--make",
            type=str,
            default="",
            help="فلتر الشركة المصنّعة (مثال: Toyota, BMW)",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=10,
            help="أقصى عدد صفحات لكل مصدر (0 = كل الصفحات، افتراضي: 10)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.5,
            help="التأخير بين الطلبات بالثواني (افتراضي: 1.5)",
        )
        parser.add_argument(
            "--resume",
            action="store_true",
            default=False,
            help="تخطي اللوتات الموجودة مسبقاً",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="جلب البيانات فقط بدون حفظ في قاعدة البيانات",
        )

    def handle(self, *args, **options):
        source = options["source"]
        make = options["make"]
        max_pages = options["max_pages"]
        delay = options["delay"]
        resume = options["resume"]
        dry_run = options["dry_run"]

        def log(msg):
            self.stdout.write(msg)

        t0 = time.time()
        db_path = settings.DATABASES["default"]["NAME"]

        # ACV credentials من settings
        acv_username = getattr(settings, "ACV_USERNAME", "") or ""
        acv_password = getattr(settings, "ACV_PASSWORD", "") or ""

        log("=" * 65)
        log("  ACV API SYNC — مزامنة ACV Auctions")
        log("=" * 65)
        log(f"  المصدر:      {source}")
        log(f"  الشركة:      {make or 'الكل'}")
        log(f"  أقصى صفحات: {max_pages or 'كل الصفحات'}")
        log(f"  Credentials: {'✓ متوفرة' if acv_username else '✗ غير متوفرة'}")
        log(f"  استئناف:     {'نعم' if resume else 'لا'}")
        log(f"  تجريبي:      {'نعم (لا حفظ)' if dry_run else 'لا'}")
        log("-" * 65)

        existing_lots: Set[str] = set()
        if resume:
            existing_lots = _get_existing_lots(db_path)
            log(f"  لوتات ACV موجودة: {len(existing_lots)}")

        total_new = 0
        total_saved = 0
        sources_used = []

        # ── ACV Direct (إذا توفرت credentials) ──
        if source in ("all", "direct") and acv_username:
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 1: ACV Direct API                ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_acv_direct(
                    username=acv_username,
                    password=acv_password,
                    make_filter=make,
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [ACV-DIRECT] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"ACV Direct ({saved})")
                    else:
                        sources_used.append(f"ACV Direct ({len(cars)} dry)")
            except Exception as e:
                log(f"  [ACV-DIRECT] خطأ: {e}")

        # ── SalvageBid ACV ──
        if source in ("all", "salvagebid"):
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 2: SalvageBid (ACV listings)     ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_acv_via_salvagebid(
                    make_filter=make,
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [SALVAGEBID-ACV] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"SalvageBid ({saved})")
                    else:
                        sources_used.append(f"SalvageBid ({len(cars)} dry)")
                else:
                    log("  [SALVAGEBID-ACV] لا توجد سيارات جديدة")
            except Exception as e:
                log(f"  [SALVAGEBID-ACV] خطأ: {e}")

        # ── bid.cars ACV ──
        if source in ("all", "bidcars"):
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 3: bid.cars (ACV fallback)       ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_acv_via_bidcars(
                    make_filter=make,
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [BID.CARS-ACV] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"bid.cars ({saved})")
                    else:
                        sources_used.append(f"bid.cars ({len(cars)} dry)")
                else:
                    log("  [BID.CARS-ACV] لا توجد سيارات جديدة")
            except Exception as e:
                log(f"  [BID.CARS-ACV] خطأ: {e}")

        # ── ملخص ──
        elapsed = time.time() - t0
        log("")
        log("=" * 65)
        log("  FINAL SUMMARY — الملخص النهائي")
        log("=" * 65)
        log(f"  إجمالي السيارات الجديدة: {total_new}")
        log(f"  إجمالي المحفوظ في DB:   {total_saved}")
        log(f"  المصادر المستخدمة:      {', '.join(sources_used) or 'لا شيء'}")
        log(f"  الوقت المستغرق:         {elapsed:.0f}s ({elapsed / 60:.1f} دقيقة)")
        log(f"  انتهى في:               {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log("=" * 65)

        if total_saved > 0:
            self.stdout.write(self.style.SUCCESS(
                f"\n  ✓ نجاح: تم استيراد {total_saved} سيارة ACV جديدة!"
            ))
        elif dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n  ℹ وضع تجريبي: {total_new} سيارة جاهزة للحفظ"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "\n  ⚠ لا توجد سيارات جديدة"
            ))

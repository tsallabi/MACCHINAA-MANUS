"""
korea_sync.py — جلب السيارات من المزادات الكورية
══════════════════════════════════════════════════
المصادر:
  1. Encar.com     — أكبر سوق سيارات مستعملة في كوريا (API مفتوح)
  2. KCar.com      — ثاني أكبر سوق كوري (API مفتوح)
  3. Glovis Korea  — مزاد هيونداي/كيا (موجود في all_auctions)
  4. AJ Auction    — مزاد كوري متخصص (موجود في all_auctions)

الاستخدام:
    python manage.py korea_sync
    python manage.py korea_sync --source encar
    python manage.py korea_sync --source kcar
    python manage.py korea_sync --make Toyota --max-pages 5
    python manage.py korea_sync --dry-run
    python manage.py korea_sync --resume

ملاحظة:
  - يحفظ في جدول ManualCarData بنفس أسلوب iaai_full_sync
  - Yard_name = "Encar Korea" / "KCar Korea" / "Glovis Korea" / "AJ Korea"
  - Currency_Code = "KRW" مع تحويل تلقائي للدولار
  - Location_country = "KR"
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

KRW_TO_USD = 0.000735   # 1 KRW ≈ 0.000735 USD (يُحدَّث من API إذا أمكن)
MAN_WON_TO_USD = 7.35   # 1 만원 (10,000 KRW) ≈ 7.35 USD

ENCAR_SEARCH_URL = "https://api.encar.com/search/car/list/general"
ENCAR_DETAIL_URL = "https://api.encar.com/v1/readside/vehicle/{car_id}"

KCAR_SEARCH_URL  = "https://api.kcar.com/bc/car/usedList"
KCAR_DETAIL_URL  = "https://api.kcar.com/bc/car/usedDetail/{car_id}"

GLOVIS_SEARCH_URL = "https://www.glovisusedcar.com/api/v1/vehicles"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.encar.com/",
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


def _get_exchange_rate() -> float:
    """يجلب سعر صرف KRW/USD الحالي من exchangerate-api."""
    try:
        r = requests.get(
            "https://api.exchangerate-api.com/v4/latest/KRW",
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            rate = data.get("rates", {}).get("USD", 0)
            if rate > 0:
                return rate
    except Exception:
        pass
    return KRW_TO_USD  # fallback


def _man_won_to_usd(man_won_value: Any, rate: float) -> str:
    """يحوّل قيمة 만원 (10,000 وون) إلى دولار."""
    try:
        val = float(str(man_won_value).replace(",", "").strip())
        # Encar يعطي القيمة بـ 만원 (مضروبة في 10000 للحصول على KRW)
        krw = val * 10_000
        usd = krw * rate
        return f"${usd:,.0f}"
    except Exception:
        return ""


def _safe_str(val: Any, max_len: int = 50) -> str:
    if val is None:
        return ""
    return str(val).strip()[:max_len]


def _safe_int(val: Any) -> Optional[int]:
    try:
        return int(str(val).replace(",", "").strip())
    except Exception:
        return None


def _normalize_fuel(fuel: str) -> str:
    fuel = (fuel or "").lower()
    mapping = {
        "가솔린": "Gasoline",
        "디젤": "Diesel",
        "lpi": "LPG",
        "lpg": "LPG",
        "전기": "Electric",
        "하이브리드": "Hybrid",
        "수소": "Hydrogen",
    }
    for k, v in mapping.items():
        if k in fuel:
            return v
    return fuel.capitalize() or "Gasoline"


def _normalize_transmission(trans: str) -> str:
    trans = (trans or "").lower()
    if "자동" in trans or "auto" in trans:
        return "Automatic"
    if "수동" in trans or "manual" in trans:
        return "Manual"
    return trans.capitalize() or "Automatic"


def _get_existing_lots(db_path: str, yard_names: List[str]) -> Set[str]:
    """يجلب أرقام اللوتات الموجودة مسبقاً لتجنب التكرار."""
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        placeholders = ",".join("?" * len(yard_names))
        rows = conn.execute(
            f'SELECT Lot_number FROM "ManualCarData" WHERE Yard_name IN ({placeholders})',
            yard_names
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning("Could not fetch existing lots: %s", e)
        return set()


def _save_to_db(cars: List[Dict], db_path: str, log_fn=print) -> int:
    """يحفظ السيارات في ManualCarData بنفس أسلوب iaai_full_sync."""
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
                lot,                                            # Lot_number
                _safe_str(car.get("vin", ""), 50),             # VIN
                _safe_str(car.get("make", ""), 50),            # Make
                _safe_str(car.get("model", ""), 50),           # Model_Detail
                _safe_int(car.get("year")),                     # Year
                _safe_str(car.get("color", ""), 50),           # Color
                _safe_str(car.get("damage", ""), 1024),        # Damage_Description
                "",                                             # Secondary_Damage
                _safe_str(car.get("odometer", ""), 50),        # Odometer
                _safe_str(car.get("odometer_unit", "km"), 50), # Odometer_Brand
                _safe_str(car.get("engine", ""), 50),          # Engine
                _safe_str(car.get("drive", ""), 50),           # Drive
                _safe_str(car.get("transmission", ""), 50),    # Transmission
                _safe_str(car.get("fuel", ""), 50),            # Fuel_Type
                _safe_str(car.get("body_style", ""), 50),      # Body_Style
                "active",                                       # Sale_Status
                _safe_str(car.get("price_krw", ""), 50),       # High_Bid_non_vix_Sealed_Vix
                _safe_str(car.get("buy_now", ""), 50),         # Buy_It_Now_Price
                _safe_str(car.get("city", ""), 1024),          # Location_city
                _safe_str(car.get("state", ""), 1024),         # Location_state
                "",                                             # Location_ZIP
                "KR",                                           # Location_country
                "KRW",                                          # Currency_Code
                _safe_str(car.get("thumbnail", ""), 1024),     # Image_Thumbnail
                _safe_str(car.get("thumbnail", ""), 100),      # Image_URL
                _safe_str(car.get("trim", ""), 1024),          # Trim
                _safe_str(car.get("sale_date", ""), 50),       # Sale_Date_M_D_CY
                "",                                             # Minimum_Price
                _safe_str(car.get("note", ""), 1024),          # Special_Note
                _safe_str(car.get("yard_name", ""), 1024),     # Yard_name
                _safe_str(car.get("price_usd", ""), 50),       # Est_Retail_Value
                _safe_str(car.get("model_group", ""), 50),     # Model_Group
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
                     "Yard_name", "Est_Retail_Value", "Model_Group")
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ''', params_list)
                saved += conn.execute("SELECT changes()").fetchone()[0]
            except Exception as e:
                log_fn(f"  [DB ERROR] {e}")

        conn.commit()

    conn.close()
    return saved


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 1: ENCAR.COM
# ══════════════════════════════════════════════════════════════════════════

def _fetch_encar(
    make_filter: str = "",
    max_pages: int = 20,
    delay: float = 1.0,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
    exchange_rate: float = KRW_TO_USD,
) -> List[Dict]:
    """
    يجلب السيارات من Encar.com عبر API المفتوح.
    الـ API يعيد بيانات JSON مباشرة بدون مصادقة.
    """
    if existing_lots is None:
        existing_lots = set()

    session = _make_session()
    session.headers.update({"Referer": "https://www.encar.com/"})

    all_cars = []
    page = 0
    per_page = 20
    total_fetched = 0
    consecutive_errors = 0

    log_fn(f"  [ENCAR] بدء الجلب... (make={make_filter or 'الكل'}, max_pages={max_pages})")

    while True:
        if max_pages > 0 and page >= max_pages:
            break

        params = {
            "count": "true",
            "q": f"(And.Hidden.N._.CarType.Y.{f'_.Make.{make_filter}.' if make_filter else ''})",
            "sr": f"|ModifiedDate|{page * per_page}|{per_page}",
        }

        try:
            resp = session.get(ENCAR_SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [ENCAR] خطأ في الصفحة {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 3:
                log_fn("  [ENCAR] 3 أخطاء متتالية — إيقاف")
                break
            time.sleep(delay * 2)
            continue

        consecutive_errors = 0
        items = data.get("SearchResults", [])
        if not items:
            log_fn(f"  [ENCAR] لا توجد نتائج في الصفحة {page} — انتهى")
            break

        for item in items:
            car_id = str(item.get("Id", ""))
            if not car_id:
                continue

            lot = f"ENCAR-{car_id}"
            if lot in existing_lots:
                continue

            # استخراج البيانات
            category = item.get("Category", {}) or {}
            spec = item.get("Spec", {}) or {}
            ad = item.get("Ad", {}) or {}
            photos = item.get("Photos", []) or []

            make_raw = category.get("Manufacturer", "") or ""
            model_raw = category.get("ModelGroup", "") or ""
            detail_raw = category.get("Model", "") or ""
            year_raw = spec.get("Year", None)
            fuel_raw = spec.get("FuelType", "") or ""
            trans_raw = spec.get("Transmission", "") or ""
            mileage_raw = spec.get("Mileage", None)
            color_raw = spec.get("Color", "") or ""
            engine_raw = spec.get("Displacement", "") or ""
            price_raw = ad.get("Price", 0) or 0  # بالـ 만원

            # تحويل الصورة
            thumbnail = ""
            if photos:
                first_photo = photos[0] if isinstance(photos[0], str) else photos[0].get("location", "")
                if first_photo:
                    thumbnail = f"https://ci.encar.com/carpicture{first_photo}"

            # تحويل السعر
            price_usd = _man_won_to_usd(price_raw, exchange_rate)
            price_krw = f"{int(price_raw) * 10000:,} KRW" if price_raw else ""

            car = {
                "lot_number": lot,
                "vin": "",
                "make": make_raw,
                "model_group": model_raw,
                "model": detail_raw or model_raw,
                "year": _safe_int(year_raw),
                "color": color_raw,
                "damage": "중고차 (Used)",
                "odometer": str(mileage_raw) if mileage_raw else "",
                "odometer_unit": "km",
                "engine": f"{engine_raw}cc" if engine_raw else "",
                "drive": "",
                "transmission": _normalize_transmission(trans_raw),
                "fuel": _normalize_fuel(fuel_raw),
                "body_style": category.get("Grade", "") or "",
                "price_krw": price_krw,
                "price_usd": price_usd,
                "buy_now": price_usd,
                "city": ad.get("Garage", {}).get("Name", "") if isinstance(ad.get("Garage"), dict) else "",
                "state": "",
                "thumbnail": thumbnail,
                "trim": detail_raw,
                "sale_date": "",
                "yard_name": "Encar Korea",
                "note": f"Encar ID: {car_id}",
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [ENCAR] صفحة {page + 1}: {len(items)} سيارة، إجمالي جديد: {total_fetched}")

        # تحقق من وجود صفحات أخرى
        total_count = data.get("Count", 0)
        if (page + 1) * per_page >= total_count:
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [ENCAR] ✓ انتهى: {total_fetched} سيارة جديدة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 2: KCAR.COM
# ══════════════════════════════════════════════════════════════════════════

def _fetch_kcar(
    make_filter: str = "",
    max_pages: int = 10,
    delay: float = 1.5,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
    exchange_rate: float = KRW_TO_USD,
) -> List[Dict]:
    """
    يجلب السيارات من KCar.com.
    KCar هو ثاني أكبر سوق سيارات مستعملة في كوريا.
    """
    if existing_lots is None:
        existing_lots = set()

    session = _make_session()
    session.headers.update({
        "Referer": "https://www.kcar.com/",
        "Origin": "https://www.kcar.com",
    })

    all_cars = []
    page = 1
    per_page = 20
    total_fetched = 0
    consecutive_errors = 0

    log_fn(f"  [KCAR] بدء الجلب... (max_pages={max_pages})")

    while True:
        if max_pages > 0 and page > max_pages:
            break

        params = {
            "pageNo": page,
            "pageSize": per_page,
            "sortType": "NEW",
            "carType": "A",  # A = All
        }
        if make_filter:
            params["brandNm"] = make_filter

        try:
            resp = session.get(KCAR_SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [KCAR] خطأ في الصفحة {page}: {e}")
            consecutive_errors += 1
            if consecutive_errors >= 3:
                break
            time.sleep(delay * 2)
            continue

        consecutive_errors = 0

        # KCar API structure
        result = data.get("data", {}) or data
        items = result.get("list", []) or result.get("carList", []) or []

        if not items:
            log_fn(f"  [KCAR] لا توجد نتائج في الصفحة {page} — انتهى")
            break

        for item in items:
            car_id = str(item.get("carNo", "") or item.get("carId", ""))
            if not car_id:
                continue

            lot = f"KCAR-{car_id}"
            if lot in existing_lots:
                continue

            make_raw = item.get("brandNm", "") or item.get("mfcNm", "") or ""
            model_raw = item.get("modelNm", "") or item.get("carNm", "") or ""
            year_raw = item.get("frmYyyy", "") or item.get("year", "")
            color_raw = item.get("colorNm", "") or ""
            mileage_raw = item.get("driveDist", "") or item.get("mileage", "")
            fuel_raw = item.get("fuelNm", "") or ""
            trans_raw = item.get("mssNm", "") or ""
            price_raw = item.get("slAmt", 0) or item.get("price", 0) or 0
            thumbnail = item.get("repCarImgUrl", "") or item.get("imgUrl", "") or ""
            city_raw = item.get("locNm", "") or item.get("location", "") or ""

            # تحويل السعر (KCar يعطي بالـ 만원 أيضاً)
            price_usd = _man_won_to_usd(price_raw, exchange_rate)
            price_krw = f"{int(price_raw) * 10000:,} KRW" if price_raw else ""

            car = {
                "lot_number": lot,
                "vin": item.get("vin", "") or "",
                "make": make_raw,
                "model_group": model_raw,
                "model": model_raw,
                "year": _safe_int(year_raw),
                "color": color_raw,
                "damage": "중고차 (Used)",
                "odometer": str(mileage_raw).replace(",", "") if mileage_raw else "",
                "odometer_unit": "km",
                "engine": item.get("dsplNm", "") or "",
                "drive": item.get("drvMdNm", "") or "",
                "transmission": _normalize_transmission(trans_raw),
                "fuel": _normalize_fuel(fuel_raw),
                "body_style": item.get("carKindNm", "") or "",
                "price_krw": price_krw,
                "price_usd": price_usd,
                "buy_now": price_usd,
                "city": city_raw,
                "state": "",
                "thumbnail": thumbnail,
                "trim": item.get("gradeNm", "") or "",
                "sale_date": "",
                "yard_name": "KCar Korea",
                "note": f"KCar ID: {car_id}",
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [KCAR] صفحة {page}: {len(items)} سيارة، إجمالي جديد: {total_fetched}")

        total_count = result.get("totalCount", 0) or result.get("total", 0)
        if total_count and page * per_page >= total_count:
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [KCAR] ✓ انتهى: {total_fetched} سيارة جديدة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 3: GLOVIS KOREA (Hyundai/Kia Auction)
# ══════════════════════════════════════════════════════════════════════════

def _fetch_glovis(
    max_pages: int = 5,
    delay: float = 2.0,
    log_fn=print,
    existing_lots: Optional[Set[str]] = None,
    exchange_rate: float = KRW_TO_USD,
) -> List[Dict]:
    """
    يجلب السيارات من Hyundai Glovis Used Car.
    Glovis هو الذراع اللوجستي لمجموعة Hyundai/Kia.
    """
    if existing_lots is None:
        existing_lots = set()

    session = _make_session()
    session.headers.update({"Referer": "https://www.glovisusedcar.com/"})

    all_cars = []
    page = 1
    total_fetched = 0

    log_fn(f"  [GLOVIS] بدء الجلب... (max_pages={max_pages})")

    while True:
        if max_pages > 0 and page > max_pages:
            break

        params = {
            "page": page,
            "size": 20,
            "sort": "regDt,desc",
            "saleYn": "Y",
        }

        try:
            resp = session.get(GLOVIS_SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_fn(f"  [GLOVIS] خطأ في الصفحة {page}: {e}")
            # Glovis قد يكون محمياً — نتوقف بهدوء
            break

        items = data.get("content", []) or data.get("data", []) or []
        if not items:
            break

        for item in items:
            car_id = str(item.get("vhclNo", "") or item.get("id", ""))
            if not car_id:
                continue

            lot = f"GLOVIS-{car_id}"
            if lot in existing_lots:
                continue

            make_raw = item.get("mkerNm", "") or item.get("brand", "") or "Hyundai/Kia"
            model_raw = item.get("carNm", "") or item.get("model", "") or ""
            year_raw = item.get("mfgYr", "") or item.get("year", "")
            price_raw = item.get("slAmt", 0) or item.get("price", 0) or 0
            mileage_raw = item.get("drvDist", "") or item.get("mileage", "")
            thumbnail = item.get("repImgUrl", "") or item.get("imgUrl", "") or ""
            color_raw = item.get("colorNm", "") or ""
            fuel_raw = item.get("fuelNm", "") or ""

            price_usd = _man_won_to_usd(price_raw, exchange_rate)
            price_krw = f"{int(price_raw) * 10000:,} KRW" if price_raw else ""

            car = {
                "lot_number": lot,
                "vin": item.get("vin", "") or "",
                "make": make_raw,
                "model_group": model_raw,
                "model": model_raw,
                "year": _safe_int(year_raw),
                "color": color_raw,
                "damage": "중고차 (Used)",
                "odometer": str(mileage_raw).replace(",", "") if mileage_raw else "",
                "odometer_unit": "km",
                "engine": item.get("dsplNm", "") or "",
                "drive": "",
                "transmission": _normalize_transmission(item.get("mssNm", "") or ""),
                "fuel": _normalize_fuel(fuel_raw),
                "body_style": item.get("carKndNm", "") or "",
                "price_krw": price_krw,
                "price_usd": price_usd,
                "buy_now": price_usd,
                "city": item.get("locNm", "") or "",
                "state": "",
                "thumbnail": thumbnail,
                "trim": item.get("gradeNm", "") or "",
                "sale_date": "",
                "yard_name": "Glovis Korea",
                "note": f"Glovis ID: {car_id}",
            }
            all_cars.append(car)
            existing_lots.add(lot)
            total_fetched += 1

        log_fn(f"  [GLOVIS] صفحة {page}: {len(items)} سيارة، إجمالي جديد: {total_fetched}")

        total_pages = data.get("totalPages", 1)
        if page >= total_pages:
            break

        page += 1
        time.sleep(delay)

    log_fn(f"  [GLOVIS] ✓ انتهى: {total_fetched} سيارة جديدة")
    return all_cars


# ══════════════════════════════════════════════════════════════════════════
#  DJANGO MANAGEMENT COMMAND
# ══════════════════════════════════════════════════════════════════════════

class Command(BaseCommand):
    help = "جلب السيارات من المزادات الكورية (Encar + KCar + Glovis)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            default="all",
            choices=["all", "encar", "kcar", "glovis"],
            help="المصدر: all | encar | kcar | glovis (افتراضي: all)",
        )
        parser.add_argument(
            "--make",
            type=str,
            default="",
            help="فلتر الشركة المصنّعة (مثال: Toyota, Hyundai)",
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
            default=1.0,
            help="التأخير بين الطلبات بالثواني (افتراضي: 1.0)",
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

        log("=" * 65)
        log("  KOREA SYNC — مزامنة المزادات الكورية")
        log("=" * 65)
        log(f"  المصدر:     {source}")
        log(f"  الشركة:     {make or 'الكل'}")
        log(f"  أقصى صفحات: {max_pages or 'كل الصفحات'}")
        log(f"  استئناف:    {'نعم' if resume else 'لا'}")
        log(f"  تجريبي:     {'نعم (لا حفظ)' if dry_run else 'لا'}")
        log("-" * 65)

        # جلب سعر الصرف الحالي
        log("  جلب سعر صرف KRW/USD...")
        exchange_rate = _get_exchange_rate()
        log(f"  سعر الصرف: 1 KRW = {exchange_rate:.6f} USD")
        log(f"  (1 만원 = {exchange_rate * 10000:.2f} USD)")

        # جلب اللوتات الموجودة إذا طُلب الاستئناف
        existing_lots: Set[str] = set()
        if resume:
            existing_lots = _get_existing_lots(
                db_path,
                ["Encar Korea", "KCar Korea", "Glovis Korea", "AJ Korea"]
            )
            log(f"  لوتات موجودة: {len(existing_lots)}")

        total_new = 0
        total_saved = 0
        sources_used = []

        # ── Encar ──
        if source in ("all", "encar"):
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 1: Encar.com (أكبر سوق كوري)    ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_encar(
                    make_filter=make,
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                    exchange_rate=exchange_rate,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [ENCAR] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"Encar ({saved})")
                    else:
                        log(f"  [ENCAR] تجريبي: {len(cars)} سيارة (لم تُحفظ)")
                        sources_used.append(f"Encar ({len(cars)} dry)")
                else:
                    log("  [ENCAR] لا توجد سيارات جديدة")
            except Exception as e:
                log(f"  [ENCAR] خطأ: {e}")
                import traceback
                log(traceback.format_exc())

        # ── KCar ──
        if source in ("all", "kcar"):
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 2: KCar.com (ثاني أكبر سوق)     ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_kcar(
                    make_filter=make,
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                    exchange_rate=exchange_rate,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [KCAR] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"KCar ({saved})")
                    else:
                        log(f"  [KCAR] تجريبي: {len(cars)} سيارة (لم تُحفظ)")
                        sources_used.append(f"KCar ({len(cars)} dry)")
                else:
                    log("  [KCAR] لا توجد سيارات جديدة")
            except Exception as e:
                log(f"  [KCAR] خطأ: {e}")

        # ── Glovis ──
        if source in ("all", "glovis"):
            log("")
            log("  ╔══════════════════════════════════════════╗")
            log("  ║  SOURCE 3: Glovis Korea (Hyundai/Kia)   ║")
            log("  ╚══════════════════════════════════════════╝")
            try:
                cars = _fetch_glovis(
                    max_pages=max_pages,
                    delay=delay,
                    log_fn=log,
                    existing_lots=existing_lots,
                    exchange_rate=exchange_rate,
                )
                if cars:
                    total_new += len(cars)
                    if not dry_run:
                        saved = _save_to_db(cars, db_path, log_fn=log)
                        total_saved += saved
                        log(f"  [GLOVIS] ✓ حُفظ {saved} سيارة")
                        sources_used.append(f"Glovis ({saved})")
                    else:
                        log(f"  [GLOVIS] تجريبي: {len(cars)} سيارة (لم تُحفظ)")
                        sources_used.append(f"Glovis ({len(cars)} dry)")
                else:
                    log("  [GLOVIS] لا توجد سيارات جديدة")
            except Exception as e:
                log(f"  [GLOVIS] خطأ: {e}")

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
                f"\n  ✓ نجاح: تم استيراد {total_saved} سيارة كورية جديدة!"
            ))
        elif dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n  ℹ وضع تجريبي: {total_new} سيارة جاهزة للحفظ"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "\n  ⚠ لا توجد سيارات جديدة (كل اللوتات موجودة مسبقاً)"
            ))

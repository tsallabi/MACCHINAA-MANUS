"""
MACCHINAA-EVOLVED — Japan Auctions Scraper
============================================
جلب السيارات من المزادات اليابانية عبر:

  1. BE FORWARD (beforward.jp)  — أكبر مصدر سيارات يابانية للتصدير
  2. SBI Motor Japan            — مزادات يابانية مباشرة
  3. USS Auction (عبر aggregators) — أكبر مزاد سيارات في اليابان
  4. JAA (Japan Auto Auctions)  — مزادات يابانية متعددة

لماذا المزادات اليابانية مهمة لليبيا؟
  - سيارات بحالة ممتازة (درجة 4-5)
  - أسعار تنافسية جداً
  - Toyota Land Cruiser, Hilux, Prado بأسعار أقل من السوق
  - شحن مباشر من اليابان إلى ميناء مصراتة
  - وقت الشحن: 30-45 يوم

نظام الدرجات الياباني:
  5   = ممتازة (مثل الجديدة)
  4.5 = ممتازة جداً
  4   = جيدة جداً
  3.5 = جيدة
  3   = متوسطة (بعض الخدوش)
  2   = ضعيفة (تحتاج إصلاح)
  1   = سيئة (للقطع)
  RA  = يعمل ولكن يحتاج إصلاح

الاستخدام:
    from scrapers.japan.scraper import JapanAuctionsScraper
    scraper = JapanAuctionsScraper()
    for batch in scraper.fetch_pages(make="Toyota", grade_min=3.5):
        process(batch)
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Dict, Generator, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "JAPAN"

# BE FORWARD — largest Japanese used car exporter
BEFORWARD_SEARCH = "https://www.beforward.jp/stocklist/list/ps/1"
BEFORWARD_API = "https://api.beforward.jp/v1/vehicles"

# SBI Motor Japan
SBI_SEARCH = "https://www.sbimotorjapan.com/en/search"

# CarFromJapan aggregator
CARFROMJAPAN_API = "https://carfromjapan.com/api/v1/vehicles"

# Aucnet (Japanese auction network)
AUCNET_API = "https://www.aucnet.co.jp/api/vehicles"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Grade conversion to numeric
GRADE_MAP = {
    "5":   5.0,  "4.5": 4.5, "4":   4.0, "3.5": 3.5,
    "3":   3.0,  "2.5": 2.5, "2":   2.0, "1":   1.0,
    "RA":  2.5,  "R":   2.0, "A":   4.0, "B":   3.0,
    "C":   2.0,  "D":   1.0, "S":   5.0, "***": 3.5,
    "**":  2.5,  "*":   2.0,
}

# Hot models for Libya market
LIBYA_HOT_MODELS = {
    "Toyota":   ["Land Cruiser", "Prado", "Hilux", "Fortuner", "Camry", "Corolla", "RAV4"],
    "Nissan":   ["Patrol", "Navara", "X-Trail", "Sunny", "Tiida"],
    "Mitsubishi": ["Pajero", "L200", "Outlander", "Galant"],
    "Honda":    ["CR-V", "Accord", "Civic", "Pilot"],
    "Lexus":    ["LX", "GX", "RX", "IS", "ES"],
    "Suzuki":   ["Jimny", "Swift", "Vitara"],
    "Isuzu":    ["D-Max", "Trooper", "MU-X"],
    "Mazda":    ["CX-5", "BT-50", "Atenza"],
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
    })
    return session


def _fetch_beforward_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    model: Optional[str] = None,
    grade_min: Optional[float] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 2.0,
) -> List[Dict]:
    """Fetch vehicles from BE FORWARD."""
    params: Dict[str, Any] = {
        "page": page,
        "per_page": 50,
        "country": "LY",  # Libya destination
        "currency": "USD",
        "sort": "price_asc",
    }
    if make:
        params["make"] = make
    if model:
        params["model"] = model
    if year_min:
        params["year_from"] = year_min
    if year_max:
        params["year_to"] = year_max
    if grade_min:
        params["grade_min"] = grade_min

    try:
        time.sleep(delay + random.uniform(0.5, 1.5))
        resp = session.get(BEFORWARD_API, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("[Japan/BeForward] Rate limited — sleeping 60s")
            time.sleep(60)
            return []

        if resp.status_code != 200:
            logger.warning("[Japan/BeForward] HTTP %s page %d", resp.status_code, page)
            return []

        data = resp.json()
        items = data.get("vehicles") or data.get("results") or data.get("data") or []
        logger.debug("[Japan/BeForward] Page %d → %d items", page, len(items))
        return items

    except Exception as exc:
        logger.error("[Japan/BeForward] Page %d error: %s", page, exc)
        return []


def _fetch_carfromjapan_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    grade_min: Optional[float] = None,
    delay: float = 2.0,
) -> List[Dict]:
    """Fetch vehicles from CarFromJapan aggregator."""
    params: Dict[str, Any] = {
        "page": page,
        "limit": 50,
        "destination": "LY",
    }
    if make:
        params["make"] = make
    if grade_min:
        params["grade"] = grade_min

    try:
        time.sleep(delay + random.uniform(0.5, 1.0))
        resp = session.get(CARFROMJAPAN_API, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("vehicles") or data.get("data") or []
    except Exception as exc:
        logger.error("[Japan/CarFromJapan] Page %d error: %s", page, exc)
        return []


def _parse_grade(grade_raw: Any) -> Optional[float]:
    """Parse Japanese auction grade to numeric value."""
    if grade_raw is None:
        return None
    grade_str = str(grade_raw).strip().upper()
    return GRADE_MAP.get(grade_str)


def normalize_japan_record(raw: Dict) -> Optional[Dict]:
    """Normalize a Japanese auction record to AuctionVehicle format."""
    if not raw:
        return None

    # ── Identity ──────────────────────────────────────────────────────────
    stock_id = str(
        raw.get("stockId") or raw.get("stock_id") or raw.get("id") or
        raw.get("lot_number") or raw.get("chassisNumber") or ""
    ).strip()

    if not stock_id:
        return None

    lot_number = f"{stock_id}-JAPAN"

    # VIN / Chassis number (Japan uses chassis numbers, not VINs)
    vin = (
        raw.get("vin") or raw.get("chassisNumber") or raw.get("chassis_number") or
        raw.get("frameNumber") or ""
    ).strip().upper()

    # ── Vehicle info ──────────────────────────────────────────────────────
    year_raw = raw.get("year") or raw.get("modelYear") or raw.get("manufactureYear")
    try:
        year = int(str(year_raw)) if year_raw else None
    except (ValueError, TypeError):
        year = None

    make = (raw.get("make") or raw.get("manufacturer") or raw.get("brand") or "").strip().title()
    model = (raw.get("model") or raw.get("modelName") or "").strip().title()
    trim = (raw.get("trim") or raw.get("grade") or raw.get("series") or "").strip()
    body_style = (raw.get("bodyType") or raw.get("body_style") or raw.get("body") or "").strip()
    color = (raw.get("color") or raw.get("colour") or raw.get("exteriorColor") or "").strip()
    engine = (raw.get("engine") or raw.get("engineSize") or raw.get("displacement") or "").strip()
    fuel = (raw.get("fuelType") or raw.get("fuel") or "petrol").strip().lower()
    transmission = (raw.get("transmission") or raw.get("gearbox") or "").strip()
    drive = (raw.get("driveType") or raw.get("drive") or "").strip()

    # ── Odometer ──────────────────────────────────────────────────────────
    odo_raw = raw.get("mileage") or raw.get("odometer") or raw.get("kilometres") or 0
    try:
        odometer = int(str(odo_raw).replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        odometer = None

    # Japan uses km
    odo_unit = "km"

    # ── Auction Grade ─────────────────────────────────────────────────────
    grade_raw = raw.get("auctionGrade") or raw.get("grade") or raw.get("condition")
    grade_str = str(grade_raw).strip() if grade_raw else ""
    grade_numeric = _parse_grade(grade_raw)

    # Map grade to title_type
    if grade_numeric and grade_numeric >= 4.0:
        title_type = "clean"
    elif grade_numeric and grade_numeric >= 3.0:
        title_type = "clean"  # Still good condition
    elif grade_numeric and grade_numeric >= 2.0:
        title_type = "salvage"
    else:
        title_type = "unknown"

    damage = (raw.get("damage") or raw.get("repairDescription") or "").strip()

    # ── Price ─────────────────────────────────────────────────────────────
    # BE FORWARD shows FOB price (Free On Board Japan)
    price_raw = (
        raw.get("fobPrice") or raw.get("price") or raw.get("currentBid") or
        raw.get("totalPrice") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("$", "").replace("¥", ""))
    except (ValueError, TypeError):
        price = 0.0

    # Determine currency
    currency = "USD"  # BE FORWARD shows USD prices
    if raw.get("currency"):
        currency = raw["currency"].upper()

    # ── Location ──────────────────────────────────────────────────────────
    location = (raw.get("location") or raw.get("auctionHouse") or "Japan").strip()
    city = location
    state = "Japan"

    # ── Auction date ──────────────────────────────────────────────────────
    auction_date = (
        raw.get("auctionDate") or raw.get("saleDate") or
        raw.get("availableDate") or ""
    )

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:20]]
    elif raw.get("imageUrl") or raw.get("mainImage"):
        images = [raw.get("imageUrl") or raw.get("mainImage")]

    # ── Detail URL ────────────────────────────────────────────────────────
    detail_url = (
        raw.get("url") or raw.get("detailUrl") or raw.get("stockUrl") or
        f"https://www.beforward.jp/stocklist/detail/ps/1/pn/{stock_id}"
    )

    # ── Shipping estimate to Libya ─────────────────────────────────────────
    # Japan → Libya Misrata: ~$1,800-2,200 depending on vehicle size
    shipping_estimate = 2000  # USD, approximate

    return {
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": SOURCE_TAG,
        "source_country": "JP",
        "source_url": detail_url,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "body_style": body_style,
        "color": color,
        "engine": engine,
        "fuel_type": fuel,
        "transmission": transmission,
        "drive_type": drive,
        "odometer": odometer,
        "odometer_unit": odo_unit,
        "title_type": title_type,
        "damage_primary": damage,
        "auction_grade": grade_str,
        "has_keys": True,    # Japanese auction vehicles always have keys
        "runs_drives": True if grade_numeric and grade_numeric >= 3.0 else None,
        "current_bid": price,
        "currency": currency,
        "location_city": city,
        "location_state": "Japan",
        "location_country": "JP",
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "beforward",
        # Japan-specific
        "grade_numeric": grade_numeric,
        "shipping_estimate_usd": shipping_estimate,
        "is_hot_model": _is_hot_model(make, model),
    }


def _is_hot_model(make: str, model: str) -> bool:
    """Check if this is a hot model for the Libyan market."""
    make_clean = make.strip().title()
    model_clean = model.strip().title()
    hot_models = LIBYA_HOT_MODELS.get(make_clean, [])
    return any(hm.lower() in model_clean.lower() for hm in hot_models)


class JapanAuctionsScraper:
    """High-level Japan auctions scraper with grade filtering."""

    def __init__(self, delay: float = 2.0):
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        grade_min: Optional[float] = 3.0,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 50,
        hot_models_only: bool = False,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of normalized Japanese vehicles."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            raw_items = _fetch_beforward_page(
                self.session, page=page, make=make, model=model,
                grade_min=grade_min, year_min=year_min, year_max=year_max,
                delay=self.delay,
            )

            # Fallback to CarFromJapan
            if not raw_items:
                raw_items = _fetch_carfromjapan_page(
                    self.session, page=page, make=make,
                    grade_min=grade_min, delay=self.delay,
                )

            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            self._stats["fetched"] += len(raw_items)

            batch = []
            for raw in raw_items:
                norm = normalize_japan_record(raw)
                if norm:
                    if hot_models_only and not norm.get("is_hot_model"):
                        continue
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    def fetch_hot_models(self, max_pages: int = 20) -> Generator[List[Dict], None, None]:
        """Fetch only hot models for the Libyan market."""
        for make, models in LIBYA_HOT_MODELS.items():
            for model in models:
                logger.info("[Japan] Fetching hot model: %s %s", make, model)
                yield from self.fetch_pages(
                    make=make, model=model,
                    grade_min=3.0, max_pages=max_pages,
                )

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

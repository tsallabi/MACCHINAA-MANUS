"""
MACCHINAA-EVOLVED — Copart Scraper
=====================================
جلب السيارات من Copart عبر 3 مصادر بديلة:

  1. salvagebid.com REST API  — أفضل تغطية، JSON نظيف، بدون auth
  2. bid.cars aggregator      — تغطية واسعة، JSON
  3. copart.com مباشرة        — HTML scraping كملاذ أخير

Copart هو أكبر مزاد سيارات تالفة في العالم:
  - 200+ موقع في USA وكندا والمملكة المتحدة
  - 125,000+ سيارة أسبوعياً
  - معظمها من شركات التأمين (Salvage/Clean title)
  - أسعار تبدأ من $100 للسيارات التالفة

الاستخدام:
    from scrapers.copart.scraper import CopartScraper
    scraper = CopartScraper()
    vehicles = scraper.fetch_all(make="Toyota", max_pages=10)
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════

SOURCE_TAG = "COPART"

# salvagebid.com — reverse-engineered Copart API (most reliable)
SALVAGEBID_SEARCH = "https://salvagebid.com/api/search"
SALVAGEBID_DETAIL = "https://salvagebid.com/api/lot/{lot_id}"

# bid.cars aggregator
BIDCARS_SEARCH = "https://bid.cars/en/search/results"

# Copart direct (fallback)
COPART_SEARCH = "https://www.copart.com/public/lots/search-results"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) "
    "Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# Makes popular in Libya — prioritize these
LIBYAN_MARKET_MAKES = [
    "TOYOTA", "NISSAN", "HONDA", "HYUNDAI", "KIA",
    "CHEVROLET", "FORD", "GMC", "DODGE", "JEEP",
    "BMW", "MERCEDES-BENZ", "AUDI", "VOLKSWAGEN",
    "LAND ROVER", "LEXUS", "INFINITI", "MITSUBISHI",
    "MAZDA", "SUBARU", "CADILLAC", "RAM", "VOLVO",
]

# Year ranges for splitting large queries
YEAR_RANGES = [
    (2000, 2010), (2011, 2015), (2016, 2019),
    (2020, 2022), (2023, 2026),
]


# ══════════════════════════════════════════════════════════════════════════
#  HTTP SESSION
# ══════════════════════════════════════════════════════════════════════════

def _make_session(delay: float = 1.0) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=delay,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return session


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 1: salvagebid.com (most reliable)
# ══════════════════════════════════════════════════════════════════════════

def _fetch_salvagebid_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch one page from salvagebid.com Copart API."""
    params: Dict[str, Any] = {
        "auction": "copart",
        "page": page,
        "per_page": 50,
        "sort": "date_asc",
    }
    if make:
        params["make"] = make
    if model:
        params["model"] = model
    if year_min:
        params["year_from"] = year_min
    if year_max:
        params["year_to"] = year_max

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(SALVAGEBID_SEARCH, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("[Copart/salvagebid] Rate limited — sleeping 30s")
            time.sleep(30)
            return []

        if resp.status_code != 200:
            logger.warning("[Copart/salvagebid] HTTP %s page %d", resp.status_code, page)
            return []

        data = resp.json()
        items = (
            data.get("results") or data.get("data") or
            data.get("vehicles") or data.get("lots") or []
        )
        logger.debug("[Copart/salvagebid] Page %d → %d items", page, len(items))
        return items

    except Exception as exc:
        logger.error("[Copart/salvagebid] Page %d error: %s", page, exc)
        return []


# ══════════════════════════════════════════════════════════════════════════
#  SOURCE 2: bid.cars aggregator
# ══════════════════════════════════════════════════════════════════════════

def _fetch_bidcars_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch one page from bid.cars Copart aggregator."""
    params: Dict[str, Any] = {
        "auction": "copart",
        "page": page,
        "per_page": 50,
    }
    if make:
        params["make"] = make.replace(" ", "+")
    if year_min:
        params["year_from"] = year_min
    if year_max:
        params["year_to"] = year_max

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(BIDCARS_SEARCH, params=params, timeout=30)

        if resp.status_code != 200:
            return []

        data = resp.json()
        return data.get("results") or data.get("data") or []

    except Exception as exc:
        logger.error("[Copart/bidcars] Page %d error: %s", page, exc)
        return []


# ══════════════════════════════════════════════════════════════════════════
#  NORMALIZER
# ══════════════════════════════════════════════════════════════════════════

def normalize_copart_record(raw: Dict) -> Optional[Dict]:
    """
    Normalize a raw Copart record into AuctionVehicle-compatible format.
    Handles field names from both salvagebid and bid.cars.
    """
    if not raw:
        return None

    # ── Lot number ────────────────────────────────────────────────────────
    lot_id = str(
        raw.get("lot_number") or raw.get("lotNumber") or raw.get("id") or
        raw.get("lot_id") or raw.get("lotId") or ""
    ).strip()

    if not lot_id:
        return None

    lot_number = f"{lot_id}-COPART"

    # ── VIN ───────────────────────────────────────────────────────────────
    vin = (raw.get("vin") or raw.get("VIN") or "").strip().upper()

    # ── Vehicle info ──────────────────────────────────────────────────────
    year_raw = raw.get("year") or raw.get("modelYear") or raw.get("vehicle_year")
    try:
        year = int(str(year_raw)) if year_raw else None
    except (ValueError, TypeError):
        year = None

    make = (raw.get("make") or raw.get("manufacturer") or "").strip().title()
    model = (raw.get("model") or raw.get("modelName") or "").strip().title()
    trim = (raw.get("trim") or raw.get("series") or "").strip()
    body_style = (raw.get("body_style") or raw.get("bodyStyle") or raw.get("body") or "").strip()
    color = (raw.get("color") or raw.get("primaryColor") or raw.get("exterior_color") or "").strip()
    engine = (raw.get("engine") or raw.get("engineSize") or "").strip()
    fuel = (raw.get("fuel_type") or raw.get("fuelType") or "").strip()
    transmission = (raw.get("transmission") or raw.get("gearbox") or "").strip()
    drive = (raw.get("drive") or raw.get("driveType") or raw.get("drive_type") or "").strip()

    # ── Odometer ──────────────────────────────────────────────────────────
    odo_raw = raw.get("odometer") or raw.get("mileage") or raw.get("miles") or 0
    try:
        odometer = int(str(odo_raw).replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        odometer = None
    odo_unit = "mi"  # Copart USA uses miles

    # ── Condition ─────────────────────────────────────────────────────────
    title_raw = (raw.get("title_type") or raw.get("titleType") or raw.get("title") or "").lower()
    if "clean" in title_raw:
        title_type = "clean"
    elif "salvage" in title_raw:
        title_type = "salvage"
    elif "rebuilt" in title_raw:
        title_type = "rebuilt"
    elif "parts" in title_raw:
        title_type = "parts_only"
    else:
        title_type = "unknown"

    damage_primary = (
        raw.get("damage") or raw.get("primaryDamage") or
        raw.get("damage_description") or raw.get("loss_type") or ""
    ).strip()
    damage_secondary = (raw.get("secondary_damage") or raw.get("secondaryDamage") or "").strip()

    keys_raw = (raw.get("has_keys") or raw.get("hasKeys") or raw.get("keys") or "")
    has_keys = None
    if isinstance(keys_raw, bool):
        has_keys = keys_raw
    elif str(keys_raw).lower() in ("yes", "true", "1"):
        has_keys = True
    elif str(keys_raw).lower() in ("no", "false", "0"):
        has_keys = False

    runs_raw = (raw.get("runs_drives") or raw.get("runsDrives") or raw.get("runs") or "")
    runs_drives = None
    if isinstance(runs_raw, bool):
        runs_drives = runs_raw
    elif str(runs_raw).lower() in ("yes", "true", "1", "run and drive"):
        runs_drives = True
    elif str(runs_raw).lower() in ("no", "false", "0"):
        runs_drives = False

    # ── Price ─────────────────────────────────────────────────────────────
    price_raw = (
        raw.get("current_bid") or raw.get("currentBid") or
        raw.get("bid") or raw.get("price") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        price = 0.0

    buy_now_raw = raw.get("buy_now") or raw.get("buyNow") or raw.get("buy_now_price") or 0
    try:
        buy_now = float(str(buy_now_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        buy_now = 0.0

    # ── Location ──────────────────────────────────────────────────────────
    location_raw = (
        raw.get("location") or raw.get("yard_name") or raw.get("yardName") or ""
    )
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "")
        state = location_raw.get("state", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    # ── Auction date ──────────────────────────────────────────────────────
    auction_date_raw = (
        raw.get("auction_date") or raw.get("auctionDate") or
        raw.get("sale_date") or raw.get("saleDate") or ""
    )

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
        elif isinstance(imgs, str):
            images = [imgs]
    elif raw.get("image_url") or raw.get("thumbnail"):
        img = raw.get("image_url") or raw.get("thumbnail")
        images = [img]

    # ── Detail URL ────────────────────────────────────────────────────────
    detail_url = (
        raw.get("url") or raw.get("detail_url") or raw.get("link") or
        f"https://www.copart.com/lot/{lot_id}"
    )

    return {
        # Core identity
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": SOURCE_TAG,
        "source_country": "US",
        "source_url": detail_url,

        # Vehicle
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

        # Condition
        "odometer": odometer,
        "odometer_unit": odo_unit,
        "title_type": title_type,
        "damage_primary": damage_primary,
        "damage_secondary": damage_secondary,
        "has_keys": has_keys,
        "runs_drives": runs_drives,

        # Pricing
        "current_bid": price,
        "buy_now_price": buy_now,
        "currency": "USD",

        # Location
        "location_city": city,
        "location_state": state,
        "location_country": "US",

        # Auction
        "auction_date": str(auction_date_raw),
        "status": "active",

        # Media
        "primary_image": images[0] if images else "",
        "images_json": images,

        # Raw
        "raw_data": raw,
        "sync_source": "salvagebid",
    }


# ══════════════════════════════════════════════════════════════════════════
#  MAIN SCRAPER CLASS
# ══════════════════════════════════════════════════════════════════════════

class CopartScraper:
    """
    High-level Copart scraper with automatic source fallback.

    Usage:
        scraper = CopartScraper(delay=1.5)
        for batch in scraper.fetch_pages(make="Toyota", max_pages=20):
            for vehicle in batch:
                save_to_db(vehicle)
    """

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = _make_session(delay)
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 100,
        source: str = "salvagebid",
    ) -> Generator[List[Dict], None, None]:
        """
        Generator that yields batches of normalized vehicles page by page.
        Automatically falls back to bid.cars if salvagebid fails.
        """
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            # Try primary source
            if source in ("salvagebid", "auto"):
                raw_items = _fetch_salvagebid_page(
                    self.session, page=page, make=make, model=model,
                    year_min=year_min, year_max=year_max, delay=self.delay,
                )
            else:
                raw_items = _fetch_bidcars_page(
                    self.session, page=page, make=make,
                    year_min=year_min, year_max=year_max, delay=self.delay,
                )

            # Fallback to bid.cars if primary fails
            if not raw_items and source == "auto":
                logger.info("[Copart] Falling back to bid.cars for page %d", page)
                raw_items = _fetch_bidcars_page(
                    self.session, page=page, make=make,
                    year_min=year_min, year_max=year_max, delay=self.delay,
                )

            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    logger.info("[Copart] 3 consecutive empty pages — stopping at page %d", page)
                    break
                continue

            consecutive_empty = 0
            self._stats["fetched"] += len(raw_items)

            # Normalize batch
            normalized_batch = []
            for raw in raw_items:
                normalized = normalize_copart_record(raw)
                if normalized:
                    normalized_batch.append(normalized)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if normalized_batch:
                yield normalized_batch

    def fetch_all(
        self,
        make: Optional[str] = None,
        max_pages: int = 50,
    ) -> List[Dict]:
        """Fetch all pages and return flat list of normalized vehicles."""
        all_vehicles = []
        for batch in self.fetch_pages(make=make, max_pages=max_pages):
            all_vehicles.extend(batch)
        return all_vehicles

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

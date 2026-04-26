"""
MACCHINAA-EVOLVED — GovDeals / GSA Auctions Scraper
======================================================
جلب السيارات الحكومية الأمريكية عبر:

  1. GSA Auctions API الرسمي  — مجاني، JSON، لا يحتاج auth
  2. GovPlanet (Ritchie Bros)  — معدات ثقيلة وسيارات حكومية
  3. PublicSurplus.com         — مزادات حكومية إضافية

لماذا المزادات الحكومية مهمة؟
  - سيارات حكومية = صيانة منتظمة وسجل كامل
  - أسعار منخفضة جداً (لا يوجد هامش ربح تجاري)
  - سيارات شرطة وجيش وبلديات
  - Ford Crown Victoria, Chevrolet Tahoe, Dodge Charger بأسعار ممتازة

الاستخدام:
    from scrapers.govdeals.scraper import GovDealsScraper
    scraper = GovDealsScraper()
    vehicles = scraper.fetch_all(max_pages=5)
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "GOVDEALS"

# GSA Auctions official API (free, no auth needed with DEMO_KEY)
GSA_API_URL = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
GSA_API_KEY = os.environ.get("GSA_API_KEY", "DEMO_KEY")

# GovPlanet (Ritchie Bros) — government vehicles
GOVPLANET_SEARCH = "https://www.govplanet.com/for-sale/Trucks-Trailers-Buses"

YEAR_RE = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\b")

VEHICLE_KEYWORDS = [
    "vehicle", "car", "truck", "van", "suv", "sedan", "pickup",
    "sport utility", "coupe", "wagon", "cargo", "passenger", "fleet",
    "police", "patrol", "interceptor", "pursuit",
]

KNOWN_MAKES = [
    "Ford", "Chevrolet", "Chevy", "GMC", "Dodge", "Ram", "Jeep",
    "Toyota", "Honda", "Nissan", "Hyundai", "Kia", "Mazda",
    "Subaru", "Volkswagen", "BMW", "Mercedes", "Audi", "Lexus",
    "Cadillac", "Buick", "Lincoln", "Volvo", "Mitsubishi",
    "International", "Freightliner", "Peterbilt", "Kenworth",
    "Tesla", "Land Rover", "Chrysler",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
    })
    return session


def _is_vehicle(item: Dict) -> bool:
    """Check if a GSA auction item is a vehicle."""
    name = (item.get("itemName") or "").lower()
    desc = (item.get("description") or "").lower()
    text = f"{name} {desc}"

    if any(kw in text for kw in VEHICLE_KEYWORDS):
        return True
    if any(mk.lower() in text for mk in KNOWN_MAKES):
        return True
    if YEAR_RE.search(name) and any(x in name for x in ["4x4", "awd", "4wd", "cyl", "4dr", "2dr"]):
        return True
    return False


def _parse_year_make_model(title: str):
    """Extract year, make, model from auction title string."""
    year = make = model = None
    if not title:
        return year, make, model

    m = YEAR_RE.search(title)
    if m:
        year = int(m.group(1))

    tl = title.lower()
    for mk in KNOWN_MAKES:
        if mk.lower() in tl:
            make = mk
            idx = tl.find(mk.lower())
            tail = title[idx + len(mk):].strip(" -,")
            model = " ".join(tail.split()[:3]) or None
            break

    return year, make, model


def _fetch_gsa_page(
    session: requests.Session,
    page: int = 1,
    page_size: int = 50,
    delay: float = 1.0,
) -> List[Dict]:
    """Fetch one page from the official GSA Auctions API."""
    params = {
        "api_key": GSA_API_KEY,
        "page": page,
        "size": page_size,
        "category": "vehicles",  # Filter to vehicles category
        "status": "active",
    }

    try:
        time.sleep(delay + random.uniform(0.2, 0.5))
        resp = session.get(GSA_API_URL, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("[GovDeals/GSA] Rate limited — sleeping 60s")
            time.sleep(60)
            return []

        if resp.status_code != 200:
            logger.warning("[GovDeals/GSA] HTTP %s page %d", resp.status_code, page)
            return []

        data = resp.json()
        items = (
            data.get("auctionItems") or data.get("items") or
            data.get("results") or data.get("data") or []
        )

        # Filter to vehicles only
        vehicle_items = [i for i in items if _is_vehicle(i)]
        logger.info(
            "[GovDeals/GSA] Page %d: %d total, %d vehicles",
            page, len(items), len(vehicle_items),
        )
        return vehicle_items

    except Exception as exc:
        logger.error("[GovDeals/GSA] Page %d error: %s", page, exc)
        return []


def normalize_govdeals_record(raw: Dict) -> Optional[Dict]:
    """Normalize a GSA auction item to AuctionVehicle format."""
    if not raw:
        return None

    # ── Identity ──────────────────────────────────────────────────────────
    item_id = str(
        raw.get("itemId") or raw.get("id") or raw.get("auctionId") or ""
    ).strip()

    if not item_id:
        return None

    lot_number = f"{item_id}-GOVDEALS"
    title = (raw.get("itemName") or raw.get("title") or raw.get("name") or "").strip()

    # ── Parse vehicle info from title ─────────────────────────────────────
    year, make, model = _parse_year_make_model(title)

    # Also check dedicated fields
    year = year or raw.get("year") or raw.get("modelYear")
    if year:
        try:
            year = int(str(year))
        except (ValueError, TypeError):
            year = None

    make = make or (raw.get("make") or "").strip()
    model = model or (raw.get("model") or "").strip()

    # ── Price ─────────────────────────────────────────────────────────────
    price_raw = (
        raw.get("currentBid") or raw.get("current_bid") or
        raw.get("bidAmount") or raw.get("price") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        price = 0.0

    # ── Location ──────────────────────────────────────────────────────────
    location_raw = raw.get("location") or raw.get("agencyLocation") or {}
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "")
        state = location_raw.get("state", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    # ── Auction date ──────────────────────────────────────────────────────
    auction_date = (
        raw.get("endDate") or raw.get("closeDate") or
        raw.get("auctionEndDate") or raw.get("end_date") or ""
    )

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:10]]
    elif raw.get("imageUrl") or raw.get("thumbnail"):
        images = [raw.get("imageUrl") or raw.get("thumbnail")]

    # ── Detail URL ────────────────────────────────────────────────────────
    detail_url = (
        raw.get("url") or raw.get("itemUrl") or
        f"https://gsaauctions.gov/gsaauctions/aucindx?lotnum={item_id}"
    )

    # ── Description ───────────────────────────────────────────────────────
    description = (raw.get("description") or raw.get("itemDescription") or "").strip()

    # Try to extract VIN from description
    vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", description)
    vin = vin_match.group(1) if vin_match else ""

    # Try to extract odometer from description
    odo_match = re.search(r"(\d[\d,]+)\s*(?:miles?|mi\.?)", description, re.IGNORECASE)
    odometer = int(odo_match.group(1).replace(",", "")) if odo_match else None

    return {
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": SOURCE_TAG,
        "source_country": "US",
        "source_url": detail_url,
        "year": year,
        "make": make,
        "model": model,
        "trim": "",
        "color": (raw.get("color") or "").strip(),
        "engine": "",
        "fuel_type": "",
        "transmission": "",
        "odometer": odometer,
        "odometer_unit": "mi",
        "title_type": "clean",  # Government vehicles usually have clean titles
        "damage_primary": "",
        "has_keys": True,       # Government vehicles usually have keys
        "runs_drives": None,
        "current_bid": price,
        "currency": "USD",
        "location_city": city,
        "location_state": state,
        "location_country": "US",
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "gsa_api",
        # Extra: government-specific
        "agency": (raw.get("agency") or raw.get("agencyName") or "").strip(),
        "description": description[:500],
        "title_raw": title,
    }


class GovDealsScraper:
    """High-level GovDeals/GSA scraper."""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        max_pages: int = 10,
        page_size: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of normalized government vehicles."""
        for page in range(1, max_pages + 1):
            raw_items = _fetch_gsa_page(
                self.session, page=page,
                page_size=page_size, delay=self.delay,
            )

            if not raw_items:
                logger.info("[GovDeals] No more items at page %d — stopping", page)
                break

            self._stats["fetched"] += len(raw_items)

            batch = []
            for raw in raw_items:
                norm = normalize_govdeals_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    def fetch_all(self, max_pages: int = 10) -> List[Dict]:
        all_vehicles = []
        for batch in self.fetch_pages(max_pages=max_pages):
            all_vehicles.extend(batch)
        return all_vehicles

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

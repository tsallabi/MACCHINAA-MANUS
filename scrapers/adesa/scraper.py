"""
MACCHINAA-EVOLVED — ADESA / OpenLane Scraper
=============================================
جلب السيارات من ADESA وOpenLane — ثاني أكبر مزاد تجار في أمريكا

  - 75+ موقع في USA وكندا
  - 7 مليون سيارة سنوياً
  - مملوك لـ OPENLANE (سابقاً KAR Auction Services)
  - يتطلب dealer account
  - سيارات تجار بحالة ممتازة عادةً

المصادر:
  1. OpenLane API الرسمي (Auth0 authentication)
  2. ADESA.com مباشرة
  3. BacklotCars (ADESA's online platform)

الاستخدام:
    from scrapers.adesa.scraper import ADESAScraper
    scraper = ADESAScraper(bearer_token="YOUR_TOKEN")
    for batch in scraper.fetch_pages(make="Honda"):
        process(batch)
"""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "ADESA"

# OpenLane/ADESA API
OPENLANE_SEARCH = "https://api.openlane.com/v1/listings/search"
OPENLANE_AUTH = "https://auth.openlane.com/oauth/token"

# BacklotCars (ADESA online platform)
BACKLOTCARS_SEARCH = "https://api.backlotcars.com/v1/vehicles"

# ADESA direct
ADESA_SEARCH = "https://www.adesa.com/api/search/vehicles"

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


def _fetch_openlane_page(
    session: requests.Session,
    bearer_token: str,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    dealer_id: Optional[str] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch from OpenLane/ADESA API with bearer token."""
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }

    params: Dict[str, Any] = {
        "page": page,
        "pageSize": 50,
        "status": "active",
        "sortBy": "auctionDate",
    }
    if make:
        params["make"] = make
    if year_min:
        params["yearMin"] = year_min
    if year_max:
        params["yearMax"] = year_max
    if dealer_id:
        params["dealerId"] = dealer_id

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(
            OPENLANE_SEARCH,
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            logger.warning("[ADESA] Unauthorized — check bearer token")
            return []

        if resp.status_code != 200:
            logger.warning("[ADESA] HTTP %s page %d", resp.status_code, page)
            return []

        data = resp.json()
        return data.get("listings") or data.get("vehicles") or data.get("data") or []

    except Exception as exc:
        logger.error("[ADESA] Page %d error: %s", page, exc)
        return []


def _fetch_backlotcars_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch from BacklotCars (ADESA's online platform)."""
    params: Dict[str, Any] = {
        "page": page,
        "limit": 50,
    }
    if make:
        params["make"] = make

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(BACKLOTCARS_SEARCH, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("vehicles") or data.get("results") or []
    except Exception as exc:
        logger.error("[ADESA/BacklotCars] Page %d error: %s", page, exc)
        return []


def normalize_adesa_record(raw: Dict) -> Optional[Dict]:
    """Normalize an ADESA/OpenLane listing to AuctionVehicle format."""
    if not raw:
        return None

    listing_id = str(
        raw.get("listingId") or raw.get("vehicleId") or raw.get("id") or
        raw.get("stockNumber") or ""
    ).strip()

    if not listing_id:
        return None

    lot_number = f"{listing_id}-ADESA"
    vin = (raw.get("vin") or raw.get("VIN") or "").strip().upper()

    year_raw = raw.get("year") or raw.get("modelYear")
    try:
        year = int(str(year_raw)) if year_raw else None
    except (ValueError, TypeError):
        year = None

    make = (raw.get("make") or "").strip().title()
    model = (raw.get("model") or "").strip().title()
    trim = (raw.get("trim") or raw.get("series") or "").strip()
    color = (raw.get("exteriorColor") or raw.get("color") or "").strip()
    engine = (raw.get("engine") or raw.get("engineDescription") or "").strip()
    fuel = (raw.get("fuelType") or "").strip().lower()
    transmission = (raw.get("transmission") or "").strip()
    drive = (raw.get("driveType") or "").strip()

    odo_raw = raw.get("odometer") or raw.get("mileage") or 0
    try:
        odometer = int(str(odo_raw).replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        odometer = None

    title_raw = (raw.get("titleType") or "clean").lower()
    if "clean" in title_raw:
        title_type = "clean"
    elif "salvage" in title_raw:
        title_type = "salvage"
    elif "rebuilt" in title_raw:
        title_type = "rebuilt"
    else:
        title_type = "clean"

    damage = (raw.get("damage") or raw.get("conditionReport") or "").strip()

    price_raw = (
        raw.get("currentBid") or raw.get("startingBid") or
        raw.get("price") or raw.get("reservePrice") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        price = 0.0

    acv = raw.get("acv") or raw.get("actualCashValue") or 0  # Actual Cash Value

    location_raw = raw.get("location") or raw.get("auctionLocation") or {}
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "")
        state = location_raw.get("state", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    auction_date = raw.get("auctionDate") or raw.get("saleDate") or ""

    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
    elif raw.get("imageUrl"):
        images = [raw["imageUrl"]]

    detail_url = (
        raw.get("url") or raw.get("detailUrl") or
        f"https://www.adesa.com/vehicle/{listing_id}"
    )

    return {
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": SOURCE_TAG,
        "source_country": "US",
        "source_url": detail_url,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "color": color,
        "engine": engine,
        "fuel_type": fuel,
        "transmission": transmission,
        "drive_type": drive,
        "odometer": odometer,
        "odometer_unit": "mi",
        "title_type": title_type,
        "damage_primary": damage,
        "has_keys": True,
        "runs_drives": True,
        "current_bid": price,
        "estimated_retail_value": float(acv) if acv else None,
        "currency": "USD",
        "location_city": city,
        "location_state": state,
        "location_country": "US",
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "openlane_api",
    }


class ADESAScraper:
    """High-level ADESA/OpenLane scraper."""

    def __init__(
        self,
        bearer_token: str = "",
        dealer_id: str = "",
        delay: float = 1.5,
    ):
        self.bearer_token = bearer_token or os.environ.get("ADESA_BEARER_TOKEN", "")
        self.dealer_id = dealer_id or os.environ.get("ADESA_DEALER_ID", "")
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of normalized ADESA vehicles."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            if self.bearer_token:
                raw_items = _fetch_openlane_page(
                    self.session, self.bearer_token,
                    page=page, make=make,
                    year_min=year_min, year_max=year_max,
                    dealer_id=self.dealer_id,
                    delay=self.delay,
                )
            else:
                raw_items = _fetch_backlotcars_page(
                    self.session, page=page, make=make, delay=self.delay,
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
                norm = normalize_adesa_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

"""
MACCHINAA-EVOLVED — IAAI Scraper
=====================================
جلب السيارات من IAAI (Insurance Auto Auctions) عبر:

  1. salvagebid.com REST API  — أفضل تغطية
  2. bid.cars aggregator      — تغطية واسعة
  3. IAAI مباشرة              — HTML scraping

IAAI هو ثاني أكبر مزاد سيارات تالفة في العالم:
  - 200+ موقع في USA وكندا
  - 100,000+ سيارة أسبوعياً
  - شراكة مع KAR Auction Services
  - يُعرف الآن بـ "IAA" (Insurance Auto Auctions)

الاستخدام:
    from scrapers.iaai.scraper import IAAScraper
    scraper = IAAScraper()
    for batch in scraper.fetch_pages(make="BMW", max_pages=10):
        process(batch)
"""
from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "IAAI"

SALVAGEBID_SEARCH = "https://salvagebid.com/api/search"
BIDCARS_SEARCH = "https://bid.cars/en/search/results"
IAAI_DIRECT = "https://www.iaai.com/Search"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


def _make_session(delay: float = 1.5) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=delay, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, */*",
    })
    return session


def _fetch_salvagebid_iaai(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    params: Dict[str, Any] = {
        "auction": "iaai",
        "page": page,
        "per_page": 50,
    }
    if make:
        params["make"] = make
    if year_min:
        params["year_from"] = year_min
    if year_max:
        params["year_to"] = year_max

    try:
        time.sleep(delay + random.uniform(0.2, 0.7))
        resp = session.get(SALVAGEBID_SEARCH, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("results") or data.get("data") or data.get("lots") or []
    except Exception as exc:
        logger.error("[IAAI/salvagebid] Page %d: %s", page, exc)
        return []


def _fetch_bidcars_iaai(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    params: Dict[str, Any] = {
        "auction": "iaai",
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
        time.sleep(delay + random.uniform(0.2, 0.7))
        resp = session.get(BIDCARS_SEARCH, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("results") or data.get("data") or []
    except Exception as exc:
        logger.error("[IAAI/bidcars] Page %d: %s", page, exc)
        return []


def normalize_iaai_record(raw: Dict) -> Optional[Dict]:
    """Normalize a raw IAAI record to AuctionVehicle format."""
    if not raw:
        return None

    lot_id = str(
        raw.get("lot_number") or raw.get("lotNumber") or raw.get("id") or
        raw.get("stock_number") or ""
    ).strip()

    if not lot_id:
        return None

    lot_number = f"{lot_id}-IAAI"
    vin = (raw.get("vin") or raw.get("VIN") or "").strip().upper()

    year_raw = raw.get("year") or raw.get("modelYear")
    try:
        year = int(str(year_raw)) if year_raw else None
    except (ValueError, TypeError):
        year = None

    make = (raw.get("make") or "").strip().title()
    model = (raw.get("model") or "").strip().title()
    trim = (raw.get("trim") or raw.get("series") or "").strip()
    color = (raw.get("color") or raw.get("primaryColor") or "").strip()
    engine = (raw.get("engine") or "").strip()
    fuel = (raw.get("fuel_type") or raw.get("fuelType") or "").strip()
    transmission = (raw.get("transmission") or "").strip()

    odo_raw = raw.get("odometer") or raw.get("mileage") or 0
    try:
        odometer = int(str(odo_raw).replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        odometer = None

    title_raw = (raw.get("title_type") or raw.get("titleType") or "").lower()
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

    damage = (raw.get("damage") or raw.get("primaryDamage") or raw.get("loss_type") or "").strip()

    keys_raw = str(raw.get("has_keys") or raw.get("keys") or "")
    has_keys = True if keys_raw.lower() in ("yes", "true", "1") else (
        False if keys_raw.lower() in ("no", "false", "0") else None
    )

    runs_raw = str(raw.get("runs_drives") or raw.get("runsDrives") or "")
    runs_drives = True if runs_raw.lower() in ("yes", "true", "1") else (
        False if runs_raw.lower() in ("no", "false", "0") else None
    )

    price_raw = raw.get("current_bid") or raw.get("currentBid") or raw.get("price") or 0
    try:
        price = float(str(price_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        price = 0.0

    location_raw = raw.get("location") or raw.get("yard_name") or ""
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "")
        state = location_raw.get("state", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
    elif raw.get("image_url"):
        images = [raw["image_url"]]

    detail_url = (
        raw.get("url") or raw.get("detail_url") or
        f"https://www.iaai.com/VehicleDetail/{lot_id}"
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
        "odometer": odometer,
        "odometer_unit": "mi",
        "title_type": title_type,
        "damage_primary": damage,
        "has_keys": has_keys,
        "runs_drives": runs_drives,
        "current_bid": price,
        "currency": "USD",
        "location_city": city,
        "location_state": state,
        "location_country": "US",
        "auction_date": str(raw.get("auction_date") or raw.get("saleDate") or ""),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "salvagebid",
    }


class IAAScraper:
    """High-level IAAI scraper with automatic source fallback."""

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = _make_session(delay)
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 100,
        source: str = "salvagebid",
    ) -> Generator[List[Dict], None, None]:
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            if source in ("salvagebid", "auto"):
                raw_items = _fetch_salvagebid_iaai(
                    self.session, page=page, make=make,
                    year_min=year_min, year_max=year_max, delay=self.delay,
                )
            else:
                raw_items = _fetch_bidcars_iaai(
                    self.session, page=page, make=make,
                    year_min=year_min, year_max=year_max, delay=self.delay,
                )

            if not raw_items and source == "auto":
                raw_items = _fetch_bidcars_iaai(
                    self.session, page=page, make=make,
                    year_min=year_min, year_max=year_max, delay=self.delay,
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
                norm = normalize_iaai_record(raw)
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

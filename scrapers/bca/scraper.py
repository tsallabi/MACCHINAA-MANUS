"""
MACCHINAA-EVOLVED — BCA Europe Scraper
=========================================
جلب السيارات من BCA (British Car Auctions) — أكبر مزاد سيارات في أوروبا

  - يعمل في UK, Germany, France, Netherlands, Belgium, Spain, Italy
  - 500,000+ سيارة سنوياً
  - سيارات أسطول (Fleet), إيجار (Lease), تجار (Dealer)
  - معظمها بحالة جيدة مع سجل صيانة كامل
  - أسعار أقل من السوق بـ 20-40%

المصادر:
  1. BCA API الرسمي (bca-group.com) — يحتاج API key للوصول الكامل
  2. AutoTrader UK (aggregator) — بيانات BCA متاحة للعموم
  3. BCA Marketplace مباشرة — HTML scraping

الاستخدام:
    from scrapers.bca.scraper import BCAScraper
    scraper = BCAScraper()
    for batch in scraper.fetch_pages(country="uk", max_pages=10):
        process(batch)
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "BCA"

# BCA Marketplace API endpoints
BCA_UK_SEARCH = "https://www.bca.co.uk/api/search/vehicles"
BCA_DE_SEARCH = "https://www.bca.de/api/search/vehicles"
BCA_FR_SEARCH = "https://www.bca.fr/api/search/vehicles"

# AutoTrader UK (public, no auth needed)
AUTOTRADER_UK = "https://www.autotrader.co.uk/json/search"

# BCA country configs
BCA_COUNTRIES = {
    "uk":  {"url": BCA_UK_SEARCH, "currency": "GBP", "country_code": "GB", "odo_unit": "mi"},
    "de":  {"url": BCA_DE_SEARCH, "currency": "EUR", "country_code": "DE", "odo_unit": "km"},
    "fr":  {"url": BCA_FR_SEARCH, "currency": "EUR", "country_code": "FR", "odo_unit": "km"},
    "nl":  {"url": BCA_UK_SEARCH, "currency": "EUR", "country_code": "NL", "odo_unit": "km"},
    "be":  {"url": BCA_UK_SEARCH, "currency": "EUR", "country_code": "BE", "odo_unit": "km"},
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return session


def _fetch_bca_page(
    session: requests.Session,
    country: str = "uk",
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch one page from BCA marketplace."""
    config = BCA_COUNTRIES.get(country, BCA_COUNTRIES["uk"])

    params: Dict[str, Any] = {
        "page": page,
        "pageSize": 50,
        "sortBy": "dateAsc",
        "status": "live",
    }
    if make:
        params["make"] = make
    if year_min:
        params["yearFrom"] = year_min
    if year_max:
        params["yearTo"] = year_max

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(config["url"], params=params, timeout=30)

        if resp.status_code == 403:
            logger.warning("[BCA/%s] 403 Forbidden — API key may be required", country.upper())
            return []

        if resp.status_code != 200:
            logger.warning("[BCA/%s] HTTP %s page %d", country.upper(), resp.status_code, page)
            return []

        data = resp.json()
        items = (
            data.get("vehicles") or data.get("results") or
            data.get("data") or data.get("items") or []
        )
        logger.debug("[BCA/%s] Page %d → %d items", country.upper(), page, len(items))
        return items

    except Exception as exc:
        logger.error("[BCA/%s] Page %d error: %s", country.upper(), page, exc)
        return []


def normalize_bca_record(raw: Dict, country: str = "uk") -> Optional[Dict]:
    """Normalize a BCA record to AuctionVehicle format."""
    if not raw:
        return None

    config = BCA_COUNTRIES.get(country, BCA_COUNTRIES["uk"])

    # ── Identity ──────────────────────────────────────────────────────────
    lot_id = str(
        raw.get("vehicleId") or raw.get("id") or raw.get("lotId") or
        raw.get("lot_number") or ""
    ).strip()

    if not lot_id:
        return None

    lot_number = f"{lot_id}-BCA-{config['country_code']}"
    vin = (raw.get("vin") or raw.get("VIN") or raw.get("registrationNumber") or "").strip().upper()

    # ── Vehicle info ──────────────────────────────────────────────────────
    year_raw = (
        raw.get("year") or raw.get("modelYear") or raw.get("registrationYear") or
        raw.get("firstRegistrationYear")
    )
    try:
        year = int(str(year_raw)) if year_raw else None
    except (ValueError, TypeError):
        year = None

    make = (raw.get("make") or raw.get("manufacturer") or "").strip().title()
    model = (raw.get("model") or raw.get("modelName") or "").strip().title()
    trim = (raw.get("trim") or raw.get("variant") or raw.get("derivative") or "").strip()
    body_style = (raw.get("bodyStyle") or raw.get("bodyType") or raw.get("body") or "").strip()
    color = (raw.get("colour") or raw.get("color") or raw.get("exteriorColour") or "").strip()
    engine = (raw.get("engine") or raw.get("engineDescription") or "").strip()
    fuel = (raw.get("fuelType") or raw.get("fuel") or "").strip().lower()
    transmission = (raw.get("transmission") or raw.get("gearbox") or "").strip()
    drive = (raw.get("driveType") or raw.get("drive") or "").strip()

    # ── Odometer ──────────────────────────────────────────────────────────
    odo_raw = raw.get("mileage") or raw.get("odometer") or raw.get("kilometres") or 0
    try:
        odometer = int(str(odo_raw).replace(",", "").split()[0])
    except (ValueError, TypeError, IndexError):
        odometer = None

    odo_unit = config["odo_unit"]

    # ── Condition ─────────────────────────────────────────────────────────
    # BCA vehicles are mostly fleet/lease — usually clean title
    title_type = "clean"
    damage = (raw.get("damage") or raw.get("damageDescription") or "").strip()
    grade = (raw.get("grade") or raw.get("conditionGrade") or "").strip()

    # ── Price ─────────────────────────────────────────────────────────────
    price_raw = (
        raw.get("currentBid") or raw.get("startingBid") or
        raw.get("reservePrice") or raw.get("price") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("£", "").replace("€", ""))
    except (ValueError, TypeError):
        price = 0.0

    currency = config["currency"]

    # ── Location ──────────────────────────────────────────────────────────
    location_raw = raw.get("location") or raw.get("saleLocation") or {}
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "") or location_raw.get("name", "")
        state = location_raw.get("county", "") or location_raw.get("region", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    # ── Auction date ──────────────────────────────────────────────────────
    auction_date = (
        raw.get("auctionDate") or raw.get("saleDate") or
        raw.get("endDate") or raw.get("lotEndDate") or ""
    )

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
    elif raw.get("imageUrl") or raw.get("primaryImage"):
        images = [raw.get("imageUrl") or raw.get("primaryImage")]

    # ── Detail URL ────────────────────────────────────────────────────────
    detail_url = (
        raw.get("url") or raw.get("detailUrl") or raw.get("vehicleUrl") or
        f"https://www.bca.co.uk/vehicle/{lot_id}"
    )

    return {
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": SOURCE_TAG,
        "source_country": config["country_code"],
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
        "auction_grade": grade,
        "has_keys": True,    # BCA fleet vehicles always have keys
        "runs_drives": True, # Fleet vehicles are running
        "current_bid": price,
        "currency": currency,
        "location_city": city,
        "location_state": state,
        "location_country": config["country_code"],
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": f"bca_{country}",
    }


class BCAScraper:
    """High-level BCA Europe scraper supporting multiple countries."""

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        country: str = "uk",
        make: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of normalized BCA vehicles."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            raw_items = _fetch_bca_page(
                self.session, country=country, page=page,
                make=make, year_min=year_min, year_max=year_max,
                delay=self.delay,
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
                norm = normalize_bca_record(raw, country=country)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    def fetch_all_countries(
        self,
        countries: Optional[List[str]] = None,
        max_pages_per_country: int = 20,
    ) -> Generator[List[Dict], None, None]:
        """Fetch from multiple BCA countries in sequence."""
        if countries is None:
            countries = list(BCA_COUNTRIES.keys())

        for country in countries:
            logger.info("[BCA] Starting country: %s", country.upper())
            yield from self.fetch_pages(country=country, max_pages=max_pages_per_country)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

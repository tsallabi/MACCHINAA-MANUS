"""
MACCHINAA-EVOLVED — Manheim Scraper
======================================
جلب السيارات من Manheim — أكبر مزاد سيارات للتجار في العالم

  - 100+ موقع في USA
  - 10 مليون سيارة سنوياً
  - مملوك لـ Cox Automotive
  - يتطلب dealer account للوصول الكامل
  - سيارات تجار (Dealer Trade-ins) بحالة جيدة

المصادر:
  1. Manheim Market Report API (يحتاج OAuth2)
  2. OVE.com (Online Vehicle Exchange) — Manheim's online platform
  3. Manheim Express — mobile app API

الاستخدام:
    from scrapers.manheim.scraper import ManheimScraper
    scraper = ManheimScraper(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET"
    )
    for batch in scraper.fetch_pages(make="Toyota"):
        process(batch)
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SOURCE_TAG = "MANHEIM"

# Manheim API endpoints
MANHEIM_TOKEN_URL = "https://id.manheim.com/oauth2/token"
MANHEIM_SEARCH_URL = "https://api.manheim.com/listings/search"
MANHEIM_VEHICLE_URL = "https://api.manheim.com/listings/{listing_id}"

# OVE.com (Manheim's online auction platform)
OVE_SEARCH_URL = "https://www.ove.com/api/search/vehicles"

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


def _get_manheim_token(
    session: requests.Session,
    client_id: str,
    client_secret: str,
) -> Optional[str]:
    """Get OAuth2 access token from Manheim."""
    try:
        resp = session.post(
            MANHEIM_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "openid profile email",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.warning("[Manheim] Token request failed: %s", resp.status_code)
        return None
    except Exception as exc:
        logger.error("[Manheim] Token error: %s", exc)
        return None


def _fetch_manheim_page(
    session: requests.Session,
    access_token: str,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch one page from Manheim API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    params: Dict[str, Any] = {
        "page": page,
        "pageSize": 50,
        "sortBy": "auctionDate",
        "sortOrder": "asc",
        "status": "active",
    }
    if make:
        params["make"] = make
    if year_min:
        params["yearMin"] = year_min
    if year_max:
        params["yearMax"] = year_max

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(
            MANHEIM_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            logger.warning("[Manheim] Unauthorized — token may have expired")
            return []

        if resp.status_code != 200:
            logger.warning("[Manheim] HTTP %s page %d", resp.status_code, page)
            return []

        data = resp.json()
        return data.get("listings") or data.get("results") or data.get("data") or []

    except Exception as exc:
        logger.error("[Manheim] Page %d error: %s", page, exc)
        return []


def _fetch_ove_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch from OVE.com (Manheim's online platform, no auth needed for public listings)."""
    params: Dict[str, Any] = {
        "page": page,
        "perPage": 50,
        "auctionType": "online",
    }
    if make:
        params["make"] = make

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(OVE_SEARCH_URL, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("vehicles") or data.get("results") or []
    except Exception as exc:
        logger.error("[Manheim/OVE] Page %d error: %s", page, exc)
        return []


def normalize_manheim_record(raw: Dict) -> Optional[Dict]:
    """Normalize a Manheim listing to AuctionVehicle format."""
    if not raw:
        return None

    listing_id = str(
        raw.get("listingId") or raw.get("id") or raw.get("vehicleId") or ""
    ).strip()

    if not listing_id:
        return None

    lot_number = f"{listing_id}-MANHEIM"
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

    # Manheim vehicles are mostly clean title dealer trade-ins
    title_raw = (raw.get("titleType") or raw.get("title_type") or "clean").lower()
    if "clean" in title_raw:
        title_type = "clean"
    elif "salvage" in title_raw:
        title_type = "salvage"
    elif "rebuilt" in title_raw:
        title_type = "rebuilt"
    else:
        title_type = "clean"

    damage = (raw.get("damage") or raw.get("damageDescription") or "").strip()
    mmr = raw.get("mmr") or raw.get("manheimMarketReport") or 0  # Manheim Market Report value

    price_raw = (
        raw.get("currentBid") or raw.get("startingBid") or
        raw.get("reservePrice") or raw.get("price") or 0
    )
    try:
        price = float(str(price_raw).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        price = 0.0

    location_raw = raw.get("location") or raw.get("auctionLocation") or {}
    if isinstance(location_raw, dict):
        city = location_raw.get("city", "")
        state = location_raw.get("state", "")
    else:
        parts = str(location_raw).split(",")
        city = parts[0].strip() if parts else ""
        state = parts[1].strip() if len(parts) > 1 else ""

    auction_date = (
        raw.get("auctionDate") or raw.get("saleDate") or
        raw.get("endDate") or ""
    )

    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
    elif raw.get("imageUrl"):
        images = [raw["imageUrl"]]

    detail_url = (
        raw.get("url") or raw.get("detailUrl") or
        f"https://www.manheim.com/members/vehicles/{listing_id}"
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
        "estimated_retail_value": float(mmr) if mmr else None,
        "currency": "USD",
        "location_city": city,
        "location_state": state,
        "location_country": "US",
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "manheim_api",
    }


class ManheimScraper:
    """High-level Manheim scraper with OAuth2 support."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        delay: float = 1.5,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.delay = delay
        self.session = _make_session()
        self._access_token: Optional[str] = None
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def _ensure_token(self) -> bool:
        """Ensure we have a valid access token."""
        if not self.client_id or not self.client_secret:
            return False
        if not self._access_token:
            self._access_token = _get_manheim_token(
                self.session, self.client_id, self.client_secret
            )
        return bool(self._access_token)

    def fetch_pages(
        self,
        make: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of normalized Manheim vehicles."""
        use_api = self._ensure_token()

        consecutive_empty = 0
        for page in range(1, max_pages + 1):
            if use_api and self._access_token:
                raw_items = _fetch_manheim_page(
                    self.session, self._access_token,
                    page=page, make=make,
                    year_min=year_min, year_max=year_max,
                    delay=self.delay,
                )
            else:
                # Fallback to OVE.com
                raw_items = _fetch_ove_page(
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
                norm = normalize_manheim_record(raw)
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

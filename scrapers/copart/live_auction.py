"""
MACCHINAA-EVOLVED — Copart Live Auction Scraper
================================================
جلب بيانات المزادات الحية من Copart في الوقت الفعلي.

Copart Live Auction يعمل بنظام WebSocket + REST API:
  - كل يوم اثنين-جمعة: مزادات حية من الساعة 9 صباحاً حتى 5 مساءً (بتوقيت أمريكا)
  - الحصول على قائمة المزادات الحية الحالية
  - متابعة أسعار المزايدة في الوقت الفعلي
  - إشعار عند انتهاء كل مزاد

الاستخدام:
    from scrapers.copart.live_auction import CopartLiveAuction
    
    live = CopartLiveAuction()
    
    # جلب المزادات الحية الآن
    auctions = live.get_live_auctions()
    
    # متابعة سيارة معينة
    lot = live.get_lot_details("12345678")
    
    # جلب كل السيارات في مزاد حي
    for batch in live.stream_live_lots(lane_id="TX001"):
        process(batch)
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

# ── Copart API Endpoints ──────────────────────────────────────────────────
COPART_BASE = "https://www.copart.com"
COPART_API = "https://api.copart.com"

# Live auction endpoints
COPART_LIVE_AUCTIONS = f"{COPART_BASE}/public/data/lotdetails/liveauctions"
COPART_LIVE_LANES    = f"{COPART_BASE}/public/data/lotdetails/liveauctions/lanes"
COPART_LOT_DETAILS   = f"{COPART_BASE}/public/data/lotdetails/solr/lotDetails/mobileV2"
COPART_SEARCH_URL    = f"{COPART_BASE}/public/data/search/run"

# Copart GraphQL (discovered)
COPART_GRAPHQL = f"{COPART_BASE}/graphql"

# Copart public search API
COPART_SEARCH_API = f"{COPART_BASE}/public/data/search/run"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# ── Copart Damage Codes ───────────────────────────────────────────────────
COPART_DAMAGE = {
    "FRNT": "Front End",
    "REAR": "Rear End",
    "SIDE": "Side",
    "MNOR": "Minor Dents/Scratches",
    "FIRE": "Fire/Burn",
    "WTER": "Water/Flood",
    "HAIL": "Hail",
    "MECH": "Mechanical",
    "VAND": "Vandalism",
    "ROLL": "Rollover",
    "UNKN": "Unknown",
    "NONE": "",
}

# ── Copart Sale Status ────────────────────────────────────────────────────
COPART_STATUS = {
    "A": "active",
    "F": "future",
    "P": "pending",
    "S": "sold",
    "O": "on_hold",
}

# ── Copart Title Codes ────────────────────────────────────────────────────
COPART_TITLE = {
    "SV": "salvage",
    "CL": "clean",
    "RB": "rebuilt",
    "NU": "non_repairable",
    "SC": "salvage_certificate",
    "CC": "certificate_of_destruction",
    "EL": "enhanced_vehicle",
    "TT": "title_absent",
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.copart.com/",
        "Origin": "https://www.copart.com",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    })
    return session


def _fetch_copart_search(
    session: requests.Session,
    query: str = "",
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    page: int = 0,
    page_size: int = 100,
    delay: float = 1.5,
    live_only: bool = False,
) -> Dict:
    """Fetch from Copart search API."""

    filters: Dict[str, Any] = {}

    if make:
        filters["MAKE"] = [make.upper()]
    if model:
        filters["MODEL"] = [model.upper()]
    if year_min or year_max:
        year_filter = {}
        if year_min:
            year_filter["from"] = year_min
        if year_max:
            year_filter["to"] = year_max
        filters["YEAR"] = year_filter
    if live_only:
        filters["SALE_STATUS"] = ["A"]  # Active = in live auction

    payload = {
        "query": [query or "*"],
        "filter": filters,
        "sort": None,
        "page": page,
        "size": page_size,
        "start": page * page_size,
        "watchListOnly": False,
        "freeFormSearch": False,
        "hideFilters": False,
        "defaultSort": False,
        "specificRowProviders": [],
        "updateFacets": True,
        "rawParams": {},
    }

    try:
        time.sleep(delay + random.uniform(0.2, 0.6))
        resp = session.post(
            COPART_SEARCH_API,
            json=payload,
            timeout=30,
        )

        if resp.status_code == 429:
            logger.warning("[Copart] Rate limited — sleeping 30s")
            time.sleep(30)
            return {}

        if resp.status_code != 200:
            logger.warning("[Copart] HTTP %s page %d", resp.status_code, page)
            return {}

        return resp.json()

    except Exception as exc:
        logger.error("[Copart] Search error page %d: %s", page, exc)
        return {}


def _fetch_lot_details(
    session: requests.Session,
    lot_number: str,
    delay: float = 0.5,
) -> Dict:
    """Fetch detailed lot info from Copart."""
    try:
        time.sleep(delay + random.uniform(0.1, 0.3))
        url = f"{COPART_LOT_DETAILS}/{lot_number}"
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("lotDetails", {}) or data
        return {}
    except Exception as exc:
        logger.debug("[Copart] Lot detail error %s: %s", lot_number, exc)
        return {}


def _fetch_live_auctions(session: requests.Session) -> List[Dict]:
    """Fetch currently live auctions from Copart."""
    try:
        resp = session.get(COPART_LIVE_AUCTIONS, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return (
                data.get("data", {}).get("liveAuctions", [])
                or data.get("liveAuctions", [])
                or []
            )
        return []
    except Exception as exc:
        logger.error("[Copart Live] Error fetching live auctions: %s", exc)
        return []


def _fetch_live_lanes(session: requests.Session, sale_id: str) -> List[Dict]:
    """Fetch lanes for a specific live auction sale."""
    try:
        url = f"{COPART_LIVE_LANES}/{sale_id}"
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            return (
                data.get("data", {}).get("lanes", [])
                or data.get("lanes", [])
                or []
            )
        return []
    except Exception as exc:
        logger.debug("[Copart Live] Lanes error for sale %s: %s", sale_id, exc)
        return []


def normalize_copart_record(raw: Dict) -> Optional[Dict]:
    """
    Normalize a Copart search result to AuctionVehicle format.
    Works for both regular search results and live auction lots.
    """
    if not raw:
        return None

    # Copart uses different field names in different endpoints
    lot_number = str(
        raw.get("ln") or raw.get("lotNumberStr") or raw.get("lot_number") or ""
    ).strip()
    if not lot_number:
        return None

    vin = (raw.get("fv") or raw.get("vin") or "").strip().upper()
    make = (raw.get("mkn") or raw.get("make") or "").strip().title()
    model = (raw.get("mdn") or raw.get("model") or "").strip().title()
    trim = (raw.get("trim") or "").strip()
    year_raw = raw.get("lcy") or raw.get("year")
    try:
        year = int(year_raw) if year_raw else None
    except (ValueError, TypeError):
        year = None

    # Odometer
    odo_raw = raw.get("orr") or raw.get("od") or raw.get("odometer") or 0
    try:
        odometer = int(float(str(odo_raw).replace(",", "")))
    except (ValueError, TypeError):
        odometer = None

    odo_unit_raw = (raw.get("ord") or "mi").lower()
    odometer_unit = "km" if "km" in odo_unit_raw else "miles"

    # Color
    color = (raw.get("clr") or raw.get("color") or "").strip()

    # Fuel & Engine
    fuel_type = (raw.get("ft") or raw.get("fuelType") or "petrol").lower()
    engine = (raw.get("egn") or raw.get("engine") or "").strip()
    drive_type = (raw.get("drv") or raw.get("driveType") or "").upper()
    body_style = (raw.get("bstl") or raw.get("bodyStyle") or "").strip()
    transmission = (raw.get("tsmn") or raw.get("transmission") or "").lower()

    # Title
    title_code = raw.get("ttle") or raw.get("titleType") or "SV"
    title_type = COPART_TITLE.get(title_code, "salvage")

    # Damage
    dmg1_code = raw.get("dd") or raw.get("primaryDamage") or "UNKN"
    dmg2_code = raw.get("sdd") or raw.get("secondaryDamage") or "NONE"
    primary_damage = COPART_DAMAGE.get(dmg1_code, dmg1_code)
    secondary_damage = COPART_DAMAGE.get(dmg2_code, dmg2_code)

    # Price / Bid
    current_bid = 0.0
    buy_now = None

    bid_raw = raw.get("la") or raw.get("currentBid") or raw.get("bid") or 0
    try:
        current_bid = float(bid_raw)
    except (ValueError, TypeError):
        current_bid = 0.0

    buy_now_raw = raw.get("bn") or raw.get("buyNow")
    if buy_now_raw:
        try:
            buy_now = float(buy_now_raw)
        except (ValueError, TypeError):
            buy_now = None

    # Auction date
    sale_date_raw = raw.get("ad") or raw.get("saleDate") or raw.get("auctionDate") or ""
    try:
        if isinstance(sale_date_raw, (int, float)):
            sale_date = datetime.fromtimestamp(sale_date_raw / 1000, tz=timezone.utc).isoformat()
        else:
            sale_date = str(sale_date_raw)
    except Exception:
        sale_date = str(sale_date_raw)

    # Status
    status_code = raw.get("ss") or raw.get("saleStatus") or "A"
    status = COPART_STATUS.get(status_code, "active")

    # Location
    city = (raw.get("yn") or raw.get("city") or "").strip()
    state = (raw.get("stn") or raw.get("state") or "").strip()

    # Images
    images = []
    img_thumb = raw.get("tims") or raw.get("thumbnailImage") or ""
    if img_thumb:
        # Convert thumbnail to full size
        full_img = img_thumb.replace("_thb.", "_ful.").replace("_thumb.", "_full.")
        images.append(full_img)
        images.append(img_thumb)

    # High-res images from lotImages
    lot_imgs = raw.get("imgs") or raw.get("lotImages") or []
    if isinstance(lot_imgs, list):
        for img in lot_imgs[:20]:
            url = img.get("url", img) if isinstance(img, dict) else str(img)
            if url and url not in images:
                images.append(url)

    # Keys & Drivability
    has_keys_raw = raw.get("hk") or raw.get("hasKeys") or "Y"
    has_keys = str(has_keys_raw).upper() in ("Y", "YES", "TRUE", "1")

    runs_drives_raw = raw.get("rd") or raw.get("runsDrives") or "N"
    runs_drives = str(runs_drives_raw).upper() in ("Y", "YES", "TRUE", "1")

    # Seller type
    seller_type = (raw.get("sellerType") or raw.get("slt") or "insurance").lower()

    detail_url = f"{COPART_BASE}/lot/{lot_number}"

    # Is this a live auction lot?
    is_live = raw.get("isLive") or status == "active"

    return {
        "lot_number": lot_number,
        "vin": vin,
        "source_auction": "COPART",
        "source_country": "US",
        "source_url": detail_url,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "body_style": body_style,
        "color": color,
        "engine": engine,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "drive_type": drive_type,
        "odometer": odometer,
        "odometer_unit": odometer_unit,
        "title_type": title_type,
        "damage_primary": primary_damage,
        "damage_secondary": secondary_damage,
        "has_keys": has_keys,
        "runs_drives": runs_drives,
        "current_bid": current_bid,
        "buy_now_price": buy_now,
        "currency": "USD",
        "location_city": city,
        "location_state": state,
        "location_country": "US",
        "auction_date": sale_date,
        "status": status,
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "copart_api",
        # Copart-specific
        "is_live_auction": is_live,
        "seller_type": seller_type,
    }


class CopartScraper:
    """
    Copart Auctions scraper — regular + live auction support.
    """

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        max_pages: int = 100,
        page_size: int = 100,
        live_only: bool = False,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of Copart vehicles."""
        consecutive_empty = 0

        for page in range(0, max_pages):
            data = _fetch_copart_search(
                self.session,
                make=make,
                model=model,
                year_min=year_min,
                year_max=year_max,
                page=page,
                page_size=page_size,
                delay=self.delay,
                live_only=live_only,
            )

            if not data:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            # Copart wraps results in data.results.content
            results = (
                data.get("data", {}).get("results", {}).get("content", [])
                or data.get("results", {}).get("content", [])
                or data.get("content", [])
                or []
            )

            if not results:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            total = (
                data.get("data", {}).get("results", {}).get("totalElements", 0)
                or data.get("totalElements", 0)
            )
            self._stats["fetched"] += len(results)

            batch = []
            for raw in results:
                norm = normalize_copart_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

            # Check if done
            if total and ((page + 1) * page_size) >= total:
                break

    @property
    def stats(self) -> Dict:
        return dict(self._stats)


class CopartLiveAuction:
    """
    Copart Live Auction Monitor — يتابع المزادات الحية في الوقت الفعلي.

    الاستخدام:
        live = CopartLiveAuction()

        # جلب المزادات الحية الآن
        auctions = live.get_live_auctions()
        print(f"مزادات حية: {len(auctions)}")

        # جلب السيارات في مزاد حي
        for batch in live.stream_live_lots():
            for car in batch:
                print(f"{car['year']} {car['make']} {car['model']} - ${car['current_bid']}")

        # متابعة سيارة معينة
        lot = live.watch_lot("12345678", interval=10)
    """

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.session = _make_session()

    def get_live_auctions(self) -> List[Dict]:
        """
        جلب قائمة المزادات الحية الآن.
        يُرجع قائمة بمعلومات كل مزاد حي.
        """
        logger.info("[Copart Live] Fetching live auctions...")
        auctions = _fetch_live_auctions(self.session)

        if not auctions:
            # Fallback: search for active lots
            logger.info("[Copart Live] No live auctions found via direct endpoint, trying search...")
            data = _fetch_copart_search(
                self.session,
                live_only=True,
                page_size=10,
                delay=self.delay,
            )
            results = (
                data.get("data", {}).get("results", {}).get("content", [])
                or []
            )
            total = (
                data.get("data", {}).get("results", {}).get("totalElements", 0)
                or 0
            )
            return [{
                "source": "copart_search",
                "total_active_lots": total,
                "sample_lots": [normalize_copart_record(r) for r in results[:5] if r],
            }]

        return auctions

    def stream_live_lots(
        self,
        lane_id: Optional[str] = None,
        make: Optional[str] = None,
        max_lots: int = 500,
    ) -> Generator[List[Dict], None, None]:
        """
        جلب السيارات من المزادات الحية.
        يُنتج دفعات من السيارات المعروضة حالياً في المزادات الحية.
        """
        logger.info("[Copart Live] Streaming live lots...")

        # First get live auctions
        live_auctions = _fetch_live_auctions(self.session)

        if live_auctions:
            for auction in live_auctions:
                sale_id = auction.get("saleId") or auction.get("id") or ""
                if not sale_id:
                    continue

                # Get lanes for this auction
                lanes = _fetch_live_lanes(self.session, sale_id)
                for lane in lanes:
                    if lane_id and lane.get("laneId") != lane_id:
                        continue

                    lots = lane.get("lots") or []
                    batch = []
                    for raw in lots:
                        raw["isLive"] = True
                        norm = normalize_copart_record(raw)
                        if norm:
                            batch.append(norm)
                    if batch:
                        yield batch
        else:
            # Fallback: search for active lots
            logger.info("[Copart Live] Falling back to active lot search...")
            scraper = CopartScraper(delay=self.delay)
            pages = max(1, max_lots // 100)
            yield from scraper.fetch_pages(
                make=make,
                live_only=True,
                max_pages=pages,
            )

    def get_lot_details(self, lot_number: str) -> Optional[Dict]:
        """جلب تفاصيل سيارة محددة من Copart."""
        raw = _fetch_lot_details(self.session, lot_number, delay=self.delay)
        if raw:
            raw["isLive"] = True
            return normalize_copart_record(raw)
        return None

    def watch_lot(
        self,
        lot_number: str,
        interval: int = 10,
        max_checks: int = 60,
    ) -> Generator[Dict, None, None]:
        """
        متابعة سيارة في المزاد الحي — يُرجع التحديثات كل `interval` ثانية.

        Args:
            lot_number: رقم الـ lot في Copart
            interval: الفاصل الزمني بالثواني بين كل فحص
            max_checks: أقصى عدد مرات الفحص
        """
        logger.info("[Copart Live] Watching lot %s every %ds", lot_number, interval)
        last_bid = 0.0

        for check in range(max_checks):
            lot = self.get_lot_details(lot_number)
            if lot:
                current_bid = lot.get("current_bid", 0.0)
                if current_bid != last_bid:
                    lot["bid_changed"] = True
                    lot["bid_increase"] = current_bid - last_bid
                    last_bid = current_bid
                    yield lot
                else:
                    lot["bid_changed"] = False
                    yield lot

            # Check if auction ended
            if lot and lot.get("status") == "sold":
                logger.info("[Copart Live] Lot %s sold for $%.0f", lot_number, last_bid)
                break

            time.sleep(interval)

    def get_today_schedule(self) -> List[Dict]:
        """جلب جدول مزادات Copart لليوم."""
        try:
            resp = self.session.get(
                f"{COPART_BASE}/public/data/lotdetails/liveauctions/schedule",
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("schedule", []) or []
            return []
        except Exception as exc:
            logger.error("[Copart Live] Schedule error: %s", exc)
            return []

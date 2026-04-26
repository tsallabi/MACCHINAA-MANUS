"""
MACCHINAA-EVOLVED — ACV Auctions Scraper (USA)
================================================
جلب السيارات من ACV Auctions — أكبر منصة مزادات B2B للسيارات في أمريكا

  - 300,000+ سيارة شهرياً
  - مزادات مباشرة (Live) وعروض ثابتة (Buy Now)
  - سيارات من وكلاء ومن الأسطول التجاري
  - تقييم حالة السيارة بنظام ACV الخاص (0-5 نجوم)
  - صور 360° عالية الجودة
  - تقرير Carfax مدمج

لماذا ACV مهم للسوق الليبي؟
  - أسعار أقل من Copart وIAAI (لأنها B2B)
  - سيارات بحالة أفضل عموماً (من وكلاء)
  - تقارير حالة موثّقة بالصور
  - شحن من أي ميناء أمريكي

API:
  - ACV لديه API رسمي للوكلاء (يتطلب تسجيل)
  - يوجد أيضاً طريقة GraphQL مكتشفة
  - Fallback: scraping مع Selenium

الاستخدام:
    from scrapers.acv.acv_scraper import ACVScraper
    
    # مع credentials
    scraper = ACVScraper(username="dealer@email.com", password="pass")
    for batch in scraper.fetch_pages(make="Toyota", year_min=2019):
        process(batch)
    
    # بدون credentials (محدود)
    scraper = ACVScraper()
    for batch in scraper.fetch_public_listings():
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

SOURCE_TAG = "ACV"

# ── ACV API Endpoints ─────────────────────────────────────────────────────
ACV_BASE_URL = "https://app.acvauctions.com"
ACV_API_BASE = "https://api.acvauctions.com"
ACV_AUTH_URL = f"{ACV_API_BASE}/auth/login"
ACV_SEARCH_URL = f"{ACV_API_BASE}/v2/vehicles/search"
ACV_DETAIL_URL = f"{ACV_API_BASE}/v2/vehicles/{{}}"
ACV_GRAPHQL_URL = f"{ACV_API_BASE}/graphql"

# Public/semi-public endpoints
ACV_PUBLIC_SEARCH = "https://app.acvauctions.com/api/v1/search"

# ── ACV Condition Grade Mapping ───────────────────────────────────────────
# ACV uses a proprietary condition grading system
ACV_CONDITION_MAP = {
    5: "excellent",
    4: "good",
    3: "fair",
    2: "poor",
    1: "salvage",
    0: "unknown",
}

# ── ACV Sale Type ─────────────────────────────────────────────────────────
ACV_SALE_TYPE = {
    "AUCTION": "auction",
    "BUY_NOW": "buy_now",
    "MAKE_OFFER": "make_offer",
    "IF_BID": "if_bid",
}

# ── Damage Codes ──────────────────────────────────────────────────────────
ACV_DAMAGE_CODES = {
    "FRONT": "Front damage",
    "REAR": "Rear damage",
    "LEFT": "Left side damage",
    "RIGHT": "Right side damage",
    "ROOF": "Roof damage",
    "UNDERCARRIAGE": "Undercarriage damage",
    "HAIL": "Hail damage",
    "FLOOD": "Flood damage",
    "FIRE": "Fire damage",
    "MECHANICAL": "Mechanical issue",
    "NONE": "",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


def _make_session(token: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://app.acvauctions.com",
        "Referer": "https://app.acvauctions.com/",
    })
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _authenticate(username: str, password: str) -> Optional[str]:
    """Authenticate with ACV Auctions and return JWT token."""
    session = _make_session()
    try:
        payload = {"username": username, "password": password}
        resp = session.post(ACV_AUTH_URL, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            token = (
                data.get("token")
                or data.get("access_token")
                or data.get("accessToken")
                or data.get("jwt")
            )
            if token:
                logger.info("[ACV] Authentication successful")
                return token
        logger.warning("[ACV] Auth failed: HTTP %s", resp.status_code)
        return None
    except Exception as exc:
        logger.error("[ACV] Auth error: %s", exc)
        return None


def _fetch_acv_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_max: Optional[float] = None,
    condition_min: int = 2,
    page_size: int = 50,
    delay: float = 1.5,
) -> Dict:
    """Fetch one page from ACV search API."""
    payload: Dict[str, Any] = {
        "page": page,
        "pageSize": page_size,
        "sortBy": "listingDate",
        "sortOrder": "desc",
        "filters": {
            "status": ["ACTIVE", "LIVE"],
        },
    }

    if make:
        payload["filters"]["make"] = [make]
    if model:
        payload["filters"]["model"] = [model]
    if year_min or year_max:
        payload["filters"]["year"] = {}
        if year_min:
            payload["filters"]["year"]["min"] = year_min
        if year_max:
            payload["filters"]["year"]["max"] = year_max
    if price_max:
        payload["filters"]["price"] = {"max": price_max}
    if condition_min:
        payload["filters"]["conditionGrade"] = {"min": condition_min}

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.post(ACV_SEARCH_URL, json=payload, timeout=30)

        if resp.status_code == 401:
            logger.warning("[ACV] Unauthorized — token may have expired")
            return {}

        if resp.status_code == 429:
            logger.warning("[ACV] Rate limited — sleeping 30s")
            time.sleep(30)
            return {}

        if resp.status_code != 200:
            logger.warning("[ACV] HTTP %s page %d", resp.status_code, page)
            return {}

        return resp.json()

    except Exception as exc:
        logger.error("[ACV] Page %d error: %s", page, exc)
        return {}


def _fetch_acv_graphql(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    delay: float = 1.5,
) -> Dict:
    """Alternative: fetch via GraphQL endpoint."""
    query = """
    query SearchVehicles($input: VehicleSearchInput!) {
      searchVehicles(input: $input) {
        totalCount
        vehicles {
          id
          vin
          year
          make
          model
          trim
          mileage
          color
          fuelType
          transmission
          driveType
          titleType
          conditionGrade
          currentBid
          buyNowPrice
          auctionEndTime
          saleType
          primaryImage
          images
          location {
            city
            state
            zip
          }
          damage {
            primary
            secondary
          }
          acvScore
          hasKeys
          runsDrives
          sellerType
        }
      }
    }
    """
    variables = {
        "input": {
            "page": page,
            "pageSize": 50,
            "filters": {},
        }
    }
    if make:
        variables["input"]["filters"]["make"] = make
    if year_min:
        variables["input"]["filters"]["yearMin"] = year_min

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.post(
            ACV_GRAPHQL_URL,
            json={"query": query, "variables": variables},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("searchVehicles", {})
        return {}
    except Exception as exc:
        logger.debug("[ACV GraphQL] Error: %s", exc)
        return {}


def normalize_acv_record(raw: Dict) -> Optional[Dict]:
    """
    Normalize an ACV Auctions record to AuctionVehicle format.
    """
    if not raw:
        return None

    vehicle_id = str(
        raw.get("id") or raw.get("vehicleId") or raw.get("lotId") or ""
    ).strip()
    if not vehicle_id:
        return None

    lot_number = f"{vehicle_id}-ACV"

    # ── Basic Info ────────────────────────────────────────────────────────
    make = (raw.get("make") or "").strip().title()
    model = (raw.get("model") or "").strip()
    trim = (raw.get("trim") or raw.get("grade") or "").strip()
    vin = (raw.get("vin") or "").strip().upper()

    year_raw = raw.get("year") or raw.get("modelYear")
    try:
        year = int(year_raw) if year_raw else None
    except (ValueError, TypeError):
        year = None

    # ── Odometer ──────────────────────────────────────────────────────────
    odo_raw = raw.get("mileage") or raw.get("odometer") or 0
    try:
        odometer = int(float(str(odo_raw).replace(",", "")))
    except (ValueError, TypeError):
        odometer = None

    # ── Vehicle Specs ─────────────────────────────────────────────────────
    color = (raw.get("color") or raw.get("exteriorColor") or "").strip()
    fuel_type = (raw.get("fuelType") or raw.get("fuel") or "petrol").lower().strip()
    transmission = (raw.get("transmission") or "").lower().strip()
    drive_type = (raw.get("driveType") or raw.get("driveTrain") or "").upper().strip()
    engine = (raw.get("engine") or raw.get("engineSize") or "").strip()
    body_style = (raw.get("bodyStyle") or raw.get("bodyType") or "").strip()

    # ── Title & Condition ─────────────────────────────────────────────────
    title_type_raw = (raw.get("titleType") or raw.get("title") or "clean").lower()
    if "salvage" in title_type_raw:
        title_type = "salvage"
    elif "rebuilt" in title_type_raw or "reconstructed" in title_type_raw:
        title_type = "rebuilt"
    elif "lemon" in title_type_raw:
        title_type = "lemon"
    else:
        title_type = "clean"

    # ── ACV Condition Grade (0-5) ─────────────────────────────────────────
    condition_grade = raw.get("conditionGrade") or raw.get("acvScore") or 0
    try:
        condition_grade = int(float(condition_grade))
    except (ValueError, TypeError):
        condition_grade = 0
    condition_label = ACV_CONDITION_MAP.get(condition_grade, "unknown")

    # ── Damage ────────────────────────────────────────────────────────────
    damage_info = raw.get("damage") or {}
    if isinstance(damage_info, dict):
        primary_damage_code = damage_info.get("primary", "NONE")
        secondary_damage_code = damage_info.get("secondary", "NONE")
    else:
        primary_damage_code = str(damage_info) if damage_info else "NONE"
        secondary_damage_code = "NONE"

    primary_damage = ACV_DAMAGE_CODES.get(primary_damage_code, primary_damage_code)
    secondary_damage = ACV_DAMAGE_CODES.get(secondary_damage_code, secondary_damage_code)

    # ── Price ─────────────────────────────────────────────────────────────
    current_bid = 0.0
    buy_now = None

    price_raw = raw.get("currentBid") or raw.get("currentPrice") or raw.get("price") or 0
    try:
        current_bid = float(price_raw)
    except (ValueError, TypeError):
        current_bid = 0.0

    buy_now_raw = raw.get("buyNowPrice") or raw.get("buyItNow")
    if buy_now_raw:
        try:
            buy_now = float(buy_now_raw)
        except (ValueError, TypeError):
            buy_now = None

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    primary_img = raw.get("primaryImage") or raw.get("mainImage") or ""
    if primary_img:
        images.append(primary_img)

    extra_imgs = raw.get("images") or raw.get("photos") or []
    if isinstance(extra_imgs, list):
        for img in extra_imgs[:20]:
            url = img.get("url", img) if isinstance(img, dict) else str(img)
            if url and url not in images:
                images.append(url)

    # ── Location ──────────────────────────────────────────────────────────
    loc = raw.get("location") or {}
    if isinstance(loc, dict):
        city = loc.get("city", "")
        state = loc.get("state", "")
    else:
        city = str(loc)
        state = ""

    # ── Auction Timing ────────────────────────────────────────────────────
    auction_end = raw.get("auctionEndTime") or raw.get("endTime") or ""
    sale_type_raw = raw.get("saleType") or "AUCTION"
    sale_type = ACV_SALE_TYPE.get(sale_type_raw, "auction")

    # ── Seller Type ───────────────────────────────────────────────────────
    seller_type = (raw.get("sellerType") or "dealer").lower()

    # ── Keys & Drivability ────────────────────────────────────────────────
    has_keys = raw.get("hasKeys", True)
    runs_drives = raw.get("runsDrives", True)

    # ── ACV Score (proprietary 0-100) ─────────────────────────────────────
    acv_score = raw.get("acvScore") or raw.get("vehicleScore") or 0

    detail_url = f"{ACV_BASE_URL}/vehicle/{vehicle_id}"

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
        "body_style": body_style,
        "color": color,
        "engine": engine,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "drive_type": drive_type,
        "odometer": odometer,
        "odometer_unit": "miles",
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
        "auction_date": str(auction_end),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "acv_api",
        # ACV-specific extras
        "acv_condition_grade": condition_grade,
        "acv_condition_label": condition_label,
        "acv_score": acv_score,
        "sale_type": sale_type,
        "seller_type": seller_type,
    }


class ACVScraper:
    """
    ACV Auctions scraper — B2B dealer auction platform.

    يدعم:
    1. API رسمي مع credentials (للوكلاء المسجلين)
    2. GraphQL endpoint (مكتشف)
    3. Public listings (محدود)
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_token: Optional[str] = None,
        delay: float = 1.5,
    ):
        """
        Args:
            username: بريد الوكيل المسجل في ACV
            password: كلمة المرور
            api_token: JWT token مباشرة (إذا كان متاحاً)
            delay: التأخير بين الطلبات
        """
        self.delay = delay
        self._token = api_token

        # Try to authenticate if credentials provided
        if username and password and not api_token:
            self._token = _authenticate(username, password)

        self.session = _make_session(self._token)
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}
        self._authenticated = bool(self._token)

    def fetch_pages(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        price_max: Optional[float] = None,
        condition_min: int = 2,
        max_pages: int = 100,
        page_size: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """
        Generator يُنتج دفعات من سيارات ACV.

        Args:
            make: الماركة (Toyota, Honda, Ford...)
            model: الموديل
            year_min: سنة الصنع الأدنى
            year_max: سنة الصنع الأعلى
            price_max: السعر الأقصى بالدولار
            condition_min: الحد الأدنى لتقييم ACV (1-5)
            max_pages: عدد الصفحات الأقصى
            page_size: عدد السيارات في كل صفحة
        """
        if not self._authenticated:
            logger.warning(
                "[ACV] Not authenticated — trying GraphQL fallback"
            )
            yield from self._fetch_via_graphql(make=make, year_min=year_min)
            return

        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            data = _fetch_acv_page(
                self.session,
                page=page,
                make=make,
                model=model,
                year_min=year_min,
                year_max=year_max,
                price_max=price_max,
                condition_min=condition_min,
                page_size=page_size,
                delay=self.delay,
            )

            if not data:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            raw_items = (
                data.get("vehicles")
                or data.get("results")
                or data.get("data")
                or []
            )

            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            total = data.get("totalCount") or data.get("total") or 0
            self._stats["fetched"] += len(raw_items)

            batch = []
            for raw in raw_items:
                norm = normalize_acv_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

            # Check if done
            if total and (page * page_size) >= total:
                break

    def _fetch_via_graphql(
        self,
        make: Optional[str] = None,
        year_min: Optional[int] = None,
        max_pages: int = 20,
    ) -> Generator[List[Dict], None, None]:
        """Fallback: fetch via GraphQL."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            data = _fetch_acv_graphql(
                self.session, page=page, make=make,
                year_min=year_min, delay=self.delay,
            )

            if not data:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            raw_items = data.get("vehicles", [])
            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            self._stats["fetched"] += len(raw_items)

            batch = []
            for raw in raw_items:
                norm = normalize_acv_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1

            if batch:
                yield batch

    def fetch_by_condition(
        self,
        min_grade: int = 3,
        max_pages: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """Fetch vehicles filtered by ACV condition grade (3-5 = good to excellent)."""
        yield from self.fetch_pages(condition_min=min_grade, max_pages=max_pages)

    def fetch_hot_deals(
        self,
        max_price: float = 15000,
        min_year: int = 2018,
        max_pages: int = 30,
    ) -> Generator[List[Dict], None, None]:
        """Fetch hot deals: newer cars under a price threshold."""
        yield from self.fetch_pages(
            year_min=min_year,
            price_max=max_price,
            condition_min=3,
            max_pages=max_pages,
        )

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    @property
    def stats(self) -> Dict:
        return dict(self._stats)

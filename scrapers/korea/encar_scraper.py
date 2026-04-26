"""
MACCHINAA-EVOLVED — Encar.com Scraper (Korea)
===============================================
جلب السيارات من Encar.com — أكبر سوق سيارات مستعملة في كوريا الجنوبية

  - 218,000+ سيارة نشطة
  - تحديث يومي
  - API مباشر بدون مصادقة (للبحث العام)
  - سيارات كورية (Hyundai, Kia, Genesis) وسيارات مستوردة

لماذا كوريا مهمة للسوق الليبي؟
  - Hyundai Tucson, Santa Fe, Palisade بأسعار ممتازة
  - Kia Sportage, Sorento, Telluride
  - Genesis GV80, GV70 (فاخرة بأسعار معقولة)
  - سيارات بحالة ممتازة مع تاريخ صيانة موثّق
  - شحن من ميناء بوسان → مصراتة: ~$1,400-1,800
  - وقت الشحن: 25-35 يوم

API Endpoints المكتشفة:
  - البحث:  https://api.encar.com/search/car/list/general
  - التفاصيل: https://api.encar.com/v1/readside/vehicle/{id}
  - الصور:  https://ci.encar.com{photo_path}

الاستخدام:
    from scrapers.korea.encar_scraper import EncarScraper
    scraper = EncarScraper()
    for batch in scraper.fetch_pages(make="현대", model="싼타페"):
        process(batch)

    # أو بالإنجليزية
    for batch in scraper.fetch_by_english_make("Hyundai"):
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

SOURCE_TAG = "ENCAR_KR"

# ── Encar API Endpoints ────────────────────────────────────────────────────
ENCAR_SEARCH_URL = "https://api.encar.com/search/car/list/general"
ENCAR_DETAIL_URL = "https://api.encar.com/v1/readside/vehicle/{vehicle_id}"
ENCAR_PHOTO_BASE = "https://ci.encar.com"
ENCAR_VEHICLE_PAGE = "https://www.encar.com/dc/dc_cardetailview.do?carid={vehicle_id}"

# ── Korean Make Name Mapping ──────────────────────────────────────────────
# Korean name → English name
MAKE_KO_TO_EN = {
    "현대":   "Hyundai",
    "기아":   "Kia",
    "제네시스": "Genesis",
    "쌍용":   "SsangYong",
    "르노코리아": "Renault Korea",
    "쉐보레":  "Chevrolet",
    "BMW":   "BMW",
    "벤츠":   "Mercedes-Benz",
    "아우디":  "Audi",
    "폭스바겐": "Volkswagen",
    "도요타":  "Toyota",
    "렉서스":  "Lexus",
    "혼다":   "Honda",
    "포르쉐":  "Porsche",
    "볼보":   "Volvo",
    "랜드로버": "Land Rover",
    "재규어":  "Jaguar",
    "미니":   "MINI",
    "닛산":   "Nissan",
    "인피니티": "Infiniti",
    "마쓰다":  "Mazda",
    "스바루":  "Subaru",
    "포드":   "Ford",
    "링컨":   "Lincoln",
    "지프":   "Jeep",
    "캐딜락":  "Cadillac",
    "크라이슬러": "Chrysler",
    "테슬라":  "Tesla",
    "BYD":   "BYD",
    "이수":   "Isuzu",
}

# English make → Korean name (for search)
MAKE_EN_TO_KO = {v: k for k, v in MAKE_KO_TO_EN.items()}

# ── Hot Models for Libya ──────────────────────────────────────────────────
LIBYA_HOT_KOREAN = {
    "Hyundai": ["싼타페", "팰리세이드", "투싼", "그랜저", "쏘나타", "아이오닉5"],
    "Kia":     ["쏘렌토", "텔루라이드", "스포티지", "K8", "K5", "EV6"],
    "Genesis": ["GV80", "GV70", "G80", "GV60"],
    "SsangYong": ["렉스턴", "코란도"],
}

# ── Fuel type mapping ─────────────────────────────────────────────────────
FUEL_KO_TO_EN = {
    "가솔린":    "petrol",
    "디젤":     "diesel",
    "가솔린+전기": "hybrid",
    "디젤+전기":  "hybrid",
    "전기":     "electric",
    "LPG":    "lpg",
    "수소":     "hydrogen",
}

# ── Transmission mapping ──────────────────────────────────────────────────
TRANS_KO_TO_EN = {
    "오토": "automatic",
    "수동": "manual",
    "CVT": "cvt",
    "DCT": "dct",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
        "Referer": "https://www.encar.com/",
        "Origin": "https://www.encar.com",
    })
    return session


def _build_search_query(
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_max_krw: Optional[int] = None,
    fuel_type: Optional[str] = None,
    domestic_only: bool = False,
) -> str:
    """Build Encar search query string."""
    conditions = [
        "Hidden.N",
        "SellType.일반",
        "CarType.A",  # A = 일반 (regular cars)
    ]

    if make:
        # Convert English to Korean if needed
        ko_make = MAKE_EN_TO_KO.get(make, make)
        conditions.append(f"Manufacturer.{ko_make}")

    if model:
        conditions.append(f"Model.{model}")

    if year_min:
        conditions.append(f"Year.{year_min * 100:08d}")

    if price_max_krw:
        conditions.append(f"Price.~{price_max_krw}")

    if fuel_type:
        ko_fuel = {v: k for k, v in FUEL_KO_TO_EN.items()}.get(fuel_type, fuel_type)
        conditions.append(f"FuelType.{ko_fuel}")

    if domestic_only:
        conditions.append("Domestic.Y")

    query = "(And." + "._.".join(conditions) + ".)"
    return query


def _fetch_encar_page(
    session: requests.Session,
    page: int = 0,
    make: Optional[str] = None,
    model: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    price_max_krw: Optional[int] = None,
    page_size: int = 50,
    delay: float = 1.5,
) -> Dict:
    """Fetch one page from Encar search API."""
    query = _build_search_query(
        make=make, model=model,
        year_min=year_min, year_max=year_max,
        price_max_krw=price_max_krw,
    )

    params = {
        "count": "true",
        "q": query,
        "sr": f"|ModifiedDate|{page * page_size}|{page_size}",
    }

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(ENCAR_SEARCH_URL, params=params, timeout=30)

        if resp.status_code == 429:
            logger.warning("[Encar] Rate limited — sleeping 30s")
            time.sleep(30)
            return {}

        if resp.status_code != 200:
            logger.warning("[Encar] HTTP %s page %d", resp.status_code, page)
            return {}

        return resp.json()

    except Exception as exc:
        logger.error("[Encar] Page %d error: %s", page, exc)
        return {}


def _fetch_encar_detail(
    session: requests.Session,
    vehicle_id: str,
    delay: float = 0.5,
) -> Dict:
    """Fetch detailed vehicle info from Encar."""
    try:
        time.sleep(delay + random.uniform(0.1, 0.3))
        url = ENCAR_DETAIL_URL.format(vehicle_id=vehicle_id)
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception as exc:
        logger.debug("[Encar] Detail fetch error for %s: %s", vehicle_id, exc)
        return {}


def _krw_to_usd(man_won: float, rate: float = 1350.0) -> float:
    """
    Convert Encar price (in 만원 = 10,000 KRW units) to USD.
    Example: 3270 만원 = 32,700,000 KRW ÷ 1350 = $24,222 USD
    Default rate: 1 USD ≈ 1350 KRW
    """
    if not man_won:
        return 0.0
    krw = float(man_won) * 10000  # Convert 만원 to KRW
    return round(krw / rate, 2)


def normalize_encar_record(raw: Dict, detail: Optional[Dict] = None) -> Optional[Dict]:
    """
    Normalize an Encar.com record to AuctionVehicle format.

    raw: from search API (list endpoint)
    detail: from detail API (optional, for richer data)
    """
    if not raw:
        return None

    vehicle_id = str(raw.get("Id", "")).strip()
    if not vehicle_id:
        return None

    lot_number = f"{vehicle_id}-ENCAR"

    # ── Make & Model ──────────────────────────────────────────────────────
    make_ko = (raw.get("Manufacturer") or "").strip()
    make_en = MAKE_KO_TO_EN.get(make_ko, make_ko)

    model_ko = (raw.get("Model") or "").strip()
    trim_ko = (raw.get("Badge") or "").strip()

    # Use English names from detail if available
    if detail:
        cat = detail.get("category", {})
        make_en = cat.get("manufacturerEnglishName") or make_en
        model_en = cat.get("modelGroupEnglishName") or model_ko
        trim_en = cat.get("gradeEnglishName") or trim_ko
    else:
        model_en = model_ko  # Keep Korean if no detail
        trim_en = trim_ko

    # ── Year ──────────────────────────────────────────────────────────────
    year_raw = raw.get("FormYear") or raw.get("Year")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except (ValueError, TypeError):
        year = None

    # ── Odometer ──────────────────────────────────────────────────────────
    odo_raw = raw.get("Mileage") or 0
    try:
        odometer = int(float(str(odo_raw).replace(",", "")))
    except (ValueError, TypeError):
        odometer = None

    # ── Fuel & Transmission ───────────────────────────────────────────────
    fuel_ko = (raw.get("FuelType") or "").strip()
    fuel_en = FUEL_KO_TO_EN.get(fuel_ko, "petrol")

    # From detail
    transmission = ""
    color = ""
    engine_cc = None
    body_style = ""
    if detail:
        spec = detail.get("spec", {})
        trans_ko = spec.get("transmissionName", "")
        transmission = TRANS_KO_TO_EN.get(trans_ko, trans_ko)
        color_ko = spec.get("colorName", "")
        color = color_ko  # Keep Korean color name for now
        engine_cc = spec.get("displacement")
        body_ko = spec.get("bodyName", "")
        body_style = body_ko

    # ── Price (Encar uses 만원 = 10,000 KRW units) ────────────────────────────────────
    price_man_won = raw.get("Price") or 0
    try:
        price_man_won_f = float(price_man_won)
        price_krw = price_man_won_f * 10000  # Convert 만원 to KRW
        price_usd = _krw_to_usd(price_man_won_f)  # Pass 만원 value
    except (ValueError, TypeError):
        price_krw = 0.0
        price_usd = 0.0

    # ── Images ────────────────────────────────────────────────────────────
    images = []
    photo_base = raw.get("Photo", "")
    if photo_base:
        # Main photo
        images.append(f"{ENCAR_PHOTO_BASE}{photo_base}001.jpg")

    # From detail photos
    if detail and detail.get("photos"):
        for photo in detail["photos"][:15]:
            path = photo.get("path", "")
            if path:
                img_url = f"{ENCAR_PHOTO_BASE}{path}"
                if img_url not in images:
                    images.append(img_url)

    # ── Location ──────────────────────────────────────────────────────────
    city_ko = raw.get("OfficeCityState", "")
    # Map Korean city names
    CITY_MAP = {
        "서울": "Seoul", "부산": "Busan", "인천": "Incheon",
        "대구": "Daegu", "대전": "Daejeon", "광주": "Gwangju",
        "수원": "Suwon", "성남": "Seongnam", "고양": "Goyang",
        "울산": "Ulsan", "창원": "Changwon",
    }
    city_en = CITY_MAP.get(city_ko, city_ko)

    # ── Title type ────────────────────────────────────────────────────────
    # Encar vehicles are generally clean title (Korean market)
    # Check for accident history in conditions
    conditions = raw.get("Condition", [])
    has_record = "Record" in conditions  # Has accident/repair record
    has_inspection = "Inspection" in conditions

    title_type = "clean"
    damage = ""

    if detail:
        # Check accident info
        accident = detail.get("accident", {})
        if accident:
            total_loss = accident.get("totalLoss", False)
            if total_loss:
                title_type = "salvage"
            elif accident.get("accidentCount", 0) > 0:
                damage = f"Accident history: {accident.get('accidentCount', 0)} incidents"

    # ── Quality indicators ────────────────────────────────────────────────
    is_verified = "Inspection" in conditions
    has_warranty = "ExtendWarranty" in raw.get("Trust", [])
    is_home_service = raw.get("HomeServiceVerification") == "Y"

    # ── Detail URL ────────────────────────────────────────────────────────
    detail_url = ENCAR_VEHICLE_PAGE.format(vehicle_id=vehicle_id)

    # ── Shipping estimate to Libya ─────────────────────────────────────────
    # Korea (Busan) → Libya (Misrata): ~$1,600
    shipping_estimate = 1600

    return {
        "lot_number": lot_number,
        "vin": "",  # Encar doesn't expose VIN in public API
        "source_auction": SOURCE_TAG,
        "source_country": "KR",
        "source_url": detail_url,
        "year": year,
        "make": make_en,
        "model": model_en,
        "trim": trim_en,
        "body_style": body_style,
        "color": color,
        "engine": f"{engine_cc}cc" if engine_cc else "",
        "fuel_type": fuel_en,
        "transmission": transmission,
        "drive_type": "",
        "odometer": odometer,
        "odometer_unit": "km",
        "title_type": title_type,
        "damage_primary": damage,
        "has_keys": True,
        "runs_drives": True,
        "current_bid": price_usd,
        "currency": "USD",
        "location_city": city_en,
        "location_state": "South Korea",
        "location_country": "KR",
        "auction_date": "",
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "encar_api",
        # Korea-specific extras
        "price_krw": price_krw,
        "has_inspection_record": has_record,
        "is_verified": is_verified,
        "has_warranty": has_warranty,
        "is_home_service": is_home_service,
        "shipping_estimate_usd": shipping_estimate,
        "make_korean": make_ko,
        "model_korean": model_ko,
    }


class EncarScraper:
    """
    High-level Encar.com scraper.

    يجلب السيارات من Encar.com مباشرةً عبر API بدون مصادقة.
    218,000+ سيارة متاحة.
    """

    def __init__(self, delay: float = 1.5, fetch_details: bool = False):
        """
        Args:
            delay: التأخير بين الطلبات بالثواني
            fetch_details: جلب تفاصيل كل سيارة (أبطأ لكن بيانات أغنى)
        """
        self.delay = delay
        self.fetch_details = fetch_details
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        make: Optional[str] = None,
        model: Optional[str] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        price_max_usd: Optional[float] = None,
        max_pages: int = 100,
        page_size: int = 50,
    ) -> Generator[List[Dict], None, None]:
        """
        Generator يُنتج دفعات من السيارات الكورية.

        Args:
            make: اسم الماركة بالإنجليزية (Hyundai, Kia, Genesis...)
            model: اسم الموديل بالكورية أو الإنجليزية
            year_min: سنة الصنع الأدنى
            year_max: سنة الصنع الأعلى
            price_max_usd: السعر الأقصى بالدولار
            max_pages: عدد الصفحات الأقصى
            page_size: عدد السيارات في كل صفحة
        """
        # Convert USD to KRW (in 만원 units)
        price_max_krw = None
        if price_max_usd:
            price_max_krw = int(price_max_usd * 1350 / 10000)

        consecutive_empty = 0

        for page in range(0, max_pages):
            data = _fetch_encar_page(
                self.session,
                page=page,
                make=make,
                model=model,
                year_min=year_min,
                year_max=year_max,
                price_max_krw=price_max_krw,
                page_size=page_size,
                delay=self.delay,
            )

            if not data:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            raw_items = data.get("SearchResults", [])
            total = data.get("Count", 0)

            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            self._stats["fetched"] += len(raw_items)

            # Check if we've fetched all available items
            fetched_so_far = (page + 1) * page_size
            if fetched_so_far >= total:
                logger.info("[Encar] Fetched all %d vehicles", total)

            batch = []
            for raw in raw_items:
                # Optionally fetch detailed info
                detail = None
                if self.fetch_details:
                    vehicle_id = str(raw.get("Id", ""))
                    if vehicle_id:
                        detail = _fetch_encar_detail(
                            self.session, vehicle_id, delay=0.3
                        )

                norm = normalize_encar_record(raw, detail=detail)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

            # Stop if we've reached the end
            if fetched_so_far >= total:
                break

    def fetch_by_english_make(
        self,
        make_en: str,
        max_pages: int = 50,
        **kwargs,
    ) -> Generator[List[Dict], None, None]:
        """Fetch vehicles by English make name."""
        yield from self.fetch_pages(make=make_en, max_pages=max_pages, **kwargs)

    def fetch_hot_models_for_libya(
        self,
        max_pages: int = 20,
    ) -> Generator[List[Dict], None, None]:
        """Fetch hot Korean models for the Libyan market."""
        for make_en, models_ko in LIBYA_HOT_KOREAN.items():
            for model_ko in models_ko:
                logger.info("[Encar] Fetching hot model: %s %s", make_en, model_ko)
                yield from self.fetch_pages(
                    make=make_en,
                    model=model_ko,
                    max_pages=max_pages,
                )

    def get_total_count(self, make: Optional[str] = None) -> int:
        """Get total available vehicles count."""
        data = _fetch_encar_page(self.session, page=0, make=make, page_size=1, delay=0.5)
        return data.get("Count", 0)

    @property
    def stats(self) -> Dict:
        return dict(self._stats)

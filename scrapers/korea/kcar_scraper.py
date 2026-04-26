"""
MACCHINAA-EVOLVED — KCar & AJ Auction Scraper (Korea)
=======================================================
جلب السيارات من مصادر كورية متعددة:

  1. KCar (케이카) — ثاني أكبر سوق سيارات مستعملة في كوريا
     - سيارات معتمدة بضمان
     - تاريخ صيانة كامل
     - 30,000+ سيارة

  2. AJ Auction (AJ셀카) — مزاد سيارات كوري متخصص
     - مزادات يومية
     - سيارات تجارية وخاصة
     - أسعار أقل من السوق

  3. SK Encar Auction — مزاد B2B كوري
     - سيارات عائدة من الإيجار
     - حالة ممتازة عادةً
     - مزادات كل خميس في أوسان

  4. Glovis Auction (هيونداي) — مزاد هيونداي/كيا الرسمي
     - سيارات مستعملة هيونداي وكيا
     - مضمونة من الشركة

الاستخدام:
    from scrapers.korea.kcar_scraper import KCarScraper, AJAuctionScraper
    
    kcar = KCarScraper()
    for batch in kcar.fetch_pages(make="Hyundai"):
        process(batch)
    
    aj = AJAuctionScraper()
    for batch in aj.fetch_pages():
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

# ── KCar API ──────────────────────────────────────────────────────────────
KCAR_SEARCH_URL = "https://www.kcar.com/api/v1/vehicles/search"
KCAR_DETAIL_URL = "https://www.kcar.com/api/v1/vehicles/{vehicle_id}"
KCAR_VEHICLE_PAGE = "https://www.kcar.com/vehicle/{vehicle_id}"

# ── AJ셀카 (AJ Auction) ────────────────────────────────────────────────────
AJ_SEARCH_URL = "https://www.ajcelka.com/api/search/vehicles"
AJ_AUCTION_URL = "https://www.ajcelka.com/auction/live"

# ── SK Encar Auction ──────────────────────────────────────────────────────
SK_ENCAR_URL = "https://auction.encar.com/api/v1/lots"

# ── Glovis Auction ────────────────────────────────────────────────────────
GLOVIS_URL = "https://www.glovisauction.com/api/vehicles"

# ── AuctionWini (Korean Salvage) ──────────────────────────────────────────
AUCTIONWINI_URL = "https://www.auctionwini.com/api/v1/vehicles"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# Korean make → English
MAKE_KO_TO_EN = {
    "현대": "Hyundai", "기아": "Kia", "제네시스": "Genesis",
    "쌍용": "SsangYong", "르노코리아": "Renault Korea",
    "쉐보레": "Chevrolet", "BMW": "BMW", "벤츠": "Mercedes-Benz",
    "아우디": "Audi", "폭스바겐": "Volkswagen", "도요타": "Toyota",
    "렉서스": "Lexus", "혼다": "Honda", "포르쉐": "Porsche",
    "볼보": "Volvo", "테슬라": "Tesla",
}

FUEL_KO_TO_EN = {
    "가솔린": "petrol", "디젤": "diesel",
    "가솔린+전기": "hybrid", "전기": "electric", "LPG": "lpg",
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    return session


def _krw_to_usd(krw_man_won: float, rate: float = 1350.0) -> float:
    """Convert 만원 (10,000 KRW) to USD."""
    return round(float(krw_man_won) * 10000 / rate, 2) if krw_man_won else 0.0


# ══════════════════════════════════════════════════════════════════════════
#  KCAR SCRAPER
# ══════════════════════════════════════════════════════════════════════════

def _fetch_kcar_page(
    session: requests.Session,
    page: int = 1,
    make: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch from KCar API."""
    params: Dict[str, Any] = {
        "page": page,
        "size": 50,
        "sort": "registDate,desc",
        "status": "ON_SALE",
    }
    if make:
        # Convert English to Korean
        ko_makes = {v: k for k, v in MAKE_KO_TO_EN.items()}
        params["manufacturer"] = ko_makes.get(make, make)
    if year_min:
        params["yearFrom"] = year_min
    if year_max:
        params["yearTo"] = year_max

    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(KCAR_SEARCH_URL, params=params, timeout=30)
        if resp.status_code != 200:
            logger.warning("[KCar] HTTP %s page %d", resp.status_code, page)
            return []
        data = resp.json()
        return data.get("content") or data.get("vehicles") or data.get("data") or []
    except Exception as exc:
        logger.error("[KCar] Page %d error: %s", page, exc)
        return []


def normalize_kcar_record(raw: Dict) -> Optional[Dict]:
    """Normalize a KCar record."""
    if not raw:
        return None

    vehicle_id = str(
        raw.get("vehicleId") or raw.get("id") or raw.get("stockNo") or ""
    ).strip()
    if not vehicle_id:
        return None

    lot_number = f"{vehicle_id}-KCAR"

    make_ko = (raw.get("manufacturer") or raw.get("make") or "").strip()
    make_en = MAKE_KO_TO_EN.get(make_ko, make_ko)
    model_ko = (raw.get("model") or "").strip()
    trim_ko = (raw.get("grade") or raw.get("trim") or "").strip()

    year_raw = raw.get("year") or raw.get("modelYear")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except (ValueError, TypeError):
        year = None

    odo_raw = raw.get("mileage") or raw.get("odometer") or 0
    try:
        odometer = int(float(str(odo_raw).replace(",", "")))
    except (ValueError, TypeError):
        odometer = None

    fuel_ko = (raw.get("fuelType") or "").strip()
    fuel_en = FUEL_KO_TO_EN.get(fuel_ko, "petrol")

    price_raw = raw.get("price") or raw.get("salePrice") or 0
    price_usd = _krw_to_usd(float(price_raw)) if price_raw else 0.0

    color_ko = (raw.get("color") or raw.get("exteriorColor") or "").strip()

    images = []
    if raw.get("images"):
        imgs = raw["images"]
        if isinstance(imgs, list):
            images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:15]]
    elif raw.get("mainImage") or raw.get("imageUrl"):
        images = [raw.get("mainImage") or raw.get("imageUrl")]

    city_ko = (raw.get("location") or raw.get("region") or "").strip()
    CITY_MAP = {
        "서울": "Seoul", "부산": "Busan", "인천": "Incheon",
        "대구": "Daegu", "대전": "Daejeon", "광주": "Gwangju",
    }
    city_en = CITY_MAP.get(city_ko, city_ko)

    detail_url = KCAR_VEHICLE_PAGE.format(vehicle_id=vehicle_id)

    # KCar vehicles are certified used cars — generally clean
    has_accident = raw.get("accidentHistory") or raw.get("hasAccident") or False
    title_type = "salvage" if has_accident else "clean"
    damage = "Accident history recorded" if has_accident else ""

    return {
        "lot_number": lot_number,
        "vin": (raw.get("vin") or "").strip().upper(),
        "source_auction": "KCAR_KR",
        "source_country": "KR",
        "source_url": detail_url,
        "year": year,
        "make": make_en,
        "model": model_ko,
        "trim": trim_ko,
        "color": color_ko,
        "fuel_type": fuel_en,
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
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "kcar_api",
    }


class KCarScraper:
    """KCar certified used car scraper."""

    def __init__(self, delay: float = 1.5):
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
        """Generator yielding batches of KCar vehicles."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            raw_items = _fetch_kcar_page(
                self.session, page=page, make=make,
                year_min=year_min, year_max=year_max,
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
                norm = normalize_kcar_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    @property
    def stats(self) -> Dict:
        return dict(self._stats)


# ══════════════════════════════════════════════════════════════════════════
#  AJ AUCTION SCRAPER
# ══════════════════════════════════════════════════════════════════════════

def _fetch_aj_page(
    session: requests.Session,
    page: int = 1,
    delay: float = 1.5,
) -> List[Dict]:
    """Fetch from AJ셀카 auction."""
    params = {
        "page": page,
        "size": 50,
        "status": "AUCTION",
    }
    try:
        time.sleep(delay + random.uniform(0.3, 0.8))
        resp = session.get(AJ_SEARCH_URL, params=params, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("vehicles") or data.get("content") or data.get("data") or []
    except Exception as exc:
        logger.error("[AJ Auction] Page %d error: %s", page, exc)
        return []


def normalize_aj_record(raw: Dict) -> Optional[Dict]:
    """Normalize an AJ Auction record."""
    if not raw:
        return None

    vehicle_id = str(raw.get("lotId") or raw.get("vehicleId") or raw.get("id") or "").strip()
    if not vehicle_id:
        return None

    lot_number = f"{vehicle_id}-AJAUCTION"

    make_ko = (raw.get("manufacturer") or "").strip()
    make_en = MAKE_KO_TO_EN.get(make_ko, make_ko)
    model_ko = (raw.get("model") or "").strip()

    year_raw = raw.get("year") or raw.get("modelYear")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except (ValueError, TypeError):
        year = None

    odo_raw = raw.get("mileage") or 0
    try:
        odometer = int(float(str(odo_raw).replace(",", "")))
    except (ValueError, TypeError):
        odometer = None

    price_raw = raw.get("startBid") or raw.get("currentBid") or raw.get("price") or 0
    price_usd = _krw_to_usd(float(price_raw)) if price_raw else 0.0

    images = []
    if raw.get("images"):
        imgs = raw["images"]
        images = [i.get("url", i) if isinstance(i, dict) else str(i) for i in imgs[:10]]

    auction_date = raw.get("auctionDate") or raw.get("saleDate") or ""

    return {
        "lot_number": lot_number,
        "vin": (raw.get("vin") or "").strip().upper(),
        "source_auction": "AJAUCTION_KR",
        "source_country": "KR",
        "source_url": f"https://www.ajcelka.com/lot/{vehicle_id}",
        "year": year,
        "make": make_en,
        "model": model_ko,
        "trim": (raw.get("grade") or "").strip(),
        "color": (raw.get("color") or "").strip(),
        "fuel_type": FUEL_KO_TO_EN.get(raw.get("fuelType", ""), "petrol"),
        "odometer": odometer,
        "odometer_unit": "km",
        "title_type": "clean",
        "has_keys": True,
        "runs_drives": True,
        "current_bid": price_usd,
        "currency": "USD",
        "location_city": "Korea",
        "location_state": "South Korea",
        "location_country": "KR",
        "auction_date": str(auction_date),
        "status": "active",
        "primary_image": images[0] if images else "",
        "images_json": images,
        "raw_data": raw,
        "sync_source": "aj_auction_api",
    }


class AJAuctionScraper:
    """AJ셀카 Korean auction scraper."""

    def __init__(self, delay: float = 1.5):
        self.delay = delay
        self.session = _make_session()
        self._stats = {"fetched": 0, "normalized": 0, "errors": 0}

    def fetch_pages(
        self,
        max_pages: int = 30,
    ) -> Generator[List[Dict], None, None]:
        """Generator yielding batches of AJ Auction vehicles."""
        consecutive_empty = 0

        for page in range(1, max_pages + 1):
            raw_items = _fetch_aj_page(self.session, page=page, delay=self.delay)

            if not raw_items:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    break
                continue

            consecutive_empty = 0
            self._stats["fetched"] += len(raw_items)

            batch = []
            for raw in raw_items:
                norm = normalize_aj_record(raw)
                if norm:
                    batch.append(norm)
                    self._stats["normalized"] += 1
                else:
                    self._stats["errors"] += 1

            if batch:
                yield batch

    @property
    def stats(self) -> Dict:
        return dict(self._stats)

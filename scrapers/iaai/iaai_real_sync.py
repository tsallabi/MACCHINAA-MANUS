"""
iaai_real_sync.py — IAAI Scraper with Photos + Video + 360
===========================================================
Endpoints:
  api.iaai.com/search    -> car list
  vis.iaai.com/images    -> photos + engine video + 360

Usage:
    python manage.py iaai_real_sync
    python manage.py iaai_real_sync --make Toyota --pages 10
    python manage.py iaai_real_sync --fetch-images --dry-run
"""
from __future__ import annotations
import json, logging, sqlite3, ssl, time, urllib.request
from typing import Dict, List, Optional, Set
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("iaai_real_sync")

IAAI_SEARCH_URL = "https://api.iaai.com/search/vehicles"
IAAI_DIMS_URL   = "https://vis.iaai.com/dimensions?stockNumber={stock}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Accept":     "application/json",
    "Referer":    "https://www.iaai.com/",
    "Origin":     "https://www.iaai.com",
}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_iaai_media(stock_number: str) -> Dict:
    """
    يجلب الوسائط من vis.iaai.com:
    - صور عادية (imageList)
    - فيديو المحرك (engineVideo)
    - صور 360 درجة (imageList360)
    """
    url = IAAI_DIMS_URL.format(stock=stock_number)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=15)
        data = json.loads(resp.read())
        images, video, img_360 = [], "", []

        for img in data.get("imageList", []):
            key = img.get("imageKey", "")
            if key:
                images.append(f"https://vis.iaai.com/resizer?imageKeys={key}&width=640&height=480")

        ev = data.get("engineVideo", {})
        if ev and ev.get("url"):
            video = ev["url"]

        for frame in data.get("imageList360", []):
            key = frame.get("imageKey", "")
            if key:
                img_360.append(f"https://vis.iaai.com/resizer?imageKeys={key}&width=640&height=480")

        return {
            "images":  images,
            "video":   video,
            "img_360": img_360,
            "total":   len(images) + (1 if video else 0) + len(img_360),
        }
    except Exception as e:
        logger.debug("IAAI media %s: %s", stock_number, e)
        return {"images": [], "video": "", "img_360": [], "total": 0}


def search_iaai(make="", model="", page=0, size=100):
    payload = {
        "query": {"make": make or "", "model": model or ""},
        "pagination": {"page": page, "size": size},
        "sort": {"field": "auctionDateTime", "order": "asc"},
    }
    body = json.dumps(payload).encode()
    headers = {**HEADERS, "Content-Type": "application/json"}
    req = urllib.request.Request(IAAI_SEARCH_URL, data=body, headers=headers, method="POST")
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
    data = json.loads(resp.read())
    items = data.get("data", {}).get("results", []) or data.get("results", [])
    total = data.get("data", {}).get("totalCount", 0) or data.get("totalCount", 0)
    return items, total


def _s(v, n=500):
    return "" if v is None else str(v).strip()[:n]


def normalize_iaai(raw: Dict, media: Optional[Dict] = None) -> Dict:
    stock     = _s(raw.get("stockNumber") or raw.get("stockNum", ""))
    thumbnail = _s(raw.get("imageUrl") or raw.get("thumbnail", ""))
    media_json = ""
    if media and media.get("total", 0) > 0:
        media_json = json.dumps({
            "images":  media.get("images", []),
            "video":   media.get("video", ""),
            "img_360": media.get("img_360", []),
            "total":   media.get("total", 0),
        })
    elif thumbnail:
        media_json = json.dumps({"images": [thumbnail], "total": 1})

    return {
        "Lot_number":                  stock,
        "VIN":                         _s(raw.get("vin", "")),
        "Make":                        _s(raw.get("make", "")),
        "Model_Group":                 _s(raw.get("model", "")),
        "Year":                        _s(raw.get("year", "")),
        "Color":                       _s(raw.get("color", "")),
        "Body_Style":                  _s(raw.get("bodyStyle", "")),
        "Damage_Description":          _s(raw.get("primaryDamage", "")),
        "Secondary_Damage":            _s(raw.get("secondaryDamage", "")),
        "Odometer":                    _s(raw.get("odometer", "")),
        "Odometer_Brand":              _s(raw.get("odometerBrand", "")),
        "Engine":                      _s(raw.get("engine", "")),
        "Drive":                       _s(raw.get("driveType", "")),
        "Transmission":                _s(raw.get("transmission", "")),
        "Fuel_Type":                   _s(raw.get("fuelType", "")),
        "Cylinders":                   _s(raw.get("cylinders", "")),
        "Runs_Drives":                 "Y" if raw.get("runsDrives") else "N",
        "Has_Keys_Yes_or_No":          "Y" if raw.get("hasKeys") else "N",
        "Sale_Status":                 _s(raw.get("saleStatus", "active")),
        "High_Bid_non_vix_Sealed_Vix": _s(raw.get("currentBid", "")),
        "Est_Retail_Value":            _s(raw.get("estimatedRetailValue", "")),
        "Sale_Date_M_D_CY":            _s(raw.get("auctionDateTime", "")),
        "Yard_name":                   _s(raw.get("branchName") or raw.get("yard", "IAAI")),
        "Location_city":               _s(raw.get("city", "")),
        "Currency_Code":               "USD",
        "Title_Brand":                 _s(raw.get("titleBrand", "")),
        "all_auctions":                "IAAI",
        "Image_Thumbnail":             thumbnail,
        "Image_URL":                   media_json,
    }


def _get_existing(db_path: str) -> Set[str]:
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        rows = conn.execute(
            'SELECT "Lot_number" FROM "schedulars_manualcardata" WHERE "all_auctions"=?',
            ("IAAI",)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning("DB: %s", e)
        return set()


def _save_batch(cars: List[Dict], db_path: str, log_fn=print) -> int:
    if not cars:
        return 0
    conn = sqlite3.connect(db_path, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA journal_mode=WAL")
    saved = 0
    for car in cars:
        lot = car.get("Lot_number", "")
        if not lot:
            continue
        try:
            conn.execute("""
                INSERT OR REPLACE INTO "schedulars_manualcardata"
                ("Lot_number","VIN","Make","Model_Group","Year","Color","Body_Style",
                 "Damage_Description","Secondary_Damage","Odometer","Odometer_Brand",
                 "Engine","Drive","Transmission","Fuel_Type","Cylinders",
                 "Runs_Drives","Has_Keys_Yes_or_No","Sale_Status",
                 "High_Bid_non_vix_Sealed_Vix","Est_Retail_Value","Sale_Date_M_D_CY",
                 "Yard_name","Location_city","Currency_Code","Title_Brand",
                 "Image_Thumbnail","Image_URL","all_auctions")
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                lot, car.get("VIN",""), car.get("Make",""), car.get("Model_Group",""),
                car.get("Year",""), car.get("Color",""), car.get("Body_Style",""),
                car.get("Damage_Description",""), car.get("Secondary_Damage",""),
                car.get("Odometer",""), car.get("Odometer_Brand",""), car.get("Engine",""),
                car.get("Drive",""), car.get("Transmission",""), car.get("Fuel_Type",""),
                car.get("Cylinders",""), car.get("Runs_Drives",""), car.get("Has_Keys_Yes_or_No",""),
                car.get("Sale_Status","active"), car.get("High_Bid_non_vix_Sealed_Vix",""),
                car.get("Est_Retail_Value",""), car.get("Sale_Date_M_D_CY",""),
                car.get("Yard_name","IAAI"), car.get("Location_city",""),
                car.get("Currency_Code","USD"), car.get("Title_Brand",""),
                car.get("Image_Thumbnail",""), car.get("Image_URL",""), "IAAI",
            ))
            saved += 1
        except Exception as e:
            log_fn(f"  [DB] {lot}: {e}")
    conn.commit()
    conn.close()
    return saved


class Command(BaseCommand):
    help = "جلب السيارات من IAAI مع صور + فيديو المحرك + 360 درجة"

    def add_arguments(self, parser):
        parser.add_argument("--make",         type=str, default="")
        parser.add_argument("--model",        type=str, default="")
        parser.add_argument("--pages",        type=int, default=10)
        parser.add_argument("--size",         type=int, default=100)
        parser.add_argument("--fetch-images", action="store_true",
                            help="جلب الصور والفيديو من vis.iaai.com")
        parser.add_argument("--dry-run",      action="store_true")

    def handle(self, *args, **options):
        make       = options["make"]
        model      = options["model"]
        pages      = options["pages"]
        size       = options["size"]
        fetch_imgs = options["fetch_images"]
        dry        = options["dry_run"]

        def log(m): self.stdout.write(m)

        db_path = settings.DATABASES["default"]["NAME"]
        t0 = time.time()

        log("=" * 65)
        log("  IAAI REAL SYNC — api.iaai.com + vis.iaai.com")
        log("=" * 65)
        log(f"  الشركة: {make or 'الكل'} | صفحات: {pages} | صور: {'نعم' if fetch_imgs else 'لا'}")
        log("-" * 65)

        existing = _get_existing(db_path)
        log(f"  موجود في DB: {len(existing):,}")

        all_cars, total_count, total_saved = [], 0, 0

        for p in range(pages):
            try:
                items, total = search_iaai(make, model, p, size)
                if p == 0:
                    total_count = total
                    log(f"  إجمالي IAAI: {total_count:,}")

                new_items = [i for i in items
                             if _s(i.get("stockNumber") or i.get("stockNum","")) not in existing]
                log(f"  صفحة {p+1}/{pages}: {len(items)} | جديد: {len(new_items)}")

                if not items:
                    break

                for raw in new_items:
                    stock = _s(raw.get("stockNumber") or raw.get("stockNum",""))
                    if not stock:
                        continue
                    media = fetch_iaai_media(stock) if fetch_imgs else None
                    if fetch_imgs:
                        time.sleep(0.3)
                    car = normalize_iaai(raw, media)
                    all_cars.append(car)
                    existing.add(stock)

                if len(all_cars) >= 500 and not dry:
                    s = _save_batch(all_cars, db_path, log)
                    total_saved += s
                    log(f"  ✓ دفعة: {s}")
                    all_cars = []

                time.sleep(1)

            except Exception as e:
                log(f"  ❌ صفحة {p}: {e}")
                time.sleep(5)

        if all_cars and not dry:
            total_saved += _save_batch(all_cars, db_path, log)

        elapsed = time.time() - t0
        log(f"\n{'='*65}")
        log(f"  إجمالي: {total_count:,} | محفوظ: {total_saved} | {elapsed:.0f}s")
        log("=" * 65)

        if total_saved > 0:
            self.stdout.write(self.style.SUCCESS(f"\n  ✓ تم استيراد {total_saved} سيارة من IAAI!"))

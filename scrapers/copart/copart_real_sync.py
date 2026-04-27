"""
copart_real_sync.py — Copart Scraper with Photos + Video + 360
==============================================================
Endpoints:
  vehicleFinder/search  -> car list (open, no auth)
  imagesList.content    -> photos + video + 360 (works from your PC)

Usage:
    python manage.py copart_real_sync
    python manage.py copart_real_sync --make Toyota --pages 20
    python manage.py copart_real_sync --state TX --fetch-images
    python manage.py copart_real_sync --dry-run
"""
from __future__ import annotations
import json, logging, sqlite3, ssl, time, urllib.parse, urllib.request
from typing import Dict, List, Optional, Set
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("copart_real_sync")

VEHICLE_FINDER_URL = "https://www.copart.com/public/vehicleFinder/search"
LOT_IMAGES_URL     = "https://www.copart.com/public/data/lotdetails/solr/lotImages/{lot}/USA"

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.copart.com/lotSearchResults/",
    "Origin":          "https://www.copart.com",
}

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_lot_images(lot_number: str) -> Dict:
    """Fetch all media for one lot: photos, video, 360, inspection report"""
    url = LOT_IMAGES_URL.format(lot=lot_number)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=15)
        data = json.loads(resp.read())
        content = data.get("data", {}).get("imagesList", {}).get("content", [])
        result = {"images": [], "video": "", "video_360": [], "inspection": "", "total": 0}
        for item in content:
            mt  = item.get("mediaType", "")
            url_val = item.get("url", "")
            if not url_val:
                continue
            if mt == "IMG":
                result["images"].append(url_val)
            elif mt == "GOLTV":
                result["video"] = url_val
            elif mt == "CAR360":
                result["video_360"].append(url_val)
            elif mt == "ESINSP":
                result["inspection"] = url_val
        result["total"] = len(result["images"]) + (1 if result["video"] else 0) + len(result["video_360"])
        return result
    except Exception as e:
        logger.debug("Images %s: %s", lot_number, e)
        return {"images": [], "video": "", "video_360": [], "inspection": "", "total": 0}


def search_copart(query="", make="", state="", page=0, size=100):
    params = {
        "free":  "true",
        "query": query or make or "toyota",
        "page":  str(page),
        "size":  str(size),
        "sort":  "auction_date_type,asc",
    }
    if state:
        params["freeParams"] = f"auction_state_code:{state}"
    url = VEHICLE_FINDER_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
    data = json.loads(resp.read())
    content = data.get("data", {}).get("results", {}).get("content", [])
    total   = data.get("data", {}).get("results", {}).get("totalElements", 0)
    return content, total


def _s(v, n=500):
    return "" if v is None else str(v).strip()[:n]


def normalize_copart(raw: Dict, media: Optional[Dict] = None) -> Dict:
    lot       = _s(raw.get("lotNumberStr") or raw.get("ln") or raw.get("lotNumber", ""))
    thumbnail = _s(raw.get("tims") or raw.get("thumbnail", ""))
    media_json = ""
    if media and media.get("total", 0) > 0:
        media_json = json.dumps({
            "images":     media.get("images", []),
            "video":      media.get("video", ""),
            "video_360":  media.get("video_360", []),
            "inspection": media.get("inspection", ""),
            "total":      media.get("total", 0),
        })
    elif thumbnail:
        media_json = json.dumps({"images": [thumbnail], "total": 1})

    return {
        "Lot_number":                  lot,
        "VIN":                         _s(raw.get("fv") or raw.get("vin", "")),
        "Make":                        _s(raw.get("mkn") or raw.get("make", "")),
        "Model_Group":                 _s(raw.get("lm") or raw.get("model", "")),
        "Year":                        _s(raw.get("lcy") or raw.get("year", "")),
        "Color":                       _s(raw.get("clr") or raw.get("color", "")),
        "Body_Style":                  _s(raw.get("bstl") or raw.get("bodyStyle", "")),
        "Damage_Description":          _s(raw.get("dd") or raw.get("primaryDamage", "")),
        "Secondary_Damage":            _s(raw.get("sdd") or raw.get("secondaryDamage", "")),
        "Odometer":                    _s(raw.get("orr") or raw.get("odometer", "")),
        "Odometer_Brand":              _s(raw.get("tmtp") or raw.get("odometerBrand", "")),
        "Engine":                      _s(raw.get("egn") or raw.get("engine", "")),
        "Drive":                       _s(raw.get("drv") or raw.get("driveType", "")),
        "Transmission":                _s(raw.get("tsmn") or raw.get("transmission", "")),
        "Fuel_Type":                   _s(raw.get("ft") or raw.get("fuelType", "")),
        "Cylinders":                   _s(raw.get("cyl") or raw.get("cylinders", "")),
        "Runs_Drives":                 "Y" if str(raw.get("rd","")).upper() in ("YES","Y","TRUE","1") else "N",
        "Has_Keys_Yes_or_No":          "Y" if str(raw.get("hk","")).upper() in ("YES","Y","TRUE","1") else "N",
        "Sale_Status":                 _s(raw.get("ss") or raw.get("saleStatus", "")),
        "High_Bid_non_vix_Sealed_Vix": _s(raw.get("hb") or raw.get("currentBid", "")),
        "Est_Retail_Value":            _s(raw.get("la") or raw.get("estimatedRetailValue", "")),
        "Sale_Date_M_D_CY":            _s(raw.get("ad") or raw.get("auctionDate", "")),
        "Yard_name":                   _s(raw.get("yn") or raw.get("yardName", "Copart")),
        "Location_city":               _s(raw.get("yardCity") or raw.get("city", "")),
        "Currency_Code":               "USD",
        "Title_Brand":                 _s(raw.get("tb") or raw.get("titleBrand", "")),
        "all_auctions":                "COPART",
        "Image_Thumbnail":             thumbnail,
        "Image_URL":                   media_json,
    }


def _get_existing(db_path: str) -> Set[str]:
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        rows = conn.execute(
            'SELECT "Lot_number" FROM "schedulars_manualcardata" WHERE "all_auctions"=?',
            ("COPART",)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning("DB read: %s", e)
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
                car.get("Sale_Status",""), car.get("High_Bid_non_vix_Sealed_Vix",""),
                car.get("Est_Retail_Value",""), car.get("Sale_Date_M_D_CY",""),
                car.get("Yard_name","Copart"), car.get("Location_city",""),
                car.get("Currency_Code","USD"), car.get("Title_Brand",""),
                car.get("Image_Thumbnail",""), car.get("Image_URL",""), "COPART",
            ))
            saved += 1
        except Exception as e:
            log_fn(f"  [DB] {lot}: {e}")
    conn.commit()
    conn.close()
    return saved


class Command(BaseCommand):
    help = "جلب السيارات من Copart مع صور + فيديو + 360 درجة"

    def add_arguments(self, parser):
        parser.add_argument("--query",        type=str, default="")
        parser.add_argument("--make",         type=str, default="")
        parser.add_argument("--state",        type=str, default="")
        parser.add_argument("--pages",        type=int, default=10)
        parser.add_argument("--size",         type=int, default=100)
        parser.add_argument("--fetch-images", action="store_true",
                            help="جلب الصور والفيديو لكل سيارة (أبطأ لكن أكمل)")
        parser.add_argument("--dry-run",      action="store_true")

    def handle(self, *args, **options):
        query      = options["query"]
        make       = options["make"]
        state      = options["state"]
        pages      = options["pages"]
        size       = options["size"]
        fetch_imgs = options["fetch_images"]
        dry        = options["dry_run"]

        def log(m): self.stdout.write(m)

        db_path = settings.DATABASES["default"]["NAME"]
        t0 = time.time()

        log("=" * 65)
        log("  COPART REAL SYNC — vehicleFinder + imagesList.content")
        log("=" * 65)
        log(f"  الشركة: {make or 'الكل'} | الولاية: {state or 'الكل'} | صفحات: {pages}")
        log(f"  جلب الصور: {'نعم' if fetch_imgs else 'لا (أسرع)'}")
        log("-" * 65)

        existing = _get_existing(db_path)
        log(f"  موجود في DB: {len(existing):,}")

        all_cars, total_count, total_saved = [], 0, 0

        for p in range(pages):
            try:
                lots, total = search_copart(query, make, state, p, size)
                if p == 0:
                    total_count = total
                    log(f"  إجمالي Copart: {total_count:,}")

                new_lots = [l for l in lots
                            if _s(l.get("lotNumberStr") or l.get("ln","")) not in existing]
                log(f"  صفحة {p+1}/{pages}: {len(lots)} | جديد: {len(new_lots)}")

                if not lots:
                    break

                for raw in new_lots:
                    lot_num = _s(raw.get("lotNumberStr") or raw.get("ln",""))
                    if not lot_num:
                        continue
                    media = fetch_lot_images(lot_num) if fetch_imgs else None
                    if fetch_imgs:
                        time.sleep(0.3)
                    car = normalize_copart(raw, media)
                    all_cars.append(car)
                    existing.add(lot_num)

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
            self.stdout.write(self.style.SUCCESS(f"\n  ✓ تم استيراد {total_saved} سيارة من Copart!"))
        elif dry:
            log(f"\n  [DRY-RUN] سيتم حفظ {len(all_cars)} سيارة")

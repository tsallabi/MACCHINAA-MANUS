"""
adesa_real_sync.py — ADESA / OpenLane Scraper
==============================================
ADESA uses Auth0 + GraphQL API.
Requires: ADESA_CLIENT_ID + ADESA_CLIENT_SECRET in settings.py

Usage:
    python manage.py adesa_real_sync
    python manage.py adesa_real_sync --make Toyota --pages 5
    python manage.py adesa_real_sync --dry-run
"""
from __future__ import annotations
import json, logging, sqlite3, ssl, time, urllib.parse, urllib.request
from typing import Dict, List, Set
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("adesa_real_sync")

AUTH0_URL   = "https://auth.adesa.com/oauth/token"
GRAPHQL_URL = "https://api.adesa.com/graphql"
AUDIENCE    = "https://api.adesa.com"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

SEARCH_QUERY = """
query SearchVehicles($input: VehicleSearchInput!) {
  searchVehicles(input: $input) {
    totalCount
    vehicles {
      id vin year make model trim color mileage
      currentBid buyNowPrice saleDate saleStatus
      primaryDamage secondaryDamage
      engine transmission driveType fuelType cylinders bodyStyle
      runsDrives hasKeys titleBrand
      estimatedRetailValue
      images { url isPrimary }
      videoUrl
      location { city state }
      seller { name }
    }
  }
}
"""


def get_adesa_token(client_id: str, client_secret: str) -> str:
    payload = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "audience":      AUDIENCE,
    }).encode()
    req = urllib.request.Request(AUTH0_URL, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    })
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
    data = json.loads(resp.read())
    token = data.get("access_token", "")
    if not token:
        raise ValueError(f"Auth0 failed: {data}")
    return token


def search_adesa(token: str, make="", page=0, size=50):
    variables = {
        "input": {
            "make":   make or "",
            "offset": page * size,
            "limit":  size,
            "sort":   {"field": "saleDate", "order": "ASC"},
        }
    }
    body = json.dumps({"query": SEARCH_QUERY, "variables": variables}).encode()
    req = urllib.request.Request(GRAPHQL_URL, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Origin":        "https://www.openlane.com",
        "Referer":       "https://www.openlane.com/",
    })
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
    data = json.loads(resp.read())
    result = data.get("data", {}).get("searchVehicles", {})
    return result.get("vehicles", []), result.get("totalCount", 0)


def _s(v, n=500):
    return "" if v is None else str(v).strip()[:n]


def normalize_adesa(raw: Dict) -> Dict:
    imgs    = raw.get("images", []) or []
    primary = next((i["url"] for i in imgs if i.get("isPrimary")), "")
    all_imgs = [i["url"] for i in imgs if i.get("url")]
    if not primary and all_imgs:
        primary = all_imgs[0]
    video = _s(raw.get("videoUrl", ""))
    media_json = ""
    if all_imgs or video:
        media_json = json.dumps({
            "images": all_imgs,
            "video":  video,
            "total":  len(all_imgs) + (1 if video else 0),
        })
    loc    = raw.get("location") or {}
    seller = raw.get("seller") or {}
    return {
        "Lot_number":                  _s(raw.get("id", "")),
        "VIN":                         _s(raw.get("vin", "")),
        "Make":                        _s(raw.get("make", "")),
        "Model_Group":                 _s(raw.get("model", "")),
        "Year":                        _s(raw.get("year", "")),
        "Color":                       _s(raw.get("color", "")),
        "Body_Style":                  _s(raw.get("bodyStyle", "")),
        "Damage_Description":          _s(raw.get("primaryDamage", "")),
        "Secondary_Damage":            _s(raw.get("secondaryDamage", "")),
        "Odometer":                    _s(raw.get("mileage", "")),
        "Engine":                      _s(raw.get("engine", "")),
        "Drive":                       _s(raw.get("driveType", "")),
        "Transmission":                _s(raw.get("transmission", "")),
        "Fuel_Type":                   _s(raw.get("fuelType", "")),
        "Cylinders":                   _s(raw.get("cylinders", "")),
        "Runs_Drives":                 "Y" if raw.get("runsDrives") else "N",
        "Has_Keys_Yes_or_No":          "Y" if raw.get("hasKeys") else "N",
        "Sale_Status":                 _s(raw.get("saleStatus", "active")),
        "High_Bid_non_vix_Sealed_Vix": _s(raw.get("currentBid", "")),
        "Est_Retail_Value":            _s(raw.get("estimatedRetailValue") or raw.get("buyNowPrice", "")),
        "Sale_Date_M_D_CY":            _s(raw.get("saleDate", "")),
        "Yard_name":                   _s(seller.get("name", "ADESA")),
        "Location_city":               _s(loc.get("city", "")),
        "Currency_Code":               "USD",
        "Title_Brand":                 _s(raw.get("titleBrand", "")),
        "all_auctions":                "ADESA",
        "Image_Thumbnail":             primary,
        "Image_URL":                   media_json,
    }


def _get_existing(db_path: str) -> Set[str]:
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        rows = conn.execute(
            'SELECT "Lot_number" FROM "schedulars_manualcardata" WHERE "all_auctions"=?',
            ("ADESA",)
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
                 "Damage_Description","Secondary_Damage","Odometer","Engine","Drive",
                 "Transmission","Fuel_Type","Cylinders","Runs_Drives","Has_Keys_Yes_or_No",
                 "Sale_Status","High_Bid_non_vix_Sealed_Vix","Est_Retail_Value",
                 "Sale_Date_M_D_CY","Yard_name","Location_city","Currency_Code",
                 "Title_Brand","Image_Thumbnail","Image_URL","all_auctions")
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                lot, car.get("VIN",""), car.get("Make",""), car.get("Model_Group",""),
                car.get("Year",""), car.get("Color",""), car.get("Body_Style",""),
                car.get("Damage_Description",""), car.get("Secondary_Damage",""),
                car.get("Odometer",""), car.get("Engine",""), car.get("Drive",""),
                car.get("Transmission",""), car.get("Fuel_Type",""), car.get("Cylinders",""),
                car.get("Runs_Drives",""), car.get("Has_Keys_Yes_or_No",""),
                car.get("Sale_Status","active"), car.get("High_Bid_non_vix_Sealed_Vix",""),
                car.get("Est_Retail_Value",""), car.get("Sale_Date_M_D_CY",""),
                car.get("Yard_name","ADESA"), car.get("Location_city",""),
                car.get("Currency_Code","USD"), car.get("Title_Brand",""),
                car.get("Image_Thumbnail",""), car.get("Image_URL",""), "ADESA",
            ))
            saved += 1
        except Exception as e:
            log_fn(f"  [DB] {lot}: {e}")
    conn.commit()
    conn.close()
    return saved


class Command(BaseCommand):
    help = "جلب السيارات من ADESA/OpenLane عبر Auth0 + GraphQL مع صور وفيديو"

    def add_arguments(self, parser):
        parser.add_argument("--make",    type=str, default="")
        parser.add_argument("--pages",   type=int, default=5)
        parser.add_argument("--size",    type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        make  = options["make"]
        pages = options["pages"]
        size  = options["size"]
        dry   = options["dry_run"]

        def log(m): self.stdout.write(m)

        client_id     = getattr(settings, "ADESA_CLIENT_ID", "")
        client_secret = getattr(settings, "ADESA_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            self.stdout.write(self.style.ERROR(
                "\n  ❌ أضف في settings.py:\n"
                "     ADESA_CLIENT_ID = 'your_client_id'\n"
                "     ADESA_CLIENT_SECRET = 'your_client_secret'\n"
                "  (من حساب ADESA dealer -> API settings)\n"
            ))
            return

        db_path = settings.DATABASES["default"]["NAME"]
        t0 = time.time()

        log("=" * 65)
        log("  ADESA REAL SYNC — Auth0 + GraphQL + صور + فيديو")
        log("=" * 65)

        try:
            token = get_adesa_token(client_id, client_secret)
            log("  ✓ Auth0 token OK")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ Auth0: {e}"))
            return

        log(f"  الشركة: {make or 'الكل'} | صفحات: {pages}")
        log("-" * 65)

        existing = _get_existing(db_path)
        log(f"  موجود في DB: {len(existing):,}")

        all_cars, total_count, total_saved = [], 0, 0

        for p in range(pages):
            try:
                vehicles, total = search_adesa(token, make, p, size)
                if p == 0:
                    total_count = total
                    log(f"  إجمالي ADESA: {total_count:,}")

                new_v = [v for v in vehicles if _s(v.get("id","")) not in existing]
                log(f"  صفحة {p+1}/{pages}: {len(vehicles)} | جديد: {len(new_v)}")

                if not vehicles:
                    break

                for raw in new_v:
                    car = normalize_adesa(raw)
                    if car.get("Lot_number"):
                        all_cars.append(car)
                        existing.add(car["Lot_number"])

                if len(all_cars) >= 200 and not dry:
                    s = _save_batch(all_cars, db_path, log)
                    total_saved += s
                    log(f"  ✓ دفعة: {s}")
                    all_cars = []

                time.sleep(0.5)

            except Exception as e:
                log(f"  ❌ صفحة {p}: {e}")
                if "401" in str(e) or "403" in str(e):
                    try:
                        token = get_adesa_token(client_id, client_secret)
                        log("  ✓ Token جُدِّد")
                    except Exception:
                        break
                time.sleep(3)

        if all_cars and not dry:
            total_saved += _save_batch(all_cars, db_path, log)

        elapsed = time.time() - t0
        log(f"\n{'='*65}")
        log(f"  إجمالي: {total_count:,} | محفوظ: {total_saved} | {elapsed:.0f}s")
        log("=" * 65)

        if total_saved > 0:
            self.stdout.write(self.style.SUCCESS(f"\n  ✓ تم استيراد {total_saved} سيارة من ADESA!"))

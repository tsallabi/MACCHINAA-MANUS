"""
acv_playwright_sync.py - ACV Auctions Scraper via Playwright + Token Cache
==========================================================================
ACV is protected by Cloudflare - only works from a real browser on your PC.

Strategy:
  1. First run: Playwright logs in, captures the JWT token, saves it to disk
  2. Next runs: uses the cached token directly (no browser needed, fast)
  3. If token expires (401/403): automatically re-launches Playwright to refresh

Requirements (run once on your PC):
    pip install playwright
    playwright install chromium

Settings in settings.py:
    ACV_EMAIL    = 'Macchina525@gmail.com'
    ACV_PASSWORD = 'z43:-(!y81DZ?tp'

Usage:
    python manage.py acv_playwright_sync
    python manage.py acv_playwright_sync --make Toyota --pages 10
    python manage.py acv_playwright_sync --fetch-images
    python manage.py acv_playwright_sync --refresh-token
    python manage.py acv_playwright_sync --dry-run
"""
from __future__ import annotations
import json, logging, sqlite3, ssl, time, urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("acv_playwright_sync")

ACV_SEARCH_URL = "https://api.acvauctions.com/v2/search/vehicles"
ACV_IMAGES_URL = "https://api.acvauctions.com/v1/vehicles/{vid}/images"
TOKEN_CACHE    = Path(settings.BASE_DIR) / ".acv_token_cache.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Token Management
# ---------------------------------------------------------------------------

def load_cached_token() -> Optional[str]:
    """Load saved token if still valid (5 min buffer before expiry)."""
    try:
        if TOKEN_CACHE.exists():
            data = json.loads(TOKEN_CACHE.read_text())
            if data.get("expires_at", 0) > time.time() + 300:
                return data.get("token")
    except Exception:
        pass
    return None


def save_token(token: str, expires_in: int = 3600) -> None:
    """Persist token with expiry timestamp."""
    TOKEN_CACHE.write_text(json.dumps({
        "token":      token,
        "expires_at": time.time() + expires_in,
    }))


def get_token_via_playwright(email: str, password: str) -> str:
    """
    Launch headless Chromium, log in to ACV, capture the Bearer token.
    Works only from your local PC - Cloudflare blocks cloud IPs.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed.\n"
            "Run: pip install playwright && playwright install chromium"
        )

    captured: Dict[str, str] = {"token": ""}

    def on_response(response):
        auth = response.headers.get("authorization", "")
        if auth.startswith("Bearer ") and "acvauctions" in response.url:
            captured["token"] = auth.replace("Bearer ", "")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()
        page.on("response", on_response)

        page.goto("https://app.acvauctions.com/login",
                  wait_until="networkidle", timeout=60000)
        page.fill('input[type="email"]',    email)
        page.fill('input[type="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_url("**/marketplace**", timeout=30000)
        page.wait_for_timeout(3000)

        # Fallback: try localStorage for JWT
        t = page.evaluate("""() => {
            for (let k of Object.keys(localStorage)) {
                let v = localStorage.getItem(k);
                if (v && v.startsWith('eyJ')) return v;
            }
            return '';
        }""")
        if t:
            captured["token"] = t

        browser.close()

    token = captured["token"]
    if not token:
        raise RuntimeError(
            "Could not extract ACV token. "
            "Check credentials or try --refresh-token."
        )
    save_token(token, expires_in=3600)
    logger.info("ACV token captured and saved.")
    return token


def get_acv_token(email: str, password: str, force: bool = False) -> str:
    """Return a valid token (cached or freshly obtained)."""
    if not force:
        cached = load_cached_token()
        if cached:
            return cached
    return get_token_via_playwright(email, password)


# ---------------------------------------------------------------------------
# API Calls
# ---------------------------------------------------------------------------

def search_acv(token: str, make: str = "", page: int = 0, size: int = 50):
    """Fetch vehicle list from ACV search API."""
    payload = {
        "filters":    {"make": make} if make else {},
        "pagination": {"page": page, "size": size},
        "sort":       {"field": "endTime", "order": "asc"},
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(ACV_SEARCH_URL, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
        "User-Agent":    "Mozilla/5.0 Chrome/120.0.0.0",
        "Origin":        "https://app.acvauctions.com",
        "Referer":       "https://app.acvauctions.com/marketplace",
    })
    resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=30)
    data = json.loads(resp.read())
    items = (data.get("data", {}).get("vehicles", [])
             or data.get("vehicles", []))
    total = (data.get("data", {}).get("totalCount", 0)
             or data.get("totalCount", 0))
    return items, total


def fetch_acv_images(token: str, vid: str) -> Dict:
    """Fetch all images + video URL for a vehicle."""
    try:
        req = urllib.request.Request(
            ACV_IMAGES_URL.format(vid=vid),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept":        "application/json",
                "User-Agent":    "Mozilla/5.0 Chrome/120.0.0.0",
            }
        )
        resp = urllib.request.urlopen(req, context=SSL_CTX, timeout=15)
        data = json.loads(resp.read())
        imgs  = [i.get("url", "") for i in data.get("images", []) if i.get("url")]
        video = data.get("videoUrl", "")
        return {
            "images": imgs,
            "video":  video,
            "total":  len(imgs) + (1 if video else 0),
        }
    except Exception as e:
        logger.debug("ACV images %s: %s", vid, e)
        return {"images": [], "video": "", "total": 0}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _s(v, n: int = 500) -> str:
    return "" if v is None else str(v).strip()[:n]


def normalize_acv(raw: Dict, media: Optional[Dict] = None) -> Dict:
    """Map ACV API response to ManualCarData schema."""
    vid_id = _s(raw.get("id", ""))
    thumb  = _s(raw.get("thumbnailUrl") or raw.get("imageUrl", ""))

    media_json = ""
    if media and media.get("total", 0) > 0:
        media_json = json.dumps(media)
    elif thumb:
        media_json = json.dumps({"images": [thumb], "total": 1})

    return {
        "Lot_number":                  vid_id,
        "VIN":                         _s(raw.get("vin", "")),
        "Make":                        _s(raw.get("make", "")),
        "Model_Group":                 _s(raw.get("model", "")),
        "Year":                        _s(raw.get("year", "")),
        "Color":                       _s(raw.get("exteriorColor") or raw.get("color", "")),
        "Body_Style":                  _s(raw.get("bodyStyle", "")),
        "Damage_Description":          _s(raw.get("conditionGrade") or raw.get("damage", "")),
        "Odometer":                    _s(raw.get("mileage", "")),
        "Engine":                      _s(raw.get("engine", "")),
        "Drive":                       _s(raw.get("driveType", "")),
        "Transmission":                _s(raw.get("transmission", "")),
        "Fuel_Type":                   _s(raw.get("fuelType", "")),
        "Cylinders":                   _s(raw.get("cylinders", "")),
        "Runs_Drives":                 "Y" if raw.get("runsDrives") else "N",
        "Has_Keys_Yes_or_No":          "Y" if raw.get("hasKeys") else "N",
        "Sale_Status":                 _s(raw.get("status", "active")),
        "High_Bid_non_vix_Sealed_Vix": _s(raw.get("currentBid", "")),
        "Est_Retail_Value":            _s(raw.get("mmrValue") or raw.get("retailValue", "")),
        "Sale_Date_M_D_CY":            _s(raw.get("endTime") or raw.get("saleDate", "")),
        "Yard_name":                   _s(raw.get("sellerName") or raw.get("location", "ACV")),
        "Location_city":               _s(raw.get("city", "")),
        "Currency_Code":               "USD",
        "Title_Brand":                 _s(raw.get("titleBrand", "")),
        "all_auctions":                "ACV",
        "Image_Thumbnail":             thumb,
        "Image_URL":                   media_json,
    }


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _get_existing(db_path: str) -> Set[str]:
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        rows = conn.execute(
            'SELECT "Lot_number" FROM "schedulars_manualcardata" WHERE "all_auctions"=?',
            ("ACV",)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning("DB read error: %s", e)
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
                 "Damage_Description","Odometer","Engine","Drive","Transmission",
                 "Fuel_Type","Cylinders","Runs_Drives","Has_Keys_Yes_or_No","Sale_Status",
                 "High_Bid_non_vix_Sealed_Vix","Est_Retail_Value","Sale_Date_M_D_CY",
                 "Yard_name","Location_city","Currency_Code","Title_Brand",
                 "Image_Thumbnail","Image_URL","all_auctions")
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                lot, car.get("VIN",""), car.get("Make",""), car.get("Model_Group",""),
                car.get("Year",""), car.get("Color",""), car.get("Body_Style",""),
                car.get("Damage_Description",""), car.get("Odometer",""),
                car.get("Engine",""), car.get("Drive",""), car.get("Transmission",""),
                car.get("Fuel_Type",""), car.get("Cylinders",""),
                car.get("Runs_Drives",""), car.get("Has_Keys_Yes_or_No",""),
                car.get("Sale_Status","active"),
                car.get("High_Bid_non_vix_Sealed_Vix",""),
                car.get("Est_Retail_Value",""), car.get("Sale_Date_M_D_CY",""),
                car.get("Yard_name","ACV"), car.get("Location_city",""),
                car.get("Currency_Code","USD"), car.get("Title_Brand",""),
                car.get("Image_Thumbnail",""), car.get("Image_URL",""), "ACV",
            ))
            saved += 1
        except Exception as e:
            log_fn(f"  [DB] {lot}: {e}")
    conn.commit()
    conn.close()
    return saved


# ---------------------------------------------------------------------------
# Management Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Fetch vehicles from ACV Auctions via Playwright + Token Cache"

    def add_arguments(self, parser):
        parser.add_argument("--make",          type=str, default="",
                            help="Filter by make (e.g. Toyota)")
        parser.add_argument("--pages",         type=int, default=5,
                            help="Number of pages to fetch (50 cars each)")
        parser.add_argument("--size",          type=int, default=50,
                            help="Results per page")
        parser.add_argument("--fetch-images",  action="store_true",
                            help="Fetch full image gallery for each car")
        parser.add_argument("--refresh-token", action="store_true",
                            help="Force new Playwright login even if token is valid")
        parser.add_argument("--dry-run",       action="store_true",
                            help="Fetch but do not save to DB")

    def handle(self, *args, **options):
        make  = options["make"]
        pages = options["pages"]
        size  = options["size"]
        fetch = options["fetch_images"]
        force = options["refresh_token"]
        dry   = options["dry_run"]

        def log(m): self.stdout.write(m)

        email    = getattr(settings, "ACV_EMAIL",    "")
        password = getattr(settings, "ACV_PASSWORD", "")

        if not email or not password:
            self.stdout.write(self.style.ERROR(
                "\n  ERROR: Add to settings.py:\n"
                "     ACV_EMAIL    = 'your@email.com'\n"
                "     ACV_PASSWORD = 'your_password'\n"
            ))
            return

        db_path = settings.DATABASES["default"]["NAME"]
        t0 = time.time()

        log("=" * 65)
        log("  ACV AUCTIONS SYNC - Playwright + Token Cache")
        log("=" * 65)

        # Get token
        try:
            token = get_acv_token(email, password, force)
            log("  Token: OK (cached or freshly obtained)")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Login failed: {e}"))
            return

        log(f"  Make: {make or 'ALL'} | Pages: {pages} | "
            f"Images: {'YES' if fetch else 'NO'} | "
            f"Dry-run: {'YES' if dry else 'NO'}")
        log("-" * 65)

        existing = _get_existing(db_path)
        log(f"  Already in DB: {len(existing):,} ACV vehicles")

        all_cars: List[Dict] = []
        total_count = 0
        total_saved = 0

        for p in range(pages):
            try:
                items, total = search_acv(token, make, p, size)
                if p == 0:
                    total_count = total
                    log(f"  ACV total available: {total_count:,}")

                new_items = [i for i in items
                             if _s(i.get("id", "")) not in existing]
                log(f"  Page {p+1}/{pages}: {len(items)} fetched | "
                    f"{len(new_items)} new")

                if not items:
                    log("  No more results.")
                    break

                for raw in new_items:
                    vid_id = _s(raw.get("id", ""))
                    if not vid_id:
                        continue
                    media = fetch_acv_images(token, vid_id) if fetch else None
                    if fetch:
                        time.sleep(0.3)
                    car = normalize_acv(raw, media)
                    all_cars.append(car)
                    existing.add(vid_id)

                # Flush every 200 cars
                if len(all_cars) >= 200 and not dry:
                    s = _save_batch(all_cars, db_path, log)
                    total_saved += s
                    log(f"  Flushed batch: {s} saved")
                    all_cars = []

                time.sleep(0.5)

            except Exception as e:
                log(f"  ERROR on page {p}: {e}")
                # Auto-refresh token on auth errors
                if "401" in str(e) or "403" in str(e):
                    try:
                        token = get_acv_token(email, password, force=True)
                        log("  Token auto-refreshed, retrying...")
                    except Exception:
                        log("  Token refresh failed. Stopping.")
                        break
                time.sleep(3)

        # Final flush
        if all_cars and not dry:
            total_saved += _save_batch(all_cars, db_path, log)

        elapsed = time.time() - t0
        log(f"\n{'='*65}")
        log(f"  DONE | Total available: {total_count:,} | "
            f"Saved: {total_saved} | Time: {elapsed:.0f}s")
        log("=" * 65)

        if dry:
            log(f"  [DRY-RUN] Would have saved {len(all_cars)} cars.")
        elif total_saved > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\n  Successfully imported {total_saved} cars from ACV!")
            )

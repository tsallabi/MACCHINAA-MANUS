"""
ACV Auctions Scraper — Playwright + Token Caching
==================================================
يسجّل الدخول مرة واحدة عبر متصفح حقيقي، يحفظ الـ JWT token،
ثم يستخدمه مباشرة في كل الطلبات التالية بدون متصفح.

الاستخدام:
    python manage.py acv_playwright_sync
    python manage.py acv_playwright_sync --make Toyota --max-pages 10
    python manage.py acv_playwright_sync --refresh-token   # تجديد الـ token
    python manage.py acv_playwright_sync --dry-run

المتطلبات:
    pip install playwright && playwright install chromium
"""

import json
import time
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# ── مسار حفظ الـ token ──────────────────────────────────────────────────────
TOKEN_CACHE_PATH = Path(__file__).parent / ".acv_token_cache.json"
TOKEN_TTL_HOURS  = 20   # ACV tokens تنتهي بعد ~24 ساعة


# ══════════════════════════════════════════════════════════════════════════════
#  Token Manager
# ══════════════════════════════════════════════════════════════════════════════

class ACVTokenManager:
    """يدير دورة حياة الـ JWT token لـ ACV."""

    def __init__(self, email: str, password: str):
        self.email    = email
        self.password = password

    # ── قراءة من الكاش ──────────────────────────────────────────────────────
    def _load_cached(self) -> dict | None:
        if not TOKEN_CACHE_PATH.exists():
            return None
        try:
            data = json.loads(TOKEN_CACHE_PATH.read_text())
            expires = datetime.fromisoformat(data["expires_at"])
            if datetime.utcnow() < expires:
                logger.info("✓ ACV token من الكاش (صالح حتى %s)", expires.strftime("%H:%M"))
                return data
            logger.info("⚠ ACV token منتهي الصلاحية — سيتم التجديد")
        except Exception as e:
            logger.warning("خطأ في قراءة الكاش: %s", e)
        return None

    # ── حفظ في الكاش ────────────────────────────────────────────────────────
    def _save_cache(self, token: str, dealer_id: str = ""):
        expires = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
        data = {
            "token":      token,
            "dealer_id":  dealer_id,
            "expires_at": expires.isoformat(),
            "saved_at":   datetime.utcnow().isoformat(),
        }
        TOKEN_CACHE_PATH.write_text(json.dumps(data, indent=2))
        logger.info("✓ Token محفوظ في %s", TOKEN_CACHE_PATH)

    # ── تسجيل الدخول عبر Playwright ─────────────────────────────────────────
    def _login_via_playwright(self) -> dict:
        """يفتح متصفح Chromium، يسجّل الدخول، يلتقط الـ JWT."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            raise RuntimeError(
                "Playwright غير مثبّت.\n"
                "شغّل: pip install playwright && playwright install chromium"
            )

        captured = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            # ── اعتراض الـ JWT من الطلبات الصادرة ───────────────────────────
            def intercept_request(request):
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and len(auth) > 50:
                    token = auth.replace("Bearer ", "").strip()
                    if token not in captured.get("tokens", []):
                        captured.setdefault("tokens", []).append(token)
                        logger.debug("🔑 Token مُلتقط من: %s", request.url[:80])

            page.on("request", intercept_request)

            # ── فتح صفحة الدخول ─────────────────────────────────────────────
            logger.info("🌐 فتح صفحة تسجيل الدخول...")
            page.goto("https://app.acvauctions.com/login", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # ── إدخال بيانات الدخول ──────────────────────────────────────────
            logger.info("📧 إدخال البريد الإلكتروني...")
            email_sel = 'input[type="email"], input[name="email"], input[placeholder*="email" i]'
            page.wait_for_selector(email_sel, timeout=15000)
            page.fill(email_sel, self.email)

            pass_sel = 'input[type="password"]'
            page.wait_for_selector(pass_sel, timeout=10000)
            page.fill(pass_sel, self.password)

            # ── الضغط على زر الدخول ──────────────────────────────────────────
            logger.info("🔐 تسجيل الدخول...")
            btn_sel = 'button[type="submit"], button:has-text("Sign In"), button:has-text("Log In")'
            page.click(btn_sel)

            # ── انتظار التحميل ────────────────────────────────────────────────
            try:
                page.wait_for_url("**/dashboard**", timeout=20000)
            except PWTimeout:
                # بعض الحسابات تذهب لصفحة مختلفة
                page.wait_for_load_state("networkidle", timeout=15000)

            time.sleep(3)  # انتظار إضافي لالتقاط الـ tokens

            # ── استخراج dealer_id من localStorage ────────────────────────────
            dealer_id = ""
            try:
                storage = page.evaluate("() => JSON.stringify(window.localStorage)")
                ls = json.loads(storage)
                for key, val in ls.items():
                    if "dealer" in key.lower() or "user" in key.lower():
                        try:
                            obj = json.loads(val)
                            dealer_id = str(obj.get("dealerId") or obj.get("dealer_id") or "")
                            if dealer_id:
                                break
                        except Exception:
                            pass
            except Exception:
                pass

            browser.close()

        if not captured.get("tokens"):
            raise RuntimeError("❌ فشل التقاط الـ JWT token — تحقق من بيانات الدخول")

        # أطول token هو الـ JWT الحقيقي
        token = max(captured["tokens"], key=len)
        logger.info("✅ تسجيل الدخول ناجح | dealer_id=%s", dealer_id or "غير محدد")
        return {"token": token, "dealer_id": dealer_id}

    # ── الواجهة العامة ───────────────────────────────────────────────────────
    def get_token(self, force_refresh: bool = False) -> tuple[str, str]:
        """يُعيد (token, dealer_id) — من الكاش أو بتسجيل دخول جديد."""
        if not force_refresh:
            cached = self._load_cached()
            if cached:
                return cached["token"], cached.get("dealer_id", "")

        result = self._login_via_playwright()
        self._save_cache(result["token"], result["dealer_id"])
        return result["token"], result["dealer_id"]


# ══════════════════════════════════════════════════════════════════════════════
#  ACV API Client
# ══════════════════════════════════════════════════════════════════════════════

class ACVClient:
    """يتواصل مع ACV gateways باستخدام الـ JWT token."""

    GATEWAYS = {
        "auction_house":  "https://auction-house.gateway.acvauctions.com",
        "auction_launch": "https://auction-launch.gateway.acvauctions.com",
        "inventory":      "https://inventory-service.gateway.acvauctions.com",
        "apes":           "https://apes.gateway.acvauctions.com",
    }

    def __init__(self, token: str, dealer_id: str = ""):
        self.token     = token
        self.dealer_id = dealer_id
        self.session   = requests.Session()
        self.session.headers.update({
            "Authorization":  f"Bearer {token}",
            "Content-Type":   "application/json",
            "Accept":         "application/json",
            "User-Agent":     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin":         "https://app.acvauctions.com",
            "Referer":        "https://app.acvauctions.com/",
            "x-acv-dealer-id": dealer_id,
        })

    def _get(self, gateway: str, path: str, params: dict = None) -> dict | None:
        url = self.GATEWAYS[gateway].rstrip("/") + "/" + path.lstrip("/")
        try:
            r = self.session.get(url, params=params, timeout=20)
            if r.status_code == 401:
                logger.warning("⚠ Token منتهي — يجب التجديد")
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            logger.error("خطأ في %s: %s", url, e)
            return None

    def search_vehicles(self, page: int = 1, per_page: int = 50,
                        make: str = "", model: str = "") -> dict | None:
        """البحث عن مركبات في المزادات الحية."""
        params = {
            "page":     page,
            "per_page": per_page,
            "sort":     "end_time",
            "order":    "asc",
        }
        if make:
            params["make"] = make
        if model:
            params["model"] = model

        # محاولة auction-house أولاً
        result = self._get("auction_house", "/api/v1/auctions/search", params)
        if result:
            return result

        # fallback: auction-launch
        return self._get("auction_launch", "/api/v1/vehicles", params)

    def get_vehicle_detail(self, auction_id: str) -> dict | None:
        """تفاصيل مركبة واحدة."""
        return self._get("auction_house", f"/api/v1/auctions/{auction_id}")

    def get_active_lanes(self) -> list:
        """قائمة الـ lanes النشطة."""
        result = self._get("apes", "/api/v1/lanes/active")
        if result:
            return result.get("lanes") or result.get("data") or []
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  Data Normalizer
# ══════════════════════════════════════════════════════════════════════════════

def normalize_acv_vehicle(raw: dict) -> dict:
    """
    يحوّل بيانات ACV الخام إلى الشكل المتوافق مع ManualCarData.
    يتبع نفس أسلوب iaai_full_sync تماماً.
    """
    vehicle = raw.get("vehicle") or raw
    auction  = raw.get("auction")  or raw

    # ── السعر ────────────────────────────────────────────────────────────────
    current_bid   = float(auction.get("current_bid")   or vehicle.get("current_bid")   or 0)
    buy_now_price = float(auction.get("buy_now_price") or vehicle.get("buy_now_price") or 0)
    price = current_bid or buy_now_price or 0

    # ── الصور ────────────────────────────────────────────────────────────────
    images = vehicle.get("images") or []
    if isinstance(images, list):
        image_urls = [img.get("url") or img.get("src") or img for img in images if img]
        image_urls = [u for u in image_urls if isinstance(u, str) and u.startswith("http")]
    else:
        image_urls = []

    main_image = image_urls[0] if image_urls else ""

    # ── التاريخ ───────────────────────────────────────────────────────────────
    end_time = auction.get("end_time") or auction.get("auction_end") or ""
    if end_time:
        try:
            end_time = datetime.fromisoformat(str(end_time).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            end_time = str(end_time)[:16]

    # ── الحقول الرئيسية ───────────────────────────────────────────────────────
    return {
        "lot_number":       str(auction.get("id") or auction.get("auction_id") or raw.get("id") or ""),
        "VIN":              vehicle.get("vin") or vehicle.get("VIN") or "",
        "Year":             str(vehicle.get("year") or ""),
        "Make":             vehicle.get("make") or vehicle.get("manufacturer") or "",
        "Model":            vehicle.get("model") or "",
        "Series":           vehicle.get("trim") or vehicle.get("series") or "",
        "Body_Style":       vehicle.get("body_style") or vehicle.get("body_type") or "",
        "Color":            vehicle.get("color") or vehicle.get("exterior_color") or "",
        "Odometer":         str(vehicle.get("odometer") or vehicle.get("mileage") or ""),
        "Odometer_Brand":   "Actual",
        "Engine":           vehicle.get("engine") or vehicle.get("engine_description") or "",
        "Transmission":     vehicle.get("transmission") or "",
        "Drive":            vehicle.get("drive_type") or vehicle.get("drivetrain") or "",
        "Fuel":             vehicle.get("fuel_type") or "",
        "Keys":             "Yes" if vehicle.get("has_keys") else "No",
        "Primary_Damage":   vehicle.get("primary_damage") or vehicle.get("damage") or "",
        "Secondary_Damage": vehicle.get("secondary_damage") or "",
        "Condition_Grade":  vehicle.get("condition_grade") or vehicle.get("grade") or "",
        "Est_Retail_Value": str(vehicle.get("mmr") or vehicle.get("retail_value") or ""),
        "Cur_Bid":          str(price),
        "Buy_Now_Price":    str(buy_now_price),
        "Currency_Code":    "USD",
        "Auction_Date":     end_time,
        "Yard_name":        vehicle.get("location") or vehicle.get("yard_name") or "ACV Auctions",
        "State":            vehicle.get("state") or vehicle.get("location_state") or "",
        "Zip_Code":         vehicle.get("zip") or vehicle.get("postal_code") or "",
        "all_auctions":     "ACV",
        "Img_url":          main_image,
        "all_images":       json.dumps(image_urls[:20]),
        "lot_url":          f"https://app.acvauctions.com/auction/{auction.get('id') or raw.get('id') or ''}",
        "source_raw":       json.dumps(raw, ensure_ascii=False)[:2000],
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Django Management Command
# ══════════════════════════════════════════════════════════════════════════════

try:
    from django.core.management.base import BaseCommand
    from django.conf import settings
    from django.db import connection

    class Command(BaseCommand):
        help = "جلب سيارات ACV Auctions عبر Playwright + JWT token caching"

        def add_arguments(self, parser):
            parser.add_argument("--make",          type=str, default="",    help="فلتر حسب الماركة")
            parser.add_argument("--model",         type=str, default="",    help="فلتر حسب الموديل")
            parser.add_argument("--max-pages",     type=int, default=20,    help="أقصى عدد صفحات")
            parser.add_argument("--per-page",      type=int, default=50,    help="سيارات لكل صفحة")
            parser.add_argument("--delay",         type=float, default=1.5, help="تأخير بين الصفحات")
            parser.add_argument("--refresh-token", action="store_true",     help="تجديد الـ token")
            parser.add_argument("--dry-run",       action="store_true",     help="اختبار بدون حفظ")
            parser.add_argument("--resume",        action="store_true",     help="تخطي الـ VINs الموجودة")

        def handle(self, *args, **options):
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

            email    = getattr(settings, "ACV_USERNAME", "") or os.getenv("ACV_USERNAME", "")
            password = getattr(settings, "ACV_PASSWORD", "") or os.getenv("ACV_PASSWORD", "")

            if not email or not password:
                self.stderr.write("❌ ACV_USERNAME و ACV_PASSWORD غير محددَين في settings.py أو .env")
                return

            # ── الحصول على الـ token ──────────────────────────────────────────
            self.stdout.write("🔑 الحصول على ACV token...")
            manager = ACVTokenManager(email, password)
            try:
                token, dealer_id = manager.get_token(force_refresh=options["refresh_token"])
            except Exception as e:
                self.stderr.write(f"❌ فشل تسجيل الدخول: {e}")
                return

            client = ACVClient(token, dealer_id)

            # ── جلب الـ VINs الموجودة (للـ resume) ───────────────────────────
            existing_vins = set()
            if options["resume"]:
                with connection.cursor() as cur:
                    cur.execute("SELECT VIN FROM schedulars_manualcardata WHERE all_auctions='ACV' AND VIN != ''")
                    existing_vins = {row[0] for row in cur.fetchall()}
                self.stdout.write(f"ℹ {len(existing_vins)} VIN موجود — سيتم تخطيها")

            # ── جلب الصفحات ──────────────────────────────────────────────────
            total_saved = 0
            total_skipped = 0
            total_errors = 0

            for page_num in range(1, options["max_pages"] + 1):
                self.stdout.write(f"📄 صفحة {page_num}/{options['max_pages']}...")

                data = client.search_vehicles(
                    page=page_num,
                    per_page=options["per_page"],
                    make=options["make"],
                    model=options["model"],
                )

                if not data:
                    self.stdout.write("⚠ لا بيانات — Token منتهي أو خطأ في الشبكة")
                    # محاولة تجديد الـ token تلقائياً
                    try:
                        token, dealer_id = manager.get_token(force_refresh=True)
                        client = ACVClient(token, dealer_id)
                        self.stdout.write("🔄 تم تجديد الـ token — إعادة المحاولة...")
                        data = client.search_vehicles(page=page_num, per_page=options["per_page"])
                    except Exception:
                        break

                if not data:
                    break

                # استخراج قائمة السيارات من الـ response
                vehicles = (
                    data.get("auctions") or
                    data.get("vehicles") or
                    data.get("data") or
                    data.get("results") or
                    (data if isinstance(data, list) else [])
                )

                if not vehicles:
                    self.stdout.write(f"✓ لا مزيد من النتائج في الصفحة {page_num}")
                    break

                for raw in vehicles:
                    try:
                        normalized = normalize_acv_vehicle(raw)
                        vin = normalized.get("VIN", "")

                        if options["resume"] and vin and vin in existing_vins:
                            total_skipped += 1
                            continue

                        if options["dry_run"]:
                            self.stdout.write(
                                f"  [DRY] {normalized['Year']} {normalized['Make']} "
                                f"{normalized['Model']} — ${normalized['Cur_Bid']}"
                            )
                            total_saved += 1
                            continue

                        self._save_to_db(normalized)
                        total_saved += 1

                        if vin:
                            existing_vins.add(vin)

                    except Exception as e:
                        logger.error("خطأ في معالجة سيارة: %s", e)
                        total_errors += 1

                self.stdout.write(
                    f"  ✓ الصفحة {page_num}: {len(vehicles)} سيارة | "
                    f"محفوظ={total_saved} تخطي={total_skipped} خطأ={total_errors}"
                )

                if len(vehicles) < options["per_page"]:
                    break  # آخر صفحة

                time.sleep(options["delay"])

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✅ اكتمل ACV Sync | "
                    f"محفوظ={total_saved} | تخطي={total_skipped} | أخطاء={total_errors}"
                )
            )

        def _save_to_db(self, car: dict):
            """حفظ سيارة واحدة في ManualCarData بنفس أسلوب iaai_full_sync."""
            with connection.cursor() as cur:
                cur.execute("""
                    SELECT id FROM schedulars_manualcardata
                    WHERE lot_number = %s AND all_auctions = 'ACV'
                    LIMIT 1
                """, [car["lot_number"]])
                row = cur.fetchone()

                if row:
                    cur.execute("""
                        UPDATE schedulars_manualcardata SET
                            VIN=%s, Year=%s, Make=%s, Model=%s, Series=%s,
                            Body_Style=%s, Color=%s, Odometer=%s, Engine=%s,
                            Transmission=%s, Drive=%s, Fuel=%s, Keys=%s,
                            Primary_Damage=%s, Secondary_Damage=%s,
                            Condition_Grade=%s, Est_Retail_Value=%s,
                            Cur_Bid=%s, Buy_Now_Price=%s, Currency_Code=%s,
                            Auction_Date=%s, Yard_name=%s, State=%s,
                            Zip_Code=%s, Img_url=%s, all_images=%s,
                            lot_url=%s, updated_at=CURRENT_TIMESTAMP
                        WHERE id=%s
                    """, [
                        car["VIN"], car["Year"], car["Make"], car["Model"],
                        car["Series"], car["Body_Style"], car["Color"],
                        car["Odometer"], car["Engine"], car["Transmission"],
                        car["Drive"], car["Fuel"], car["Keys"],
                        car["Primary_Damage"], car["Secondary_Damage"],
                        car["Condition_Grade"], car["Est_Retail_Value"],
                        car["Cur_Bid"], car["Buy_Now_Price"], car["Currency_Code"],
                        car["Auction_Date"], car["Yard_name"], car["State"],
                        car["Zip_Code"], car["Img_url"], car["all_images"],
                        car["lot_url"], row[0],
                    ])
                else:
                    cur.execute("""
                        INSERT INTO schedulars_manualcardata (
                            lot_number, VIN, Year, Make, Model, Series,
                            Body_Style, Color, Odometer, Odometer_Brand,
                            Engine, Transmission, Drive, Fuel, Keys,
                            Primary_Damage, Secondary_Damage, Condition_Grade,
                            Est_Retail_Value, Cur_Bid, Buy_Now_Price,
                            Currency_Code, Auction_Date, Yard_name, State,
                            Zip_Code, all_auctions, Img_url, all_images,
                            lot_url, created_at, updated_at
                        ) VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                    """, [
                        car["lot_number"], car["VIN"], car["Year"],
                        car["Make"], car["Model"], car["Series"],
                        car["Body_Style"], car["Color"], car["Odometer"],
                        car["Odometer_Brand"], car["Engine"], car["Transmission"],
                        car["Drive"], car["Fuel"], car["Keys"],
                        car["Primary_Damage"], car["Secondary_Damage"],
                        car["Condition_Grade"], car["Est_Retail_Value"],
                        car["Cur_Bid"], car["Buy_Now_Price"], car["Currency_Code"],
                        car["Auction_Date"], car["Yard_name"], car["State"],
                        car["Zip_Code"], car["all_auctions"], car["Img_url"],
                        car["all_images"], car["lot_url"],
                    ])

except ImportError:
    # يعمل خارج Django أيضاً للاختبار
    pass


# ── اختبار مستقل ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    email    = os.getenv("ACV_USERNAME", "Macchina525@gmail.com")
    password = os.getenv("ACV_PASSWORD", "")

    if not password:
        print("❌ أضف ACV_PASSWORD في متغيرات البيئة")
        sys.exit(1)

    manager = ACVTokenManager(email, password)
    token, dealer_id = manager.get_token()
    print(f"✅ Token: {token[:40]}...")
    print(f"   Dealer ID: {dealer_id}")

    client = ACVClient(token, dealer_id)
    print("\n🔍 جلب أول صفحة من المزادات...")
    data = client.search_vehicles(page=1, per_page=10)
    if data:
        vehicles = data.get("auctions") or data.get("vehicles") or data.get("data") or []
        print(f"✅ {len(vehicles)} سيارة في الصفحة الأولى")
        for v in vehicles[:3]:
            n = normalize_acv_vehicle(v)
            print(f"  • {n['Year']} {n['Make']} {n['Model']} — ${n['Cur_Bid']}")
    else:
        print("⚠ لا بيانات — تحقق من الـ token")

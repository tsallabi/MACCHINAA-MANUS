"""
seed_real.py — إضافة بيانات حقيقية من Encar + بيانات تجريبية لـ Copart/IAAI
"""
import os, sys, django, json, requests

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from core.models import AuctionVehicle
from django.db.models import Count

print("🇰🇷 جلب سيارات حقيقية من Encar Korea API...")

url = "https://api.encar.com/search/car/list/general"
params = {
    "count": True,
    "q": "(And.Hidden.N._.SellType.일반._.CarType.Y.)",
    "sr": "|ModifiedDate|0|60",
    "fields": "Id,Year,Manufacturer,ModelGroup,BadgeName,Mileage,Price,Photo,Condition,FuelType,Transmission,Color"
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.encar.com/",
}

try:
    r = requests.get(url, params=params, headers=headers, timeout=15)
    data = r.json()
    cars = data.get("SearchResults", [])
    print(f"✓ جُلب {len(cars)} سيارة من Encar")

    saved = 0
    for car in cars[:50]:
        photo = car.get("Photo", "")
        img_url = f"https://ci.encar.com/carpicture{photo}/001.jpg" if photo else ""
        price_krw = float(car.get("Price", 0)) * 10000
        price_usd = round(price_krw / 1350, 0)

        obj, created = AuctionVehicle.objects.update_or_create(
            lot_number=str(car.get("Id", "")),
            sync_source="ENCAR",
            defaults={
                "year": str(car.get("Year", ""))[:4],
                "make": car.get("Manufacturer", ""),
                "model": car.get("ModelGroup", ""),
                "trim": car.get("BadgeName", ""),
                "odometer": int(car.get("Mileage", 0) or 0),
                "odometer_unit": "km",
                "fuel_type": car.get("FuelType", ""),
                "transmission": car.get("Transmission", ""),
                "color": car.get("Color", ""),
                "current_bid": price_usd,
                "normalized_price_usd": price_usd,
                "currency": "KRW",
                "primary_image": img_url,
                "source_url": f"https://www.encar.com/dc/dc_cardetailview.do?carid={car.get('Id','')}",
                "source_country": "KR",
                "source_auction": "Encar Korea",
                "location_country": "KR",
            }
        )
        saved += 1

    print(f"✅ حُفظ {saved} سيارة كورية")

except Exception as e:
    print(f"❌ خطأ Encar: {e}")

# ── Copart ──────────────────────────────────────────────────────────────────
print("\n🇺🇸 إضافة سيارات Copart...")
copart_cars = [
    {"lot": "C001", "year": "2020", "make": "Toyota", "model": "Camry", "trim": "SE", "odo": 45000, "damage": "Front End", "bid": 8500, "state": "TX"},
    {"lot": "C002", "year": "2019", "make": "Honda", "model": "Civic", "trim": "EX", "odo": 62000, "damage": "Side", "bid": 6200, "state": "CA"},
    {"lot": "C003", "year": "2021", "make": "Ford", "model": "F-150", "trim": "XLT", "odo": 28000, "damage": "Rear End", "bid": 14500, "state": "FL"},
    {"lot": "C004", "year": "2018", "make": "BMW", "model": "3 Series", "trim": "330i", "odo": 55000, "damage": "Mechanical", "bid": 9800, "state": "NY"},
    {"lot": "C005", "year": "2022", "make": "Tesla", "model": "Model 3", "trim": "Standard Range", "odo": 18000, "damage": "Front End", "bid": 22000, "state": "CA"},
    {"lot": "C006", "year": "2020", "make": "Chevrolet", "model": "Silverado", "trim": "LT", "odo": 38000, "damage": "Rollover", "bid": 11200, "state": "TX"},
    {"lot": "C007", "year": "2019", "make": "Mercedes-Benz", "model": "C-Class", "trim": "C300", "odo": 48000, "damage": "Side", "bid": 13500, "state": "GA"},
    {"lot": "C008", "year": "2021", "make": "Nissan", "model": "Altima", "trim": "SV", "odo": 31000, "damage": "Front End", "bid": 7800, "state": "OH"},
    {"lot": "C009", "year": "2017", "make": "Lexus", "model": "RX 350", "trim": "Base", "odo": 72000, "damage": "Flood", "bid": 12000, "state": "LA"},
    {"lot": "C010", "year": "2020", "make": "Hyundai", "model": "Sonata", "trim": "SEL", "odo": 42000, "damage": "Rear End", "bid": 7200, "state": "NC"},
    {"lot": "C011", "year": "2021", "make": "Kia", "model": "Sorento", "trim": "EX", "odo": 25000, "damage": "Front End", "bid": 13800, "state": "VA"},
    {"lot": "C012", "year": "2018", "make": "Subaru", "model": "Outback", "trim": "Premium", "odo": 68000, "damage": "Hail", "bid": 8100, "state": "CO"},
    {"lot": "C013", "year": "2022", "make": "Ram", "model": "1500", "trim": "Big Horn", "odo": 12000, "damage": "Rear End", "bid": 21500, "state": "TX"},
    {"lot": "C014", "year": "2019", "make": "Volkswagen", "model": "Tiguan", "trim": "SE", "odo": 52000, "damage": "Side", "bid": 9200, "state": "NJ"},
    {"lot": "C015", "year": "2020", "make": "Mazda", "model": "CX-5", "trim": "Touring", "odo": 36000, "damage": "Front End", "bid": 10500, "state": "WA"},
]

for c in copart_cars:
    AuctionVehicle.objects.update_or_create(
        lot_number=c["lot"], sync_source="COPART",
        defaults={
            "year": c["year"], "make": c["make"], "model": c["model"],
            "trim": c["trim"], "odometer": c["odo"], "odometer_unit": "mi",
            "damage_primary": c["damage"], "current_bid": c["bid"],
            "normalized_price_usd": c["bid"], "currency": "USD",
            "source_url": f"https://www.copart.com/lot/{c['lot']}",
            "source_auction": f"Copart {c['state']}",
            "location_state": c["state"], "location_country": "US",
            "source_country": "US",
        }
    )

# ── IAAI ──────────────────────────────────────────────────────────────────────
print("🇺🇸 إضافة سيارات IAAI...")
iaai_cars = [
    {"lot": "I001", "year": "2019", "make": "Dodge", "model": "Charger", "trim": "R/T", "odo": 58000, "damage": "Front End", "bid": 9500, "state": "AZ"},
    {"lot": "I002", "year": "2021", "make": "Jeep", "model": "Wrangler", "trim": "Sport", "odo": 22000, "damage": "Rollover", "bid": 18500, "state": "CO"},
    {"lot": "I003", "year": "2020", "make": "Kia", "model": "Telluride", "trim": "EX", "odo": 35000, "damage": "Side", "bid": 16200, "state": "TN"},
    {"lot": "I004", "year": "2018", "make": "Audi", "model": "A4", "trim": "Premium", "odo": 61000, "damage": "Mechanical", "bid": 8900, "state": "IL"},
    {"lot": "I005", "year": "2022", "make": "GMC", "model": "Sierra", "trim": "SLE", "odo": 15000, "damage": "Hail", "bid": 19800, "state": "TX"},
    {"lot": "I006", "year": "2020", "make": "Cadillac", "model": "Escalade", "trim": "Premium", "odo": 42000, "damage": "Front End", "bid": 28500, "state": "FL"},
    {"lot": "I007", "year": "2019", "make": "Lincoln", "model": "Navigator", "trim": "Reserve", "odo": 55000, "damage": "Side", "bid": 24000, "state": "GA"},
    {"lot": "I008", "year": "2021", "make": "Porsche", "model": "Cayenne", "trim": "Base", "odo": 18000, "damage": "Rear End", "bid": 35000, "state": "CA"},
    {"lot": "I009", "year": "2018", "make": "Land Rover", "model": "Range Rover", "trim": "HSE", "odo": 72000, "damage": "Flood", "bid": 22000, "state": "NY"},
    {"lot": "I010", "year": "2022", "make": "Rivian", "model": "R1T", "trim": "Adventure", "odo": 8000, "damage": "Front End", "bid": 42000, "state": "WA"},
]

for c in iaai_cars:
    AuctionVehicle.objects.update_or_create(
        lot_number=c["lot"], sync_source="IAAI",
        defaults={
            "year": c["year"], "make": c["make"], "model": c["model"],
            "trim": c["trim"], "odometer": c["odo"], "odometer_unit": "mi",
            "damage_primary": c["damage"], "current_bid": c["bid"],
            "normalized_price_usd": c["bid"], "currency": "USD",
            "source_url": f"https://www.iaai.com/vehicle/{c['lot']}",
            "source_auction": f"IAAI {c['state']}",
            "location_state": c["state"], "location_country": "US",
            "source_country": "US",
        }
    )

# ── ACV ───────────────────────────────────────────────────────────────────────
print("🇺🇸 إضافة سيارات ACV...")
acv_cars = [
    {"lot": "A001", "year": "2020", "make": "Toyota", "model": "RAV4", "trim": "XLE", "odo": 32000, "bid": 18500, "state": "TX"},
    {"lot": "A002", "year": "2021", "make": "Honda", "model": "CR-V", "trim": "EX-L", "odo": 28000, "bid": 21000, "state": "OH"},
    {"lot": "A003", "year": "2019", "make": "Ford", "model": "Explorer", "trim": "XLT", "odo": 48000, "bid": 16800, "state": "MI"},
    {"lot": "A004", "year": "2022", "make": "Chevrolet", "model": "Equinox", "trim": "LT", "odo": 15000, "bid": 19200, "state": "IL"},
    {"lot": "A005", "year": "2020", "make": "Nissan", "model": "Rogue", "trim": "SV", "odo": 38000, "bid": 15500, "state": "GA"},
]

for c in acv_cars:
    AuctionVehicle.objects.update_or_create(
        lot_number=c["lot"], sync_source="ACV",
        defaults={
            "year": c["year"], "make": c["make"], "model": c["model"],
            "trim": c["trim"], "odometer": c["odo"], "odometer_unit": "mi",
            "current_bid": c["bid"], "normalized_price_usd": c["bid"],
            "currency": "USD",
            "source_url": f"https://app.acvauctions.com/auction/{c['lot']}",
            "source_auction": "ACV Auctions",
            "location_state": c["state"], "location_country": "US",
            "source_country": "US",
        }
    )

# ── الملخص ───────────────────────────────────────────────────────────────────
total = AuctionVehicle.objects.count()
print(f"\n✅ إجمالي السيارات في قاعدة البيانات: {total}")
for s in AuctionVehicle.objects.values('sync_source').annotate(c=Count('id')).order_by('-c'):
    print(f"   {s['sync_source']}: {s['c']} سيارة")

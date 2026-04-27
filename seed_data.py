"""
Seed database with real data from Encar + simulated Copart/IAAI data
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from core.models import AuctionVehicle
import random
from datetime import datetime, timedelta, timezone

print("Seeding database with real Encar data + simulated auction data...")

# ── Real data from Encar API ──────────────────────────────────────────────
sys.path.insert(0, '.')
from scrapers.korea.encar_scraper import EncarScraper

encar = EncarScraper(delay=0.5)
encar_count = 0
print("Fetching real Korean cars from Encar...")
for batch in encar.fetch_pages(max_pages=3, page_size=20):
    for v in batch:
        try:
            AuctionVehicle.objects.update_or_create(
                lot_number=v['lot_number'],
                defaults={
                    'source_auction': 'ENCAR',
                    'source_country': 'KR',
                    'source_url': v.get('source_url', ''),
                    'year': v.get('year'),
                    'make': v.get('make', ''),
                    'model': v.get('model', ''),
                    'color': v.get('color', ''),
                    'odometer': v.get('odometer'),
                    'odometer_unit': 'km',
                    'current_bid': v.get('current_bid', 0),
                    'normalized_price_usd': v.get('current_bid', 0),
                    'currency': 'USD',
                    'location_city': v.get('location_city', ''),
                    'location_country': 'KR',
                    'status': 'active',
                    'primary_image': v.get('primary_image', ''),
                    'fuel_type': v.get('fuel_type', 'petrol'),
                    'title_type': 'clean',
                    'vin': v.get('vin', ''),
                }
            )
            encar_count += 1
        except Exception as e:
            pass

print(f"  ✅ Encar: {encar_count} cars saved")

# ── Simulated Copart data (realistic) ────────────────────────────────────
copart_cars = [
    {"make": "Toyota", "model": "Camry", "year": 2019, "damage": "Front End", "bid": 4200, "state": "TX"},
    {"make": "Toyota", "model": "Land Cruiser", "year": 2018, "damage": "Rear End", "bid": 18500, "state": "CA"},
    {"make": "Toyota", "model": "Hilux", "year": 2020, "damage": "Minor Dents", "bid": 12000, "state": "FL"},
    {"make": "Toyota", "model": "Corolla", "year": 2021, "damage": "Hail", "bid": 3800, "state": "TX"},
    {"make": "Toyota", "model": "RAV4", "year": 2020, "damage": "Water/Flood", "bid": 6500, "state": "LA"},
    {"make": "Nissan", "model": "Patrol", "year": 2019, "damage": "Rollover", "bid": 15000, "state": "TX"},
    {"make": "Nissan", "model": "Altima", "year": 2020, "damage": "Front End", "bid": 5200, "state": "GA"},
    {"make": "Mitsubishi", "model": "Pajero", "year": 2018, "damage": "Mechanical", "bid": 8900, "state": "CA"},
    {"make": "Hyundai", "model": "Sonata", "year": 2021, "damage": "Hail", "bid": 4100, "state": "TX"},
    {"make": "Kia", "model": "Sportage", "year": 2020, "damage": "Front End", "bid": 7200, "state": "FL"},
    {"make": "BMW", "model": "X5", "year": 2019, "damage": "Rear End", "bid": 14000, "state": "NY"},
    {"make": "Mercedes-Benz", "model": "E-Class", "year": 2018, "damage": "Side", "bid": 11000, "state": "CA"},
    {"make": "Ford", "model": "F-150", "year": 2020, "damage": "Front End", "bid": 9800, "state": "TX"},
    {"make": "Chevrolet", "model": "Tahoe", "year": 2019, "damage": "Water/Flood", "bid": 13500, "state": "LA"},
    {"make": "Dodge", "model": "Ram 1500", "year": 2021, "damage": "Hail", "bid": 11200, "state": "TX"},
    {"make": "Toyota", "model": "FJ Cruiser", "year": 2014, "damage": "Rollover", "bid": 16000, "state": "AZ"},
    {"make": "Lexus", "model": "LX570", "year": 2017, "damage": "Rear End", "bid": 22000, "state": "CA"},
    {"make": "Toyota", "model": "Prado", "year": 2019, "damage": "Minor Dents", "bid": 19500, "state": "TX"},
    {"make": "Jeep", "model": "Wrangler", "year": 2020, "damage": "Rollover", "bid": 14500, "state": "CO"},
    {"make": "Honda", "model": "Accord", "year": 2021, "damage": "Front End", "bid": 5500, "state": "FL"},
]

copart_count = 0
for i, car in enumerate(copart_cars):
    lot = f"CP{random.randint(10000000, 99999999)}"
    vin = f"{''.join(random.choices('ABCDEFGHJKLMNPRSTUVWXYZ0123456789', k=17))}"
    try:
        AuctionVehicle.objects.update_or_create(
            lot_number=lot,
            defaults={
                'source_auction': 'COPART',
                'source_country': 'US',
                'source_url': f'https://www.copart.com/lot/{lot}',
                'year': car['year'],
                'make': car['make'],
                'model': car['model'],
                'vin': vin,
                'odometer': random.randint(30000, 180000),
                'odometer_unit': 'miles',
                'damage_primary': car['damage'],
                'title_type': 'salvage',
                'current_bid': float(car['bid']),
                'normalized_price_usd': float(car['bid']),
                'currency': 'USD',
                'location_city': random.choice(['Dallas', 'Houston', 'Los Angeles', 'Miami', 'Atlanta']),
                'location_state': car['state'],
                'location_country': 'US',
                'status': 'active',
                'has_keys': random.choice([True, False]),
                'runs_drives': random.choice([True, False]),
                'fuel_type': 'petrol',
                'color': random.choice(['White', 'Black', 'Silver', 'Red', 'Blue', 'Gray']),
                'auction_date': datetime.now(timezone.utc) + timedelta(days=random.randint(1, 14)),
                'primary_image': f'https://cs.copart.com/v1/AUTH_svc.pdoc00001/lpp/{lot[:4]}/pic{lot}_thb.jpg',
            }
        )
        copart_count += 1
    except Exception as e:
        print(f"  Error: {e}")

print(f"  ✅ Copart: {copart_count} cars saved")

# ── Simulated IAAI data ───────────────────────────────────────────────────
iaai_cars = [
    {"make": "Toyota", "model": "Camry", "year": 2020, "bid": 5100, "state": "TX"},
    {"make": "Toyota", "model": "Corolla", "year": 2019, "bid": 3200, "state": "CA"},
    {"make": "Nissan", "model": "Maxima", "year": 2018, "bid": 4800, "state": "FL"},
    {"make": "Honda", "model": "CR-V", "year": 2021, "bid": 8200, "state": "GA"},
    {"make": "Toyota", "model": "Tundra", "year": 2019, "bid": 16000, "state": "TX"},
    {"make": "Lexus", "model": "RX350", "year": 2018, "bid": 12500, "state": "CA"},
    {"make": "Infiniti", "model": "QX80", "year": 2017, "bid": 18000, "state": "NY"},
    {"make": "Hyundai", "model": "Tucson", "year": 2020, "bid": 6800, "state": "TX"},
    {"make": "Kia", "model": "Sorento", "year": 2019, "bid": 7500, "state": "FL"},
    {"make": "Mitsubishi", "model": "Outlander", "year": 2020, "bid": 7200, "state": "CA"},
]

iaai_count = 0
for car in iaai_cars:
    lot = f"IA{random.randint(10000000, 99999999)}"
    vin = f"{''.join(random.choices('ABCDEFGHJKLMNPRSTUVWXYZ0123456789', k=17))}"
    try:
        AuctionVehicle.objects.update_or_create(
            lot_number=lot,
            defaults={
                'source_auction': 'IAAI',
                'source_country': 'US',
                'source_url': f'https://www.iaai.com/VehicleDetail/{lot}',
                'year': car['year'],
                'make': car['make'],
                'model': car['model'],
                'vin': vin,
                'odometer': random.randint(40000, 200000),
                'odometer_unit': 'miles',
                'damage_primary': random.choice(['Front End', 'Rear End', 'Hail', 'Water/Flood', 'Side']),
                'title_type': 'salvage',
                'current_bid': float(car['bid']),
                'normalized_price_usd': float(car['bid']),
                'currency': 'USD',
                'location_city': random.choice(['Dallas', 'Houston', 'Los Angeles', 'Miami']),
                'location_state': car['state'],
                'location_country': 'US',
                'status': 'active',
                'has_keys': random.choice([True, False]),
                'runs_drives': random.choice([True, False]),
                'fuel_type': 'petrol',
                'color': random.choice(['White', 'Black', 'Silver', 'Red', 'Blue']),
                'auction_date': datetime.now(timezone.utc) + timedelta(days=random.randint(1, 10)),
                'primary_image': '',
            }
        )
        iaai_count += 1
    except Exception as e:
        print(f"  IAAI Error: {e}")

print(f"  ✅ IAAI: {iaai_count} cars saved")

total = AuctionVehicle.objects.count()
print(f"\n✅ Total vehicles in DB: {total}")
print("  Sources:", list(AuctionVehicle.objects.values_list('source_auction', flat=True).distinct()))

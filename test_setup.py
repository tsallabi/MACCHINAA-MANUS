import django
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

try:
    django.setup()
    print("Django setup OK")
except Exception as e:
    print(f"Django setup ERROR: {e}")
    sys.exit(1)

try:
    from core.models import AuctionVehicle
    print(f"Models OK: {AuctionVehicle._meta.verbose_name}")
except Exception as e:
    print(f"Models ERROR: {e}")
    sys.exit(1)

try:
    from api.views import VehicleViewSet
    print("API views OK")
except Exception as e:
    print(f"API views ERROR: {e}")

try:
    from dashboard.views import index
    print("Dashboard views OK")
except Exception as e:
    print(f"Dashboard views ERROR: {e}")

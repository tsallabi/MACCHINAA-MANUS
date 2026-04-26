"""
MACCHINAA-EVOLVED — Django Settings
=====================================
نسخة محسّنة ومطوّرة من مشروع MACCHINAA
"""
import os
from pathlib import Path

# ── Base ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-macchinaa-evolved-change-in-production-xyz123",
)

DEBUG = os.environ.get("DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,*"
).split(",")

# ── Applications ──────────────────────────────────────────────────────────
INSTALLED_APPS = [
    # Django built-in
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",

    # Third-party
    "rest_framework",
    "django_filters",

    # MACCHINAA-EVOLVED apps
    "core",
    "scrapers",
    "api",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# ── Database ──────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ── REST Framework ────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
}

# ── Static Files ──────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ── Internationalisation ──────────────────────────────────────────────────
LANGUAGE_CODE = "ar"
TIME_ZONE = "Africa/Tripoli"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── Scraper Settings ──────────────────────────────────────────────────────
SCRAPER_DEFAULT_DELAY = float(os.environ.get("SCRAPER_DEFAULT_DELAY", "1.5"))
SCRAPER_MAX_PAGES_DEFAULT = int(os.environ.get("SCRAPER_MAX_PAGES_DEFAULT", "50"))

# ACV Credentials
ACV_USERNAME = os.environ.get("ACV_USERNAME", "")
ACV_PASSWORD = os.environ.get("ACV_PASSWORD", "")

# Manheim Credentials
MANHEIM_CLIENT_ID = os.environ.get("MANHEIM_CLIENT_ID", "")
MANHEIM_CLIENT_SECRET = os.environ.get("MANHEIM_CLIENT_SECRET", "")

# ADESA Credentials
ADESA_BEARER_TOKEN = os.environ.get("ADESA_BEARER_TOKEN", "")
ADESA_DEALER_ID = os.environ.get("ADESA_DEALER_ID", "")

# Libya Import Cost Settings (default port: Misrata)
LIBYA_DEFAULT_PORT = os.environ.get("LIBYA_DEFAULT_PORT", "misrata")
LIBYA_CUSTOMS_RATE = float(os.environ.get("LIBYA_CUSTOMS_RATE", "0.15"))
LIBYA_SHIPPING_BASE = float(os.environ.get("LIBYA_SHIPPING_BASE", "1200"))

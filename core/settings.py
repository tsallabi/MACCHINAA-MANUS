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
    "ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0"
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
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",

    # MACCHINAA-EVOLVED apps
    "core",
    "scrapers",
    "api",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
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
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# ── Database ──────────────────────────────────────────────────────────────
import dj_database_url

_db_url = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR}/db.sqlite3")
DATABASES = {"default": dj_database_url.parse(_db_url, conn_max_age=600)}

# ── Cache (Redis) ─────────────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "macchinaa-evolved",
    }
}

# Use Redis cache if available
try:
    import redis as _redis
    _r = _redis.from_url(REDIS_URL, socket_connect_timeout=1)
    _r.ping()
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "TIMEOUT": 3600,
        }
    }
except Exception:
    pass  # Fall back to LocMemCache

# ── Celery ────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Africa/Tripoli"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ── REST Framework ────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# ── CORS ──────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://macchinaa.com",
    "https://macchina-web.onrender.com",
]

# ── Static & Media ────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ── Internationalization ──────────────────────────────────────────────────
LANGUAGE_CODE = "ar"
TIME_ZONE = "Africa/Tripoli"
USE_I18N = True
USE_L10N = True
USE_TZ = True

LANGUAGES = [
    ("ar", "Arabic"),
    ("en", "English"),
]

LOCALE_PATHS = [BASE_DIR / "locale"]

# ── Logging ───────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "scrapers": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING"},
    },
}

# ── Auction API Keys (from environment) ───────────────────────────────────
COPART_API_KEY         = os.environ.get("COPART_API_KEY", "")
COPART_USERNAME        = os.environ.get("COPART_USERNAME", "")
COPART_PASSWORD        = os.environ.get("COPART_PASSWORD", "")

IAAI_API_KEY           = os.environ.get("IAAI_API_KEY", "")
IAAI_USERNAME          = os.environ.get("IAAI_USERNAME", "")
IAAI_PASSWORD          = os.environ.get("IAAI_PASSWORD", "")

MANHEIM_CLIENT_ID      = os.environ.get("MANHEIM_CLIENT_ID", "")
MANHEIM_CLIENT_SECRET  = os.environ.get("MANHEIM_CLIENT_SECRET", "")

ADESA_BEARER_TOKEN     = os.environ.get("ADESA_BEARER_TOKEN", "")
ADESA_DEALER_ID        = os.environ.get("ADESA_DEALER_ID", "")

ACV_API_TOKEN          = os.environ.get("ACV_API_TOKEN", "")
ACV_DEALER_ID          = os.environ.get("ACV_DEALER_ID", "")

GSA_API_KEY            = os.environ.get("GSA_API_KEY", "DEMO_KEY")

EXCHANGE_RATES_API_KEY = os.environ.get("EXCHANGE_RATES_API_KEY", "")

# ── Scraper Defaults ──────────────────────────────────────────────────────
SCRAPER_DEFAULT_DELAY       = float(os.environ.get("SCRAPER_DEFAULT_DELAY", "1.5"))
SCRAPER_MAX_PAGES_DEFAULT   = int(os.environ.get("SCRAPER_MAX_PAGES_DEFAULT", "100"))
SCRAPER_REQUEST_TIMEOUT     = int(os.environ.get("SCRAPER_REQUEST_TIMEOUT", "30"))
SCRAPER_MAX_RETRIES         = int(os.environ.get("SCRAPER_MAX_RETRIES", "3"))

# ── Libya-specific Settings ───────────────────────────────────────────────
LIBYAN_PORTS = {
    "misrata": {"name_ar": "ميناء مصراتة", "transit_days": 35, "cost_usd": 1200},
    "tripoli":  {"name_ar": "ميناء طرابلس",  "transit_days": 40, "cost_usd": 1100},
    "benghazi": {"name_ar": "ميناء بنغازي",  "transit_days": 45, "cost_usd": 1300},
}

LIBYAN_CUSTOMS_RATE = 0.30   # 30% customs duty on CIF value
LIBYAN_VAT_RATE     = 0.00   # No VAT currently

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

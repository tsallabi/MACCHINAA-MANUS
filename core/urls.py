"""MACCHINAA-EVOLVED — URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("dashboard.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "MACCHINAA-EVOLVED Admin"
admin.site.site_title = "MACCHINAA-EVOLVED"
admin.site.index_title = "لوحة تحكم المزادات"

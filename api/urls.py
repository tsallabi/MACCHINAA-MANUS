"""MACCHINAA-EVOLVED — API URL Configuration"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r"vehicles", views.VehicleViewSet, basename="vehicle")
router.register(r"sync-runs", views.SyncRunViewSet, basename="sync-run")
router.register(r"alerts", views.PriceAlertViewSet, basename="alert")

urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include("rest_framework.urls")),

    # Special endpoints
    path("vehicles/<int:pk>/import-cost/",
         views.ImportCostView.as_view(), name="import-cost"),
    path("sync/trigger/",
         views.TriggerSyncView.as_view(), name="trigger-sync"),
    path("stats/",
         views.StatsView.as_view(), name="stats"),
    path("makes/",
         views.MakesListView.as_view(), name="makes-list"),
]

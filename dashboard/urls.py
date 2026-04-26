"""MACCHINAA-EVOLVED — Dashboard URLs"""
from django.urls import path
from . import views

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("vehicles/", views.VehicleListView.as_view(), name="vehicle-list"),
    path("vehicles/<int:pk>/", views.VehicleDetailView.as_view(), name="vehicle-detail"),
    path("sync-dashboard/", views.SyncDashboardView.as_view(), name="sync-dashboard"),
    path("calculator/", views.CalculatorView.as_view(), name="calculator"),
]

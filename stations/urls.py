from django.urls import path

from . import views

urlpatterns = [
    path("route/", views.route_api, name="route-api"),
    path("route/map/", views.route_map, name="route-map"),
]

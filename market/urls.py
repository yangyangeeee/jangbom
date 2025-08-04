from django.urls import path
from .views import *

app_name = 'market'

urlpatterns = [
    path('nearest/', nearest_market_view, name = "nearest_market"),
    path('direction/', map_direction_view, name='map_direction'),
]
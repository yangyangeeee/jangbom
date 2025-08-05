from django.urls import path
from .views import *

app_name = 'market'

urlpatterns = [
    path('nearest/', nearest_market_view, name = "nearest_market"),
    path('direction/', map_direction_view, name='map_direction'),
    path('arrival/<int:shoppinglist_id>/', market_arrival_view, name='market_arrival'),
    path('verify-secret/', verify_secret_code, name='verify_secret'),
    path('secret-input/<int:market_id>/', secret_input_view, name='secret_input'),
    path('success/<int:shoppinglist_id>/', shopping_success_view, name='shopping_success'),
]
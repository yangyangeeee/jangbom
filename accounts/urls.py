from django.urls import path
from .views import *

app_name = 'accounts'

urlpatterns = [
    path('signup/', signup_view, name='signup'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('activity/', activity_log_view, name='activity_log'),
    path('activity/history/', activity_history_view, name='activity_history'),
    path('activity/<int:shopping_list_id>/', activity_detail_view, name='activity_detail'),
    path('recipes/', my_recipes, name='my_recipes'),
    path('recipes/<int:recipe_id>/', recipe_detail, name='recipe_detail'),
    # 주소 설정
    path("address/", address_settings, name="address_settings"),
    path("address/search/", address_search, name="address_search"),
    path("address/delete/<int:addr_id>/", address_delete, name="address_delete"),
    path("address/confirm/", address_confirm, name="address_confirm"),
    path("address/select/<int:addr_id>/", address_select_primary, name="address_select_primary"),
    path("address/map/", address_pick_map, name="address_pick_map"),
    path("address/save-from-map/", address_save_from_map, name="address_save_from_map"),
]
from django.urls import path
from .views import *

app_name = 'accounts'

urlpatterns = [
    path('signup/', signup_view, name='signup'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('activity/', activity_log_view, name='activity_log'),
    path('activity/<int:shopping_list_id>/', activity_detail_view, name='activity_detail'),
    path('recipes/', my_recipes, name='my_recipes'),
    path('recipes/<int:recipe_id>/', recipe_detail, name='recipe_detail'),
]
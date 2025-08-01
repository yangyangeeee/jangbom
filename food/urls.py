from django.urls import path
from .views import *

app_name = 'food'

urlpatterns = [
    path('', main, name='main'),
    path('recipe/start/', recipe_input_view, name='recipe_input'),
    path('recipe/ingredients/', recipe_ingredient_result, name='recipe_ingredients'),
    path('recipe/confirm/', confirm_shopping_list, name='confirm_shopping_list'),
    path('recipe/result/', shopping_list_result, name='shopping_list_result'),
    path('chat/', chat_with_gpt, name='chat'),
    path('recipe/search/', ingredient_search_view, name='ingredient_search'),
]
from django.urls import path
from .views import *

app_name = 'food'

urlpatterns = [
    path('', main, name='main'),
    # 요리를 할거야
    path('recipe/start/', recipe_input_view, name='recipe_input'),
    path('recipe/ingredients/', recipe_ingredient_result, name='recipe_ingredients'),
    path('recipe/confirm/', confirm_shopping_list, name='confirm_shopping_list'),
    path('recipe/result/', recipe_result_view, name='recipe_result'),
    path('recipe/ai/', recipe_ai, name='recipe_ai'),
    path('recipe/search/', ingredient_search_view, name='ingredient_search'),
    
    # 식재료를 고를거야
    path('ingredient/', ingredient_input_view, name='ingredient_input'),
    path('ingredient/add/', add_ingredient, name='add_ingredient'),
    path('ingredient/delete/<str:name>/', delete_ingredient, name='delete_ingredient'),
    path('ingredient/result/', ingredient_result_view, name='ingredient_result'),
    path('ingredient/ai/<str:name>/', ingredient_ai_view, name='ingredient_ai'),
    path("ingredient/add_ai/", add_ingredient_ai, name="add_ingredient_ai"),

    #레시피 저장
    path('leftover/', show_recent_ingredients, name='show_recent_ingredients'),
    path('leftover/result/', find_recipes_with_gpt, name='find_recipes_with_gpt'),
]
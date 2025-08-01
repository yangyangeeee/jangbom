from django.urls import path
from .views import *

app_name = 'food'

urlpatterns = [
    path('', main, name='main'),
]
from django.contrib import admin
from .models import *

admin.site.register(Market)
admin.site.register(MarketStore)
admin.site.register(MarketStock)
admin.site.register(StoreStock)
admin.site.register(ShoppingList)
admin.site.register(ShoppingListIngredient)
admin.site.register(ActivityLog)
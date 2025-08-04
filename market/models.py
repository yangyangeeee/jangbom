from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from food.models import Ingredient

User = get_user_model()


class Market(models.Model):
    MARKET_TYPE_CHOICES = [
        ('마트', '마트'),
        ('전통시장', '전통시장'),
    ]

    name = models.CharField(max_length=100)
    market_type = models.CharField(max_length=20, choices=MARKET_TYPE_CHOICES)
    address = models.CharField(max_length=200)
    latitude = models.FloatField()
    longitude = models.FloatField()
    phone = models.CharField(max_length=20, blank=True)
    image = models.ImageField(upload_to='market/', blank=True, null=True)
    secret_code = models.CharField(max_length=20)
    open_days = models.CharField(max_length=50, help_text="예: 월,화,수,목,금")
    open_time = models.TimeField(help_text="예: 09:00")
    close_time = models.TimeField(help_text="예: 18:00")

    def __str__(self):
        return self.name


class MarketStore(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.market.name} - {self.name}"


class MarketStock(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    last_updated = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.market.market_type == '전통시장':
            raise ValidationError('전통시장에는 MarketStock을 등록할 수 없습니다. MarketStore를 이용하세요.')

    def __str__(self):
        return f"{self.market.name} - {self.ingredient.name} ({self.quantity})"


class StoreStock(models.Model):
    store = models.ForeignKey(MarketStore, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.store.name} - {self.ingredient.name} ({self.quantity})"


class ShoppingList(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    market = models.ForeignKey(Market, on_delete=models.SET_NULL, null=True, blank=True)  # 실제 사용한 마트
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.created_at.date()}"


class ShoppingListIngredient(models.Model):
    shopping_list = models.ForeignKey(ShoppingList, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.shopping_list.id} - {self.ingredient.name}"


class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    shopping_list = models.ForeignKey(ShoppingList, on_delete=models.CASCADE)
    visited_at = models.DateTimeField(auto_now_add=True)
    point_earned = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user} - {self.point_earned}P"

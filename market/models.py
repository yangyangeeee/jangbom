from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from food.models import Ingredient
from django.conf import settings
from django.db.models import Q

User = get_user_model()


class Market(models.Model):
    MARKET_TYPE_CHOICES = [
        ('마트', '마트'),
        ('전통시장', '전통시장'),
    ]

    name = models.CharField(max_length=100)
    market_type = models.CharField(max_length=20, choices=MARKET_TYPE_CHOICES)
    address = models.CharField(max_length=200)
    dong = models.CharField(max_length=10, blank=True)
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


class MarketStock(models.Model):
    market = models.ForeignKey(Market, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    last_updated = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.market.market_type == '전통시장':
            raise ValidationError('전통시장에는 MarketStock을 등록할 수 없습니다.')

    def __str__(self):
        return f"{self.market.name} - {self.ingredient.name}"


class ShoppingList(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    market = models.ForeignKey(Market, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_done = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.id} - {self.user.username} - {self.created_at.date()}"


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
    






"""class MarketFilterSetting(models.Model):
    class TypePref(models.TextChoices):
        NONE = 'none', '상관 없어요'
        MART = 'mart', '동네 마트를 우선'
        TRAD = 'trad', '전통 시장을 우선'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='market_filter'
    )
    # 거리 제한 (미설정이면 상관없음). UI에서 1km 체크면 1000 저장.
    radius_m = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='단위: m, 비우면 상관없음'
    )
    # 마켓 타입 우선순위
    type_preference = models.CharField(
        max_length=10,
        choices=TypePref.choices,
        default=TypePref.NONE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(radius_m__gt=0) | Q(radius_m__isnull=True),
                name='radius_positive_or_null'
            )
        ]

    def __str__(self):
        return f'{self.user} filter'"""
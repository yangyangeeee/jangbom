from django.db import models
from django.contrib.auth import get_user_model
User = get_user_model()

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class Ingredient(models.Model):
    name = models.CharField(max_length=100, unique=True)
    category = models.ManyToManyField(to=Category, through='IngredientCategory', related_name='ingredients')
    image = models.ImageField(upload_to='ingredients/', blank=True, null=True)

    def __str__(self):
        return self.name

class IngredientCategory(models.Model):
    ingredient = models.ForeignKey(to=Ingredient, on_delete=models.CASCADE, related_name='ingredient_categories')
    category = models.ForeignKey(to=Category, on_delete=models.CASCADE, related_name='ingredient_categories')

    def __str__(self):
        return f"{self.ingredient.name} in {self.category.name}"
    
class ShoppingList(models.Model):
    user = models.ForeignKey(to=User, on_delete=models.CASCADE)
    destination = models.CharField(max_length=100, default="미지정")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.destination} - {self.created_at.date()}"

class ShoppingListIngredient(models.Model):
    shopping_list = models.ForeignKey(to=ShoppingList, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(to=Ingredient, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.shopping_list.id} - {self.ingredient.name}"
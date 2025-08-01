from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.
class CustomUser(AbstractUser):
    nickname = models.CharField(max_length=30, unique=True)
    location = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.username
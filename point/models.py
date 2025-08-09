from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class UserPoint(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='point')
    total_point = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.user.username} - {self.total_point}P"
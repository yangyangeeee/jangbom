from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    nickname = forms.CharField(max_length=30)
    location = forms.CharField(max_length=100, required=False)

    class Meta:
        model = CustomUser
        fields = ('username', 'nickname', 'location', 'password1', 'password2')


class CustomLoginForm(AuthenticationForm):
    username = forms.CharField(label="아이디")
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput)

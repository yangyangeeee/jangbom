from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from .forms import CustomUserCreationForm, CustomLoginForm
from django.db.models import Count, Sum, F, Window
from django.db.models.functions import Rank
from market.models import *
from food.models import *
from django.contrib.auth.decorators import login_required

# Create your views here.
def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('food:main')  # 로그인 후 이동할 페이지
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/signup.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('food:main')
    else:
        form = CustomLoginForm()
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('food:main')

@login_required
def activity_log_view(request):
    user = request.user
    logs = ActivityLog.objects.filter(user=user).select_related('shopping_list__market').order_by('-visited_at')

    # 누적 거리 계산 (거리 = point / 100)
    total_points = logs.aggregate(total=Sum('point_earned'))['total'] or 0
    total_distance_km = total_points / 100

    # 누적 통계
    total_logs = logs.count()
    market_visits = logs.filter(shopping_list__market__market_type='전통시장').count()
    total_steps = int(total_distance_km * 1300)  # 평균 1km당 1300걸음
    co2_saved_kg = round(total_distance_km * 0.232, 2)  # kg 단위

    # 로그별 상세정보
    log_data = []
    for log in logs:
        shopping_list = log.shopping_list
        ingredients = ShoppingListIngredient.objects.filter(
            shopping_list=shopping_list
        ).select_related('ingredient')

        log_data.append({
            'visited_at': log.visited_at,
            'point_earned': log.point_earned,
            'market_name': shopping_list.market.name if shopping_list.market else '미지정 마트',
            'ingredients': [i.ingredient.name for i in ingredients],
            'shopping_list_id': shopping_list.id,
        })
    
    # 사용자별 누적 포인트 랭킹 계산
    ranking_qs = (
        ActivityLog.objects.values('user')  # 각 유저별
        .annotate(total_points=Sum('point_earned'))  # 누적 포인트
        .order_by('-total_points')  # 내림차순
    )

    # 현재 유저 랭킹 찾기
    user_rank = None
    for idx, entry in enumerate(ranking_qs, start=1):
        if entry['user'] == user.id:
            user_rank = idx
            break

    return render(request, 'accounts/activity_log.html', {
        'log_data': log_data,
        'total_logs': total_logs,
        'market_visits': market_visits,
        'total_steps': total_steps,
        'co2_saved_kg': co2_saved_kg,
        'user_rank': user_rank,
    })

@login_required
def activity_detail_view(request, shopping_list_id):
    shopping_list = get_object_or_404(
        ShoppingList.objects.select_related('market'),
        id=shopping_list_id,
        user=request.user
    )

    ingredients = ShoppingListIngredient.objects.filter(
        shopping_list=shopping_list
    ).select_related('ingredient')

    # 연결된 ActivityLog에서 포인트 가져오기
    log = ActivityLog.objects.filter(user=request.user, shopping_list=shopping_list).first()
    point_earned = log.point_earned if log else 0

    return render(request, 'accounts/activity_detail.html', {
        'shopping_list': shopping_list,
        'ingredients': ingredients,
        'point_earned': point_earned,
    })

@login_required
def my_recipes(request):
    recipes = SavedRecipe.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'accounts/my_recipes.html', {'recipes': recipes})

@login_required
def recipe_detail(request, recipe_id):
    recipe = get_object_or_404(SavedRecipe, id=recipe_id, user=request.user)
    return render(request, 'accounts/recipe_detail.html', {'recipe': recipe})
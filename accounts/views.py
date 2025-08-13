from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from .forms import CustomUserCreationForm, CustomLoginForm
from django.db.models import Count, Sum, F, Window
from django.db.models.functions import Rank
from market.models import *
from food.models import *
from django.contrib.auth.decorators import login_required
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q

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
    logs = ActivityLog.objects.filter(user=user, shopping_list__is_done=True).select_related('shopping_list__market').order_by('-visited_at')
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
STEPS_PER_KM = 1300       # 1km ≈ 1,300걸음(평균 보폭 기준 대략치)
KCAL_PER_KM  = 50         # 1km당 약 50kcal(평균 체중/보행 속도 가정)

@login_required
def activity_detail_view(request, shopping_list_id):
    shopping_list = get_object_or_404(
        ShoppingList.objects.select_related('market'),
        id=shopping_list_id,
        user=request.user
    )

    ingredients = (ShoppingListIngredient.objects.filter(shopping_list=shopping_list).select_related('ingredient'))

    # 연결된 ActivityLog에서 포인트 가져오기
    log = ActivityLog.objects.filter(user=request.user, shopping_list=shopping_list).first()
    point_earned = log.point_earned if log else 0

    # ---- 포인트 기반 추정치 계산 ----
    # points = round(distance_km * 100)  =>  distance_km ≈ points / 100
    distance_km = point_earned / 100.0
    steps = int(round(distance_km * STEPS_PER_KM))
    calories_kcal = int(round(distance_km * KCAL_PER_KM))

    return render(request, 'accounts/activity_detail.html', {
        'shopping_list': shopping_list,
        'ingredients': ingredients,
        'point_earned': point_earned,

        # 추가된 컨텍스트
        'distance_km': distance_km,
        'steps': steps,
        'calories_kcal': calories_kcal,
    })

@login_required
def my_recipes(request):
    q = request.GET.get('q', '').strip()        # 검색어
    sort = request.GET.get('sort', 'latest')    # 정렬 기준 (기본: 최신순)

    recipes = SavedRecipe.objects.filter(user=request.user)

    # 검색 필터
    if q:
        recipes = recipes.filter(title__icontains=q)

    # 정렬 조건
    if sort == 'latest':
        recipes = recipes.order_by('-created_at')
    elif sort == 'alpha':  # 가나다/알파벳순
        recipes = recipes.order_by('title')

    return render(request, 'accounts/my_recipes.html', {
        'recipes': recipes,
        'q': q,
        'sort': sort,
    })

@login_required
def recipe_detail(request, recipe_id):
    recipe = get_object_or_404(SavedRecipe, id=recipe_id, user=request.user)
    return render(request, 'accounts/recipe_detail.html', {'recipe': recipe})

_PERIODS = {
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
    "all": None,
}

@login_required
def activity_history_view(request):
    user = request.user

    # 현재 선택값 (없으면 기본값)
    q = (request.GET.get("q") or "").strip()
    period = request.GET.get("period") or "1m"
    sort = request.GET.get("sort") or "latest"

    # 기본 쿼리
    qs = (
        ActivityLog.objects
        .filter(user=user)
        .select_related("shopping_list__market")
    )

    # 기간 필터
    if period not in _PERIODS:
        period = "1m"
    delta = _PERIODS[period]
    if delta is not None:
        since = timezone.now() - delta
        qs = qs.filter(visited_at__gte=since)

    # 검색: 마트 이름만
    if q:
        qs = qs.filter(shopping_list__market__name__icontains=q)

    # 정렬
    if sort == "points":
        qs = qs.order_by("-point_earned")  # 포인트 높은 순
    else:
        sort = "latest"
        qs = qs.order_by("-visited_at")

    # 템플릿용 최소 데이터
    log_data = []
    for log in qs:
        sl = log.shopping_list
        market_name = sl.market.name if (sl and sl.market) else "미지정"
        log_data.append({
            "visited_at": log.visited_at,
            "market_name": market_name,
            "shopping_list_id": sl.id if sl else None,
        })

    return render(request, "accounts/activity_history.html", {
        "q": q,
        "period": period,
        "sort": sort,
        "log_data": log_data,
    })
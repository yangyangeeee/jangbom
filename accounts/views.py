from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from .forms import CustomUserCreationForm, CustomLoginForm
from django.db.models import Sum
from market.models import *
from food.models import *
from point.models import *
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from django.contrib import messages
from django.conf import settings
from .models import CustomUser, Address
import requests
from django.http import JsonResponse
from food.views import get_user_total_point, cart_items_count


def _mirror_user_address(user: CustomUser, addr: Address):
    """user.selected_address 및 미러 필드를 addr 기준으로 동기화"""
    user.selected_address = addr
    user.address = addr.address
    user.addr_level1 = addr.addr_level1
    user.addr_level2 = addr.addr_level2
    user.addr_level3 = addr.addr_level3
    user.latitude = addr.latitude
    user.longitude = addr.longitude
    user.save(update_fields=[
        "selected_address", "address", "addr_level1", "addr_level2",
        "addr_level3", "latitude", "longitude"
    ])


def _kakao_address_search(query: str, size: int = 20):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"}

    # 주소 검색 size 최대 30으로 제한
    try:
        size = int(size)
    except Exception:
        size = 20
    size = max(1, min(size, 30))

    params = {"query": query, "size": size}

    r = requests.get(url, headers=headers, params=params, timeout=5)
    if r.status_code != 200:
        # 이유 바로 보이게 에러 본문도 출력
        raise Exception(f"Kakao API {r.status_code}: {r.text}")

    data = r.json()
    items = []
    for doc in data.get("documents", []):
        base = doc.get("road_address") or doc.get("address")
        if not base:
            continue
        name = base.get("address_name") or doc.get("address_name")
        l1 = base.get("region_1depth_name") or ""
        l2 = base.get("region_2depth_name") or ""
        l3 = base.get("region_3depth_name") or ""
        lng = float(base.get("x"))
        lat = float(base.get("y"))
        items.append({"name": name, "l1": l1, "l2": l2, "l3": l3, "lat": lat, "lng": lng})
    return items

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
            return redirect('food:splash')
    else:
        form = CustomLoginForm()
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('food:main')

# 내 활동
def _my_district(user) -> str | None:
    addr = getattr(user, "active_address", None)
    if addr and getattr(addr, "addr_level2", None):
        return addr.addr_level2
    return getattr(user, "addr_level2", None)

def _week_bounds_now():
    now = timezone.now()
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=7)
    return start, end

@login_required
def activity_log_view(request):
    user = request.user

    # ===== 전체 기준(주간 X) =====
    logs_all = (
        ActivityLog.objects
        .filter(user=user, shopping_list__is_done=True)
        .select_related('shopping_list__market')
        .order_by('-visited_at')
    )

    total_logs = logs_all.count()                                  # 전체 횟수
    total_steps = logs_all.aggregate(s=Sum('steps'))['s'] or 0      # 누적 걸음수(기록 합)
    total_points = logs_all.aggregate(s=Sum('point_earned'))['s'] or 0
    total_distance_km = total_points / 100.0                        # 100P = 1km
    co2_saved_kg = round(total_distance_km * 0.232, 2)

    # 목록(전체 로그)
    log_data = []
    for log in logs_all:
        sl = log.shopping_list
        market_name = sl.market.name if (sl and sl.market) else '미지정 마트'
        log_data.append({
            'visited_at': log.visited_at,
            'market_name': market_name,
            'shopping_list_id': sl.id if sl else None,
            'point_earned': log.point_earned,
            'steps': log.steps or 0,
        })

    # ===== 랭킹만 “이번 주 + 같은 구(district)” 기준 =====
    week_start, week_end = _week_bounds_now()
    district = _my_district(user)
    local_users = (
        CustomUser.objects.filter(addr_level2=district)
        if district else CustomUser.objects.all()
    )

    base_qs = ActivityLog.objects.filter(
        user__in=local_users,
        visited_at__gte=week_start,
        visited_at__lt=week_end,
    )

    # 내 주간 포인트
    my_week_points = (
        base_qs.filter(user=user)
        .aggregate(s=Sum('point_earned'))['s'] or 0
    )

    # 내 주간 랭킹: 나보다 점수 큰 사람 수 + 1 (0점이면 None)
    if my_week_points > 0:
        user_rank = (
            base_qs.values('user')
            .annotate(points=Sum('point_earned'))
            .filter(points__gt=my_week_points)
            .count()
        ) + 1
    else:
        user_rank = None

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'accounts/activity_log.html', {
        # 전체 기준 요약
        'total_logs': total_logs,
        'total_steps': total_steps,
        'co2_saved_kg': co2_saved_kg,

        # 랭킹(이번 주 + 같은 구)
        'user_rank': user_rank,

        # 목록(전체 로그)
        'log_data': log_data,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

_PERIODS = {
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "1y": timedelta(days=365),
    "all": None,
}

# 추정용 상수 (기록 없을 때만 폴백)
STEPS_PER_KM = 1300
KCAL_PER_KM = 50

# 세부 활동 내역
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

        # 목록에서도 요약 정보가 필요하면 함께 내려주기 (템플릿에서 쓰거나, 안 쓰면 무시해도 됨)
        log_data.append({
            "visited_at": log.visited_at,
            "market_name": market_name,
            "shopping_list_id": sl.id if sl else None,
            "point_earned": log.point_earned,
            "steps": log.steps,  # None 가능
            "travel_minutes": log.travel_minutes,  # None 가능
            "calories_kcal": log.calories_kcal,  # None 가능 (Decimal)
        })
    
    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, "accounts/activity_history.html", {
        "q": q,
        "period": period,
        "sort": sort,
        "log_data": log_data,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

@login_required
def activity_detail_ajax(request, shopping_list_id):
    """AJAX로 세부 활동 데이터 반환 (기록값 우선, 없으면 추정치 폴백)"""
    shopping_list = get_object_or_404(
        ShoppingList.objects.select_related('market'),
        id=shopping_list_id,
        user=request.user
    )

    ingredients = ShoppingListIngredient.objects.filter(
        shopping_list=shopping_list
    ).select_related('ingredient')

    log = ActivityLog.objects.filter(
        user=request.user,
        shopping_list=shopping_list
    ).first()

    # 기본값
    point_earned = 0
    distance_km = 0.0
    steps = None
    travel_minutes = None
    calories_kcal = None

    if log:
        point_earned = log.point_earned or 0
        visited_at = log.visited_at
        # 기록이 있으면 그대로 사용
        steps = log.steps
        travel_minutes = log.travel_minutes
        calories_kcal = float(log.calories_kcal) if log.calories_kcal is not None else None

    # 기록이 부족하면 포인트 기반 추정(1km = 100P 규칙)
    if point_earned and (steps is None or travel_minutes is None or calories_kcal is None):
        distance_km = point_earned / 100.0
        if steps is None:
            steps = int(round(distance_km * STEPS_PER_KM))
        if travel_minutes is None:
            # 대략 시속 4km 보행(= 분당 66~70m) 가정 → 1km ≈ 15분
            travel_minutes = int(round(distance_km * 15))
        if calories_kcal is None:
            calories_kcal = int(round(distance_km * KCAL_PER_KM))
    else:
        # 기록이 완전한 경우에도 distance_km 표시는 편의상 계산해서 내려줌
        distance_km = point_earned / 100.0 if point_earned else 0.0

    return JsonResponse({
        "market_name": shopping_list.market.name if shopping_list.market else "미지정",
        "created_at": shopping_list.created_at.strftime("%Y.%m.%d %H:%M"),
        "visited_at": visited_at.strftime("%Y.%m.%d %H:%M") if visited_at else None,
        "point_earned": point_earned,
        "distance_km": f"{distance_km:.2f}",
        "steps": steps or 0,
        "travel_minutes": travel_minutes or 0,
        "calories_kcal": calories_kcal or 0,
        "ingredients": [item.ingredient.name for item in ingredients]
    })

# 요리법 보관함
@login_required
def my_recipes(request):
    user = request.user

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

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'accounts/my_recipes.html', {
        'recipes': recipes,
        'q': q,
        'sort': sort,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

@login_required
def recipe_detail_ajax(request, recipe_id):
    """AJAX 요청 시 레시피 상세 데이터 반환"""
    recipe = get_object_or_404(SavedRecipe, id=recipe_id, user=request.user)
    return JsonResponse({
        'title': recipe.title,
        'created_at': recipe.created_at.strftime('%Y.%m.%d %H:%M'),
        'description': recipe.description,
    })


# -----주소 설정---------
@login_required
def address_settings(request):
    """페이지1: 주소 설정(대표 주소/최근 기록)"""
    user = request.user
    current = user.selected_address  # FK 대표 주소
    recents = user.addresses.order_by("-created_at")[:10]  # 최근 기록

    return render(request, "accounts/address_settings.html", {
        "current": current,
        "recents": recents,
    })


@login_required
def address_search(request):
    """페이지2: 주소 검색 + 결과 리스트"""
    q = (request.GET.get("q") or "").strip()
    results = []
    if q:
        try:
            results = _kakao_address_search(q, size=30)
        except Exception as e:
            messages.error(request, f"주소 검색 중 오류: {e}")

    return render(request, "accounts/address_search.html", {
        "q": q,
        "results": results,
    })


def _apply_selected_address(user, addr):
    """대표 주소 FK + 미러필드 동기화"""
    user.selected_address = addr
    user.address = addr.address
    user.addr_level1 = addr.addr_level1
    user.addr_level2 = addr.addr_level2
    user.addr_level3 = addr.addr_level3
    user.latitude = addr.latitude
    user.longitude = addr.longitude
    user.save(update_fields=[
        "selected_address", "address", "addr_level1", "addr_level2",
        "addr_level3", "latitude", "longitude"
    ])

@login_required
@require_POST
def address_save(request):
    """검색 결과에서 바로 저장 + 대표 지정"""
    user = request.user

    name   = (request.POST.get("name") or "").strip()
    l1     = (request.POST.get("l1") or "").strip()
    l2     = (request.POST.get("l2") or "").strip()
    l3     = (request.POST.get("l3") or "").strip()
    detail = (request.POST.get("detail") or "").strip()
    lat    = request.POST.get("lat")
    lng    = request.POST.get("lng")

    # 상세주소를 address 문자열에 합치기
    full_address = f"{name} {detail}".strip() if detail else name

    # 숫자 캐스팅 (안전 처리)
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        messages.error(request, "좌표값이 올바르지 않습니다.")
        return redirect("accounts:address_search")

    # 동일 주소 중복 방지: 좌표+문자열 기준으로 재사용
    addr, _created = Address.objects.get_or_create(
        user=user,
        address=full_address,
        addr_level1=l1,
        addr_level2=l2,
        addr_level3=l3,
        defaults={"latitude": lat_f, "longitude": lng_f},
    )

    # 좌표가 비어 있던 기존 레코드가 있을 경우 보정
    if addr.latitude is None or addr.longitude is None:
        addr.latitude = lat_f
        addr.longitude = lng_f
        addr.save(update_fields=["latitude", "longitude"])

    _apply_selected_address(user, addr)
    return redirect("accounts:address_settings")


@login_required
def address_select_primary(request, addr_id: int):
    """최근 기록에서 주소 클릭 → 대표 주소 변경"""
    addr = get_object_or_404(Address, id=addr_id, user=request.user)
    _mirror_user_address(request.user, addr)
    return redirect("accounts:address_settings")

@login_required
def address_pick_map(request):
    """
    페이지: 지도에서 위치 확인
    - 최초 중심은: (1) 사용자 미러필드(lat/lng) → (2) 서울시청 좌표 폴백
    - JS가 GPS 권한 허용 시 그 좌표로 재중심
    """
    user = request.user
    init_lat = user.latitude or 37.5665   # 서울시청 위도
    init_lng = user.longitude or 126.9780 # 서울시청 경도
    return render(request, "accounts/address_pick_map.html", {
        "init_lat": init_lat,
        "init_lng": init_lng,
        "kakao_js_key": getattr(settings, "KAKAO_JS_API_KEY", ""),
    })

@login_required
@require_POST
def address_save_from_map(request):
    name = request.POST.get("name")
    l1   = request.POST.get("l1")
    l2   = request.POST.get("l2")
    l3   = request.POST.get("l3") or ""
    lat  = float(request.POST.get("lat"))
    lng  = float(request.POST.get("lng"))
    detail = (request.POST.get("detail") or "").strip()
    full = name if not detail else f"{name} {detail}"

    addr, _ = Address.objects.get_or_create(
        user=request.user, address=full,
        defaults={"addr_level1": l1, "addr_level2": l2, "addr_level3": l3, "latitude": lat, "longitude": lng}
    )
    _mirror_user_address(request.user, addr)
    return redirect("accounts:address_settings")

@login_required
@require_POST
def address_delete(request, addr_id: int):
    user = request.user
    addr = get_object_or_404(Address, id=addr_id, user=user)

    with transaction.atomic():
        # 지우려는 주소가 대표 주소인 경우, FK와 미러 필드 모두 NULL 처리
        if user.selected_address_id == addr.id:
            user.selected_address = None
            user.address = None
            user.addr_level1 = None
            user.addr_level2 = None
            user.addr_level3 = None
            user.latitude = None
            user.longitude = None
            user.save(update_fields=[
                "selected_address", "address", "addr_level1", "addr_level2",
                "addr_level3", "latitude", "longitude"
            ])

        addr.delete()

    return redirect("accounts:address_settings")
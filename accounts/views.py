from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from .forms import CustomUserCreationForm, CustomLoginForm
from django.db.models import Count, Sum, F, Window
from django.db.models.functions import Rank
from market.models import *
from food.models import *
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from django.utils.http import urlencode
from django.contrib import messages
from django.conf import settings
from .models import CustomUser, Address
import requests



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


@login_required
def address_settings(request):
    """페이지1: 주소 설정(대표 주소/최근 기록)"""
    user = request.user
    current = user.selected_address  # FK 대표 주소
    recents = user.addresses.order_by("-created_at")[:5]  # 최근 기록

    return render(request, "accounts/address_settings.html", {
        "current": current,
        "recents": recents,
    })

# -----주소 설정---------
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


@login_required
def address_confirm(request):
    """
    페이지3:
    - GET: 검색결과에서 선택된 좌표/행정동 정보를 쿼리스트링으로 전달받아 상세주소 입력 폼 표시
    - POST: Address 생성(또는 재사용) + 대표주소/미러필드 동기화
    """
    user = request.user

    if request.method == "GET":
        # 검색 결과에서 넘어온 기본 정보
        name = request.GET.get("name")  # 전체 주소(도로명/지번)
        l1 = request.GET.get("l1")
        l2 = request.GET.get("l2")
        l3 = request.GET.get("l3")
        lat = request.GET.get("lat")
        lng = request.GET.get("lng")

        if not all([name, l1, l2, lat, lng]):
            messages.error(request, "주소 정보가 올바르지 않습니다. 다시 검색해 주세요.")
            return redirect("accounts:address_search")

        return render(request, "accounts/address_confirm.html", {
            "name": name,
            "l1": l1, "l2": l2, "l3": l3 or "",
            "lat": lat, "lng": lng,
            "kakao_js_key": getattr(settings, "KAKAO_JS_API_KEY", ""),
        })

    # POST 저장
    name = request.POST.get("name")
    l1 = request.POST.get("l1")
    l2 = request.POST.get("l2")
    l3 = request.POST.get("l3") or ""
    lat = float(request.POST.get("lat"))
    lng = float(request.POST.get("lng"))
    detail = (request.POST.get("detail") or "").strip()

    full = name if not detail else f"{name} {detail}"

    # 같은 전체주소가 있으면 재사용(선택), 없으면 생성
    addr, created = Address.objects.get_or_create(
        user=user,
        address=full,
        defaults={"addr_level1": l1, "addr_level2": l2, "addr_level3": l3, "latitude": lat, "longitude": lng},
    )
    if not created:
        # 좌표/행정동 업데이트(선택)
        changed = False
        if addr.addr_level1 != l1 or addr.addr_level2 != l2 or addr.addr_level3 != l3:
            addr.addr_level1, addr.addr_level2, addr.addr_level3 = l1, l2, l3
            changed = True
        if addr.latitude != lat or addr.longitude != lng:
            addr.latitude, addr.longitude = lat, lng
            changed = True
        if changed:
            addr.save(update_fields=["addr_level1", "addr_level2", "addr_level3", "latitude", "longitude"])

    _mirror_user_address(user, addr)
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
    """최근 기록의 주소 삭제. 대표 주소는 기본적으로 삭제 금지."""
    addr = get_object_or_404(Address, id=addr_id, user=request.user)

    # 대표 주소 삭제 방지
    if request.user.selected_address_id == addr.id:
        messages.warning(request, "현재 대표 주소는 삭제할 수 없습니다. 먼저 다른 주소를 대표로 선택하세요.")
        return redirect("accounts:address_settings")

    addr.delete()
    return redirect("accounts:address_settings")
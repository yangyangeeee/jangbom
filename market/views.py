from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages  
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .services.route_service import route_user_to_market
from .integrations.tmap_client import get_pedestrian_route
from food.views import get_user_total_point, cart_items_count
from django.db.models import Sum, Value, IntegerField
from django.db.models.functions import Coalesce
from market.models import *
from point.models import UserPoint
from math import radians, cos, sin, sqrt, atan2
import requests, datetime, json, math, random
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse, HttpResponseBadRequest
from django.core.cache import cache
from .ai import *
from decimal import Decimal


# ---------- 유틸 함수 ---------- (추후 util.py로 나눌 예정)

# 거리 계산 (Haversine 공식)
def get_distance_km(lat1, lng1, lat2, lng2):
    R = 6371  # km
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2)**2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2)**2
    )
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# Kakao 경로 API
def get_directions_api(start_x, start_y, end_x, end_y):
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}",
    }
    params = {
        "origin": f"{start_x},{start_y}",
        "destination": f"{end_x},{end_y}",
        "priority": "RECOMMEND",
    }

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print("Kakao API 실패:", response.status_code, response.text)
        return None

# 경로 정보 (좌표 리스트)
def get_walking_directions(start_lat, start_lng, end_lat, end_lng):
    result = get_directions_api(start_lng, start_lat, end_lng, end_lat)
    if not result:
        return []

    try:
        roads = result['routes'][0]['sections'][0]['roads']
        polyline = []
        for road in roads:
            vertexes = road['vertexes']
            for i in range(0, len(vertexes), 2):
                lng = vertexes[i]
                lat = vertexes[i + 1]
                polyline.append([lat, lng])
        return polyline
    except Exception as e:
        print("경로 추출 오류:", e)
        return []

# 유저와 마켓 간 거리/시간/포인트 (TMAP 보행자 기준)
def get_travel_info(user_lat, user_lng, market_lat, market_lng):
    try:
        route = get_pedestrian_route(user_lat, user_lng, market_lat, market_lng)
        distance_m = int(route.get("distance_m", 0))
        duration_s = int(route.get("duration_s", 0))
    except Exception:
        distance_m, duration_s = 0, 0

    # TMAP이 실패하거나 0을 주면 폴백: 직선거리 + 보행 80m/분
    if distance_m <= 0:
        distance_km = get_distance_km(user_lat, user_lng, market_lat, market_lng)
        distance_m = int(round(distance_km * 1000))
    if duration_s <= 0:
        duration_s = max(60, int(distance_m / 80 * 60))  # 80 m/min → sec

    expected_time = math.ceil(duration_s / 60)          # 분
    point_earned  = round((distance_m / 1000) * 100)    # 기존 규칙 유지: km * 100

    return expected_time, distance_m, point_earned

# 유저의 is_done=False인 가장 최근 장바구니 재료 목록
def get_latest_shopping_ingredients(user):
    shopping_lists = user.shoppinglist_set.all().filter(is_done=False).order_by('-created_at')
    if shopping_lists.exists():
        latest = shopping_lists.first()
        return set(latest.shoppinglistingredient_set.values_list('ingredient__name', flat=True))
    return set()

# 마켓 재고와 유저 재료 비교
def match_ingredients(market, shopping_ingredients_set):
    market_stocks = (MarketStock.objects.filter(market=market).select_related('ingredient'))
    stocked_names = {s.ingredient.name for s in market_stocks}

    ings = Ingredient.objects.filter(name__in=shopping_ingredients_set)
    img_map = {i.name: (i.image.url if i.image else None) for i in ings}

    matched, unmatched = [], []
    for name in sorted(shopping_ingredients_set):
        item = {"name": name, "image": img_map.get(name)}
        if name in stocked_names:
            matched.append(item)
        else:
            unmatched.append(item)

    return matched, unmatched


def estimate_steps(distance_m: int, step_length_m: float = 0.75) -> int:
    """거리(m)와 보폭(m)으로 걸음 수 추정."""
    if step_length_m <= 0:
        step_length_m = 0.75
    return int(round(distance_m / step_length_m))

def estimate_calories_kcal(user, distance_m: int, duration_min: int, steps: int) -> float:
    """
    칼로리(kcal) 추정.
    1) user에 weight_kg가 있으면 MET 기반
    2) 없으면 걸음당 0.045kcal 기본값
    """
    # 2) 기본: 걸음당 kcal
    kcal_by_steps = steps * 0.045

    # 1) 선택: 체중 기반(MET) — user에 weight_kg가 있을 때만
    weight_kg = getattr(user, "weight_kg", None)
    if weight_kg and duration_min > 0:
        hours = duration_min / 60.0
        kmh = (distance_m / 1000.0) / hours if hours > 0 else 0.0
        # 속도별 대략적 MET (평지 보행)
        if kmh < 3.0:
            met = 2.3
        elif kmh < 4.0:
            met = 3.3
        elif kmh < 5.0:
            met = 3.8
        elif kmh < 6.0:
            met = 4.3
        else:
            met = 5.0
        kcal_by_met = met * weight_kg * hours
        # 두 방식 중 더 보수적인(작은) 값을 채택하거나, MET 우선으로 바꿔도 OK
        return round(kcal_by_met, 2)

    return round(kcal_by_steps, 2)

# ---- 영업시간 유틸 ----
WEEKDAYS_KO = ['월','화','수','목','금','토','일']

def is_open_now(open_days: str, open_time, close_time, when=None, *, treat_equal_as_24h: bool = True) -> bool:
    """
    - open_days: '월,화,수' 처럼 쉼표로 구분된 요일 문자열
    - open_time, close_time: datetime.time
    - when: 기준 시각(datetime); None이면 timezone.now()
    - treat_equal_as_24h: open_time == close_time 을 24시간 영업으로 볼지 여부
    """
    if not (open_days and open_time and close_time):
        return False

    now = timezone.localtime(when or timezone.now())
    wd = WEEKDAYS_KO[now.weekday()]
    days = {s.strip() for s in open_days.split(',') if s.strip()}
    if wd not in days:
        return False

    t = now.time()
    ot, ct = open_time, close_time

    # 24시간 영업 처리(옵션)
    if treat_equal_as_24h and ot == ct:
        return True

    # 같은 날에 닫힘 (예: 09:00~18:00)
    if ot <= ct:
        return ot <= t <= ct

    # 자정 넘김 (예: 18:00~02:00)
    return t >= ot or t <= ct

def minutes_until_close(open_time, close_time, when=None) -> int:
    """현재 기준 마감까지 남은 분(영업 중이 아닐 땐 0). 자정 넘김 포함."""
    if not (open_time and close_time):
        return 0
    now_dt = timezone.localtime(when or timezone.now())
    t = now_dt.time()
    ot, ct = open_time, close_time

    # 같은 날에 닫힘
    if ot <= ct:
        if not (ot <= t <= ct):
            return 0
        end = datetime.datetime.combine(now_dt.date(), ct, tzinfo=now_dt.tzinfo)
        return max(0, int((end - now_dt).total_seconds() // 60))

    # 자정 넘김
    if not (t >= ot or t <= ct):
        return 0
    end_date = now_dt.date() if t <= ct else (now_dt.date() + datetime.timedelta(days=1))
    end = datetime.datetime.combine(end_date, ct, tzinfo=now_dt.tzinfo)
    return max(0, int((end - now_dt).total_seconds() // 60))

def reset_cart_session(request):
    for k in [
        'optional_selected', 'extra_ingredients', 'search_selected',
        'basic', 'optional', 'recipe_input', 'latest_recipe'
    ]:
        request.session.pop(k, None)
    request.session['active_sl_id'] = None

# ---------- 뷰 함수 ----------
@login_required
def edit_market_filter_recipe(request):
    filt, _ = MarketFilterSetting.objects.get_or_create(user=request.user)

    if request.method == "POST":
        dp = request.POST.get("distance_preference")
        tp = request.POST.get("type_preference")

        if not dp or not tp:
            messages.error(request, "거리와 상점 종류를 각각 하나씩 선택해 주세요.")
            return redirect("market:edit_market_filter_recipe")

        valid_dp = {v for v, _ in MarketFilterSetting.DistancePref.choices}
        valid_tp = {v for v, _ in MarketFilterSetting.TypePref.choices}

        changed = False
        if dp in valid_dp and dp != filt.distance_preference:
            filt.distance_preference = dp
            changed = True
        if tp in valid_tp and tp != filt.type_preference:
            filt.type_preference = tp
            changed = True

        if changed:
            filt.save()

        return redirect("food:confirm_shopping_list")

    return render(request, "market/filter_form_recipe.html", {
        "filter": filt,
        "distance_choices": MarketFilterSetting.DistancePref.choices,
        "type_choices": MarketFilterSetting.TypePref.choices,
    })


@login_required
def edit_market_filter_ingredient(request):
    filt, _ = MarketFilterSetting.objects.get_or_create(user=request.user)

    if request.method == "POST":
        dp = request.POST.get("distance_preference")
        tp = request.POST.get("type_preference")

        if not dp or not tp:
            messages.error(request, "거리와 상점 종류를 각각 하나씩 선택해 주세요.")
            return redirect("market:edit_market_filter_ingredient")

        valid_dp = {v for v, _ in MarketFilterSetting.DistancePref.choices}
        valid_tp = {v for v, _ in MarketFilterSetting.TypePref.choices}

        changed = False
        if dp in valid_dp and dp != filt.distance_preference:
            filt.distance_preference = dp
            changed = True
        if tp in valid_tp and tp != filt.type_preference:
            filt.type_preference = tp
            changed = True

        if changed:
            filt.save()

        return redirect("food:ingredient_result")

    return render(request, "market/filter_form_ingredient.html", {
        "filter": filt,
        "distance_choices": MarketFilterSetting.DistancePref.choices,
        "type_choices": MarketFilterSetting.TypePref.choices,
    })


@csrf_exempt
@login_required
def nearest_market_view(request):
    user = request.user
    user_lat, user_lng = user.latitude, user.longitude

    filt, _ = MarketFilterSetting.objects.get_or_create(user=user)
    min_m, max_m, min_strict = filt.distance_range_m

    def in_range(d):
        return (d > min_m if min_strict else d >= min_m) and d <= max_m

    # 내 장바구니 재료(set) — 교집합 개수 계산용
    shopping_ingredients_set = get_latest_shopping_ingredients(user)  # set of names

    # 후보 수집 (영업중 + 거리범위)
    candidates = []
    for m in Market.objects.all():
        if m.latitude is None or m.longitude is None:
            continue
        d_m = int(round(get_distance_km(user_lat, user_lng, m.latitude, m.longitude) * 1000))
        if not in_range(d_m):
            continue
        if not is_open_now(m.open_days, m.open_time, m.close_time):
            continue

        # 매칭 재료 수
        if shopping_ingredients_set:
            match_count = MarketStock.objects.filter(
                market=m, ingredient__name__in=shopping_ingredients_set
            ).count()
        else:
            match_count = 0

        candidates.append((m, d_m, match_count))   # (마켓, 거리(m), 재료일치수)

    if not candidates:
        return render(request, 'market/nearest_market.html', {
            "market": None, "distance_m": 0, "expected_time": -1,
            "closing_in_minutes": 0, "point_earned": 0,
        })

    # --- 정렬: 타입 우선 → (마트 우선일 때) 재료일치수 ↓ → 거리 ↑ ---
    type_pref = (filt.type_preference or "none")  # 'mart' | 'trad' | 'none'

    def type_priority(market_type: str) -> int:
        mt = (market_type or "").lower()
        if type_pref == "mart":
            return 0 if mt == "mart" else 1
        if type_pref == "trad":
            return 0 if mt == "trad" else 1
        return 0

    # === 폴백: 마트 우선인데, 범위 내 모든 'mart'가 매칭 재료 수 0이면 → 전통시장 중 가장 가까운 곳 ===
    selected_market = None
    if type_pref == "mart":
        marts = [t for t in candidates if (t[0].market_type or "").lower() == "mart"]
        if marts and all(t[2] == 0 for t in marts):
            trads = [t for t in candidates if (t[0].market_type or "").lower() == "trad"]
            if trads:
                trads.sort(key=lambda x: x[1])  # 거리 오름차순
                selected_market = trads[0][0]

    # 기본 정렬(선택된 폴백이 없으면 기존 규칙대로)
    if selected_market is None:
        def sort_key(tup):
            m, dist, match_cnt = tup
            if type_pref == "mart":
                return (type_priority(m.market_type), -match_cnt, dist)
            else:
                return (type_priority(m.market_type), dist)
        candidates.sort(key=sort_key)
        selected_market = candidates[0][0]

    nearest = selected_market

    # 거리/시간/포인트
    expected_time, distance_m, point_earned = get_travel_info(
        user_lat, user_lng, nearest.latitude, nearest.longitude
    )
    closing_in_minutes = minutes_until_close(nearest.open_time, nearest.close_time)

    # 장바구니에 마켓 연결 (비어있을 때만)
    shopping_list = user.shoppinglist_set.order_by('-created_at').first()
    if shopping_list and shopping_list.market_id is None:
        shopping_list.market = nearest
        shopping_list.save(update_fields=['market'])

    # 선택된 마켓 기준 재료 비교
    matched_ingredients, unmatched_ingredients = match_ingredients(nearest, shopping_ingredients_set)

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'market/nearest_market.html', {
        "market": nearest,
        "distance_m": distance_m,
        "expected_time": expected_time,
        "closing_in_minutes": closing_in_minutes,
        "point_earned": point_earned,
        "matched_ingredients": matched_ingredients,
        "unmatched_ingredients": unmatched_ingredients,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

@login_required
def map_direction_view(request):
    user = request.user
    market_id = request.GET.get('market_id')
    market = get_object_or_404(Market, id=market_id)

    # 1) TMAP 보행자 경로 사용 (폴리라인/거리/시간 모두 보행자 기준)
    route = route_user_to_market(user, market)  # {'path': [{lat,lng},...], 'distance_m': int, 'duration_s': int}
    polyline = route["path"]

    expected_time, distance_m, point_earned = get_travel_info(user.latitude, user.longitude, market.latitude, market.longitude)

    # 3) 유저의 최신 장바구니 가져오기
    shopping_list = user.shoppinglist_set.order_by('-created_at').first()
    if shopping_list and getattr(shopping_list, "market", None) is None:
        shopping_list.market = market
        shopping_list.save()

    # 4) 재료 비교
    shopping_ingredients_set = get_latest_shopping_ingredients(user)
    matched_ingredients, unmatched_ingredients = match_ingredients(market, shopping_ingredients_set)

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    # 5) 템플릿 렌더링
    context = {
        'market': market,
        'shopping_list': shopping_list,
        'expected_time': expected_time,      
        'distance_m': distance_m,            
        'point_earned': point_earned,
        'kakao_key': settings.KAKAO_JS_API_KEY,
        'polyline': json.dumps(polyline),  
        'matched_ingredients': matched_ingredients,
        'unmatched_ingredients': unmatched_ingredients,
        "cart_items_count" : items_count,
        "total_point":total_point,
    }
    return render(request, 'market/map_direction.html', context)


@login_required
def market_arrival_view(request, shoppinglist_id):
    user = request.user
    shopping_list = get_object_or_404(ShoppingList, id=shoppinglist_id, user=user)
    market = shopping_list.market

    expected_time, distance_m, point_earned = get_travel_info(
        user.latitude, user.longitude, market.latitude, market.longitude
    )

    shopping_ingredients_set = get_latest_shopping_ingredients(user)
    matched_ingredients, unmatched_ingredients = match_ingredients(market, shopping_ingredients_set)

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    # AI 칭찬 문구 2줄 생성 (에러 시 기본 문구)
    try:
        praise_lines = generate_arrival_praises(market.name, getattr(market, "dong", None), distance_m)
        if len(praise_lines) < 2:
            raise ValueError("not enough lines")
    except Exception:
        praise_lines = ["지역 경제를 살린 쇼핑", "탄소 없는 도보 쇼핑"]

    context = {
        'user': user,
        'market': market,
        'point_earned': point_earned,
        'distance_m': distance_m,
        'expected_time': expected_time,
        'shopping_list': shopping_list,
        'matched_ingredients': matched_ingredients,
        'unmatched_ingredients': unmatched_ingredients,
        "cart_items_count" : items_count,
        'total_point': total_point,
        'praise_lines': praise_lines,        
    }
    return render(request, 'market/market_arrival.html', context)

@login_required
@require_POST
def save_selected_ingredients_view(request, shoppinglist_id):
    sl = get_object_or_404(ShoppingList, id=shoppinglist_id, user=request.user)
    selected = set(request.POST.getlist("items"))

    current = set(
        ShoppingListIngredient.objects
        .filter(shopping_list=sl)
        .values_list("ingredient__name", flat=True)
    )

    # 제거
    ShoppingListIngredient.objects.filter(shopping_list=sl)\
        .exclude(ingredient__name__in=selected).delete()

    # 추가
    to_add = selected - current
    if to_add:
        ing_map = {i.name: i for i in Ingredient.objects.filter(name__in=to_add)}
        ShoppingListIngredient.objects.bulk_create(
            [ShoppingListIngredient(shopping_list=sl, ingredient=ing_map[n]) for n in to_add if n in ing_map]
        )

    # 저장 후 이동
    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    # 폴백: 도착 페이지로 유지
    return redirect("market:market_arrival", shoppinglist_id=sl.id)

@require_GET
@login_required
def ingredient_tip_page(request):
    name = (request.GET.get("name") or "").strip()
    if not name:
        return HttpResponseBadRequest("name required")
    return render(request, "market/ingredient_tip.html", {"name": name})

@require_GET
@login_required
def ingredient_tip_api(request):
    name = (request.GET.get("name") or "").strip()
    q    = (request.GET.get("q") or "").strip()
    if not name:
        return HttpResponseBadRequest("name required")

    if q:  # 후속 질문은 캐시 건너뛰고 즉시 생성
        tip = generate_tip_text(name, followup=q)
        return HttpResponse(tip, content_type="text/plain; charset=utf-8")

    key = f"tip:{name.lower()}"
    tip = cache.get(key)
    if tip is None:
        tip = generate_tip_text(name)
        cache.set(key, tip, 60 * 60 * 24)

    return HttpResponse(tip, content_type="text/plain; charset=utf-8")


@csrf_exempt
@login_required
def verify_secret_code(request):
    if request.method == "POST":
        input_code = request.POST.get("password")
        market_id = request.POST.get("market_id")
        point_earned = request.POST.get("point_earned")
        shoppinglist_id = request.POST.get("shoppinglist_id")

        market = Market.objects.filter(id=market_id).first()
        if market and market.secret_code == input_code:
            return render(request, 'market/secret_input.html', {
                'market': market,
                'shoppinglist_id': shoppinglist_id, 
                'point_earned': point_earned,
                'message': "구매 인증 성공"
            })
        else:
            return render(request, 'market/secret_input.html', {
                'market': market,
                'shoppinglist_id': shoppinglist_id, 
                'point_earned': point_earned,
                'message': "올바르지 않은 비밀번호입니다"
            })

    return render(request, 'market/secret_input.html', {
        'message': "잘못된 요청입니다"
    })


@login_required
def secret_input_view(request, market_id):
    market = get_object_or_404(Market, id=market_id)
    point_earned = request.GET.get("point_earned")
    shoppinglist_id = request.GET.get("shoppinglist_id")

    return render(request, 'market/secret_input.html', {
        'market': market,
        'point_earned': point_earned,
        'shoppinglist_id': shoppinglist_id,
    })

@login_required
def shopping_success_view(request, shoppinglist_id):
    user = request.user
    shopping_list = get_object_or_404(ShoppingList, id=shoppinglist_id, user=user)
    market = shopping_list.market

    # --- 주변 장소: 영업중만 필터 + 랜덤 3개 ---
    places_qs = NearbyPlace.objects.filter(market=market)
    open_places = []
    for p in places_qs:
        if is_open_now(p.open_days, p.open_time, p.close_time):
            # 템플릿에서 편하게 쓰도록 속성 부여
            p.is_open = True
            p.closing_in_minutes = minutes_until_close(p.open_time, p.close_time)
            open_places.append(p)
    random.shuffle(open_places)
    nearby_sample = open_places[:3]

    total_steps = ActivityLog.objects.filter(user=user).aggregate(total_steps=Coalesce(Sum('steps'), Value(0), output_field=IntegerField()))['total_steps']

    # --- 이미 적립된 장보기면 포인트 0으로 리턴 ---
    if ActivityLog.objects.filter(user=user, shopping_list=shopping_list).exists():
        user_point, _ = UserPoint.objects.get_or_create(user=user)
        return render(request, "market/shopping_success.html", {
            "market": market,
            "point_earned": 0,
            "total_point": user_point.total_point,
            "message": "이미 포인트가 지급된 장보기입니다",
            "nearby_places": nearby_sample,
            "total_steps": total_steps,
        })

    # --- 거리/시간/포인트 계산 (TMAP 보행자 기준 + 폴백) ---
    expected_time_min, distance_m, point_earned = get_travel_info(
        user.latitude, user.longitude, market.latitude, market.longitude
    )

    # --- 걸음/칼로리 ---
    steps = estimate_steps(distance_m)
    calories = estimate_calories_kcal(user, distance_m, expected_time_min, steps)

    # --- 쇼핑리스트 완료 표시 ---
    shopping_list.is_done = True
    shopping_list.save(update_fields=["is_done"])

    # --- 포인트 적립 ---
    user_point, _ = UserPoint.objects.get_or_create(user=user)
    user_point.total_point += point_earned
    user_point.save(update_fields=["total_point"])

    # --- 활동 로그 ---
    created_log = ActivityLog.objects.create(
        user=user,
        shopping_list=shopping_list,
        point_earned=point_earned,
        visited_at=timezone.now(),
        steps=steps,
        travel_minutes=expected_time_min,
        calories_kcal=Decimal(str(calories)),
    )

    # --- 장바구니 세션 초기화(완료 후 비우기) ---
    reset_cart_session(request)

    return render(request, "market/shopping_success.html", {
        "market": market,
        "point_earned": point_earned,
        "total_point": user_point.total_point,
        "nearby_places": nearby_sample,
        "total_steps": total_steps,
    })

@login_required
@require_GET
def nearby_places_random_api(request, market_id: int):
    market = get_object_or_404(Market, id=market_id)
    items = []
    for p in NearbyPlace.objects.filter(market=market):
        if is_open_now(p.open_days, p.open_time, p.close_time):
            items.append({
                "name": p.name,
                "category": p.category,
                "info": p.info,
                "distance_m": p.distance_m,
                "image_url": (p.image.url if p.image else ""),
                "link_url": p.link_url or "",
                "closing_in_minutes": minutes_until_close(p.open_time, p.close_time),
            })
    random.shuffle(items)
    return JsonResponse({"ok": True, "items": items[:3]})
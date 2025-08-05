from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from market.models import *
from point.models import UserPoint
from math import radians, cos, sin, sqrt, atan2
import requests, datetime, json



# ---------- 유틸 함수 ---------- (추후 util.py로 나눌 예정)

# 거리 계산 (Haversine 공식)
def get_distance_km(lat1, lng1, lat2, lng2):
    R = 6371  # 지구 반지름 (km)
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# Kakao 도보 소요 시간
def get_travel_time(start_lat, start_lng, end_lat, end_lng):
    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_REST_API_KEY}"
    }
    params = {
        "origin": f"{start_lng},{start_lat}",
        "destination": f"{end_lng},{end_lat}",
        "priority": "TIME"
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()

        if "routes" in data and data["routes"]:
            seconds = data["routes"][0]["summary"]["duration"]
            return int(seconds / 60)
        else:
            print("Kakao 응답 이상:", data)
            return -1
    except Exception as e:
        print("Kakao 요청 실패:", str(e))
        return -1

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

# 유저와 마켓 간 거리/시간/포인트 계산
def get_travel_info(user_lat, user_lng, market_lat, market_lng):
    distance_km = get_distance_km(user_lat, user_lng, market_lat, market_lng)
    distance_m = int(distance_km * 1000)
    expected_time = get_travel_time(user_lat, user_lng, market_lat, market_lng)
    point_earned = round(distance_km * 100)
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
    market_stocks = MarketStock.objects.filter(market=market).select_related('ingredient')
    ingredient_dict = {stock.ingredient.name: stock.ingredient for stock in market_stocks}

    matched = []
    unmatched = []

    for name in shopping_ingredients_set:
        if name in ingredient_dict:
            ingredient = ingredient_dict[name]
            matched.append({
                'name': ingredient.name,
                'image': ingredient.image.url if ingredient.image else None
            })
        else:
            unmatched.append(name)

    return matched, sorted(unmatched)


# ---------- 뷰 함수 ----------

@csrf_exempt
@login_required
def nearest_market_view(request):
    user = request.user
    user_lat = user.latitude
    user_lng = user.longitude

    markets = Market.objects.all()

    # 가장 가까운 마켓 찾기
    nearest, nearest_distance = min(
        [(m, get_distance_km(user_lat, user_lng, m.latitude, m.longitude)) for m in markets],
        key=lambda x: x[1]
    )

    # 거리/시간/포인트
    expected_time, distance_m, point_earned = get_travel_info(
        user_lat, user_lng,
        nearest.latitude, nearest.longitude
    )

    # 마감까지 남은 시간 계산
    now = datetime.datetime.now().time()
    open_time = nearest.open_time
    close_time = nearest.close_time

    if open_time < close_time:
        if open_time <= now <= close_time:
            closing_in_minutes = (
                datetime.datetime.combine(datetime.date.today(), close_time) -
                datetime.datetime.combine(datetime.date.today(), now)
            ).seconds // 60
        else:
            closing_in_minutes = 0
    else:
        if now >= open_time or now <= close_time:
            today = datetime.date.today()
            now_time = datetime.datetime.combine(today, now)
            end_time = datetime.datetime.combine(
                today + datetime.timedelta(days=1) if now <= close_time else today,
                close_time
            )
            closing_in_minutes = (end_time - now_time).seconds // 60
        else:
            closing_in_minutes = 0

    # 전통시장 가게 정보
    store_names = []
    store_count = 0
    if nearest.market_type == '전통시장':
        stores_qs = nearest.stores.all()
        store_names = list(stores_qs.values_list('name', flat=True))
        store_count = stores_qs.count()

    return render(request, 'market/nearest_market.html', {
        "market": nearest,
        "distance_m": distance_m,
        "travel_time_min": expected_time,
        "closing_in_minutes": closing_in_minutes,
        "point_earned": point_earned,
        "store_names": store_names,
        "store_count": store_count,
    })


@login_required
def map_direction_view(request):
    user = request.user
    market_id = request.GET.get('market_id')
    market = get_object_or_404(Market, id=market_id)

    # 1. 경로 정보
    polyline = get_walking_directions(user.latitude, user.longitude, market.latitude, market.longitude)

    # 2. 거리/시간/포인트
    expected_time, distance_m, point_earned = get_travel_info(
        user.latitude, user.longitude,
        market.latitude, market.longitude
    )

    # 3. 유저의 최신 장바구니 가져오기
    shopping_list = user.shoppinglist_set.order_by('-created_at').first()

    # 3-1. 장바구니가 있고, market이 지정되지 않았다면 → 현재 마켓으로 연결
    if shopping_list and shopping_list.market is None:
        shopping_list.market = market
        shopping_list.save()

    # 4. 재료 비교
    shopping_ingredients_set = get_latest_shopping_ingredients(user)
    matched_ingredients, unmatched_ingredients = match_ingredients(market, shopping_ingredients_set)

    # 5. 템플릿 렌더링
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
    }

    return render(request, 'market/map_direction.html', context)


@login_required
def market_arrival_view(request, shoppinglist_id):
    user = request.user
    shopping_list = get_object_or_404(ShoppingList, id=shoppinglist_id, user=user)
    market = shopping_list.market

    _, _, point_earned = get_travel_info(
        user.latitude, user.longitude,
        market.latitude, market.longitude
    )

    context = {
        'market': market,
        'point_earned': point_earned,
        'shopping_list': shopping_list,
    }

    return render(request, 'market/market_arrival.html', context)


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
                'message': "인증 완료!"
            })
        else:
            return render(request, 'market/secret_input.html', {
                'market': market,
                'shoppinglist_id': shoppinglist_id, 
                'point_earned': point_earned,
                'message': "올바르지 않은 비밀번호입니다."
            })

    return render(request, 'market/secret_input.html', {
        'message': "잘못된 요청입니다."
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

    # 중복 적립 방지: 이미 활동 기록이 있으면 포인트 다시 지급하지 않음
    if ActivityLog.objects.filter(user=user, shopping_list=shopping_list).exists():
        user_point, _ = UserPoint.objects.get_or_create(user=user)
        return render(request, "market/shopping_success.html", {
            "point_earned": 0,
            "total_point": user_point.total_point,
            "message": "이미 포인트가 지급된 장보기입니다.",
        })

    # 거리 기반으로 포인트 계산
    _, _, point_earned = get_travel_info(
        user.latitude, user.longitude,
        market.latitude, market.longitude
    )

    # 장보기를 완료로 표시
    shopping_list.is_done = True
    shopping_list.save()

    # 유저 총 포인트 업데이트
    user_point, _ = UserPoint.objects.get_or_create(user=user)
    user_point.total_point += point_earned
    user_point.save()

    # 활동 로그 기록
    ActivityLog.objects.create(
        user=user,
        shopping_list=shopping_list,
        point_earned=point_earned,
        visited_at=timezone.now()
    )

    return render(request, "market/shopping_success.html", {
        "point_earned": point_earned,
        "total_point": user_point.total_point,
        "message": "포인트가 적립되었습니다!",
    })
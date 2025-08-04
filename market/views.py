from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from market.models import *
from math import radians, cos, sin, sqrt, atan2
import requests, datetime, json


# 거리 계산 (Haversine 공식)
def get_distance_km(lat1, lng1, lat2, lng2):
    R = 6371  # 지구 반지름 (km)
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# Kakao API 도보 소요 시간 계산
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

@csrf_exempt
@login_required
def nearest_market_view(request):
    user = request.user
    user_lat = user.latitude
    user_lng = user.longitude

    markets = Market.objects.all()

    # 가장 가까운 마켓 계산
    nearest, nearest_distance = min(
        [(m, get_distance_km(user_lat, user_lng, m.latitude, m.longitude)) for m in markets],
        key=lambda x: x[1]
    )

    # 소요 시간
    minutes = get_travel_time(user_lat, user_lng, nearest.latitude, nearest.longitude)
    if minutes == -1:
        minutes = "도보 시간 계산 실패"

    # 마감 시간 계산
    now = datetime.datetime.now().time()
    open_time = nearest.open_time
    close_time = nearest.close_time

    if open_time < close_time:
        # 일반적인 경우
        if open_time <= now <= close_time:
            closing_in_minutes = (
                datetime.datetime.combine(datetime.date.today(), close_time) -
                datetime.datetime.combine(datetime.date.today(), now)
            ).seconds // 60
        else:
            closing_in_minutes = 0
    else:
        # 자정을 넘기는 경우
        if now >= open_time or now <= close_time:
            today = datetime.date.today()
            if now <= close_time:
                end_time = datetime.datetime.combine(today + datetime.timedelta(days=1), close_time)
            else:
                end_time = datetime.datetime.combine(today, close_time)
            now_time = datetime.datetime.combine(today, now)
            closing_in_minutes = (end_time - now_time).seconds // 60
        else:
            closing_in_minutes = 0

    # 포인트 계산 (거리 * 100)
    point_earned = round(nearest_distance * 100)

    # 전통시장이라면 가게 리스트 추출
    store_names = []
    if nearest.market_type == '전통시장':
        store_names = nearest.stores.values_list('name', flat=True)

    # 전통시장이면 가게 목록과 개수
    store_names = []
    store_count = 0
    if nearest.market_type == '전통시장':
        stores_qs = nearest.stores.all()
        store_names = list(stores_qs.values_list('name', flat=True))
        store_count = stores_qs.count()

    return render(request, 'market/nearest_market.html', {
        "market": nearest,
        "distance_m": int(nearest_distance * 1000),
        "travel_time_min": minutes,
        "closing_in_minutes": closing_in_minutes,
        "point_earned": point_earned,
        "store_names": store_names,
        "store_count": store_count,
    })



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
                lat = vertexes[i+1]
                polyline.append([lat, lng])
        return polyline
    except Exception as e:
        print("경로 추출 오류:", e)
        return []

@login_required
def map_direction_view(request):
    user = request.user
    market_id = request.GET.get('market_id')
    market = get_object_or_404(Market, id=market_id)

    # 1. 경로 정보
    polyline = get_walking_directions(
        user.latitude, user.longitude,
        market.latitude, market.longitude
    )

    # 2. 소요 시간 및 포인트
    expected_time = get_travel_time(user.latitude, user.longitude, market.latitude, market.longitude)
    distance_km = get_distance_km(user.latitude, user.longitude, market.latitude, market.longitude)
    point_earned = round(distance_km * 100)

    # 3. 유저가 선택한 재료
    shopping_ingredients = []
    shopping_lists = user.shoppinglist_set.all().order_by('-created_at')
    if shopping_lists.exists():
        latest = shopping_lists.first()
        shopping_ingredients = list(
            latest.shoppinglistingredient_set.values_list('ingredient__name', flat=True)
        )

    shopping_ingredients_set = set(shopping_ingredients)

    # 4. 마트가 보유한 재료 → 이름: Ingredient 객체 딕셔너리로 만들기
    market_stocks = MarketStock.objects.filter(market=market).select_related('ingredient')
    ingredient_dict = {
        stock.ingredient.name: stock.ingredient for stock in market_stocks
    }

    # 5. matched + unmatched 분리
    matched_ingredients = []
    unmatched_ingredients = []

    for name in shopping_ingredients_set:
        if name in ingredient_dict:
            ingredient_obj = ingredient_dict[name]
            matched_ingredients.append({
                'name': ingredient_obj.name,
                'image': ingredient_obj.image.url if ingredient_obj.image else None
            })
        else:
            unmatched_ingredients.append(name)

    context = {
        'market': market,
        'expected_time': expected_time,
        'point_earned': point_earned,
        'kakao_key': settings.KAKAO_JS_API_KEY,
        'polyline': json.dumps(polyline),
        'matched_ingredients': matched_ingredients,
        'unmatched_ingredients': sorted(unmatched_ingredients),
    }

    return render(request, 'market/map_direction.html', context)
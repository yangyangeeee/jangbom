from django.shortcuts import render, redirect, get_object_or_404
from .ai import *
from .models import *
from market.models import ShoppingList, ShoppingListIngredient
from point.models import UserPoint
from django.contrib import messages
from urllib.parse import urlencode
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse, HttpResponseBadRequest
from openai import OpenAI
from typing import List
from django.core.cache import cache
import hashlib
from django.utils.html import escape


# ---------- 유틸 함수 ----------

# 유저의 '진행 중인 장바구니'가 있으면 가져오고, 없으면 새로 생성
def get_or_create_active_shopping_list(user):
    active_list = ShoppingList.objects.filter(user=user, is_done=False).first()
    return active_list or ShoppingList.objects.create(user=user)

# 장바구니에 담긴 재료들 반환
def get_shopping_list_ingredients(shopping_list):
    return Ingredient.objects.filter(
        shoppinglistingredient__shopping_list=shopping_list
    ).order_by('name')

# 장바구니에 재료 이름 리스트를 추가하고, 추가된 재료들 반환
def add_ingredients_to_list(shopping_list, ingredient_names):
    added = []
    for name in ingredient_names:
        ing, _ = Ingredient.objects.get_or_create(name=name)
        if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ing).exists():
            ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ing)
        added.append({
            'name': ing.name,
            'image_url': ing.image.url if ing.image else None
        })
    return added

# 레시피 플로우에서 항상 같은 쇼핑리스트를 쓰도록 세션 기준으로 가져오는 기능
def get_active_shopping_list_from_session(request):
    list_id = request.session.get('shopping_list_id')
    if list_id:
        try:
            return ShoppingList.objects.get(id=list_id, user=request.user, is_done=False)
        except ShoppingList.DoesNotExist:
            pass

    sl = get_or_create_active_shopping_list(request.user)
    request.session['shopping_list_id'] = sl.id
    return sl


# 사용자 포인트
def get_user_total_point(user):
    """해당 사용자의 보유 포인트를 정수로 반환. 없으면 0."""
    if not getattr(user, "is_authenticated", False):
        return 0
    val = (
        UserPoint.objects
        .filter(user=user)
        .values_list("total_point", flat=True)
        .first()
    )
    return int(val) if val is not None else 0

# 장바구니 식재료 건수
def cart_items_count(user) -> int:
    shopping_list = (ShoppingList.objects.filter(user=user, is_done=False).order_by('-created_at').first())
    if not shopping_list:
        return 0
    return ShoppingListIngredient.objects.filter(shopping_list=shopping_list).count()

# ---------- 뷰 함수 ----------
@login_required
def splash(request):
    return render(request, "food/splash.html")


@login_required
def main(request):
    user = request.user

    # 카테고리 탭 (없으면 전체)
    allowed = {"mart", "cafe", "trad"}
    tab_raw = request.GET.get("tab")
    tab = tab_raw if tab_raw in allowed else None

    # 배너 쿼리: 노출 중 + 사용자 동(동네) 타깃
    qs = FoodBanner.objects.active().for_user(user)
    if tab:
        qs = qs.for_category(tab)

    # 여러 개 노출 (원하는 개수로 자르기)
    banners = list(qs.order_by("-created_at")[:5])

    # 진행 중 장바구니
    shopping_list = (
        ShoppingList.objects
        .filter(user=user, is_done=False)
        .order_by('-created_at')
        .first()
    )
    items_count = (
        ShoppingListIngredient.objects
        .filter(shopping_list=shopping_list)
        .count()
        if shopping_list else 0
    )

    total_point = get_user_total_point(user)

    return render(request, "food/main.html", {
        "tab": tab,                         # None이면 '전체'로 취급
        "banners": banners,                 # ← 템플릿에서 for 루프로 출력
        "shoppinglist_id": shopping_list.id if shopping_list else None,
        "has_active_cart": items_count > 0,
        "cart_items_count": items_count,
        "total_point":total_point,
    })

# ------ 1. 요리를 할거야  ------
# Step 1. 요리 입력
@login_required
def recipe_input_view(request):
    user = request.user
    initial_recipe = request.GET.get('recipe', '')

    if request.method == 'POST':
        recipe_name = request.POST.get('recipe')
        request.session['recipe_input'] = recipe_name

        # 새 요리를 입력했으므로 이전 재료들 초기화
        for k in ('basic', 'optional', 'extra_selected'):
            request.session.pop(k, None)
        return redirect('food:recipe_ingredients') 
        
    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)
    today = timezone.localdate()            # 날짜만 (로컬 타임존 기준)
    today_str = today.strftime('%Y년 %m월 %d일')  # 템플릿에서 문자열이 더 편하면 사용

    return render(request, 'food/recipe_input.html', {
        'initial_recipe': initial_recipe,
        'cart_items_count': items_count,
        'total_point': total_point,
        'today': today,        
        'today_str': today_str, 
    })


# Step 2-1. GPT 분석 결과 보여주기
@login_required
def recipe_ingredient_result(request):
    recipe_name = (request.GET.get('recipe') or request.session.get('recipe_input') or "").strip()
    if not recipe_name:
        return redirect('food:recipe_input')

    prev_recipe = request.session.get('recipe_input')

    # 레시피 변경 시 세션 초기화
    if prev_recipe != recipe_name:
        request.session['recipe_input'] = recipe_name
        for k in ('basic', 'optional', 'optional_selected', 'extra_selected'):
            request.session.pop(k, None)

    if request.method == "POST":
        # 폼에서 체크된 재료들만 사용
        selected = request.POST.getlist('ingredients')  # 모든 섹션에서 name="ingredients"로 넘어와야 함
        selected = list(dict.fromkeys(s for s in selected if s))  # 중복 제거 + 빈 값 제거
        next_action = request.POST.get('next')

        # 검색 화면에서 장바구니(선택 목록) 보여주기 위해 세션에 현재 선택 상태 저장
        # (이 키를 검색 화면에서 사용중이라면 그대로 재활용)
        request.session['optional_selected'] = selected

        if next_action == 'search':
            return redirect('food:ingredient_search')

        if next_action == 'confirm':
            if not selected:
                messages.warning(request, "선택된 재료가 없습니다.")
                return redirect('food:recipe_ingredients')

            shopping_list = get_active_shopping_list_from_session(request)

            from django.db import transaction
            with transaction.atomic():
                # 기존 장바구니 비우고
                ShoppingListIngredient.objects.filter(shopping_list=shopping_list).delete()
                # 체크된 것만 저장
                ing_map = {
                    n: i for n, i in Ingredient.objects
                    .filter(name__in=selected)
                    .values_list('name', 'id')
                }
                bulk = [
                    ShoppingListIngredient(shopping_list=shopping_list, ingredient_id=ing_map[n])
                    for n in selected if n in ing_map
                ]
                if bulk:
                    ShoppingListIngredient.objects.bulk_create(bulk)

            request.session['shopping_list_id'] = shopping_list.id
            return redirect('food:confirm_shopping_list')

        # 기타 버튼 동작 시 자기 자신으로
        return redirect('food:recipe_ingredients')

    # ---- GET 분기 (기존 그대로) ----
    basic_filtered = request.session.get('basic')
    optional_filtered = request.session.get('optional')

    need_fetch = (
        prev_recipe != recipe_name or
        basic_filtered is None or optional_filtered is None or
        (len(basic_filtered or []) == 0 and len(optional_filtered or []) == 0)
    )

    if need_fetch:
        try:
            basic_raw, optional_raw = extract_ingredients_from_recipe(recipe_name)
            db_names = set(Ingredient.objects.values_list('name', flat=True))
            basic_filtered    = [x for x in (basic_raw or [])    if x in db_names]
            optional_filtered = [x for x in (optional_raw or []) if x in db_names]
            request.session['basic'] = basic_filtered
            request.session['optional'] = optional_filtered
        except Exception as e:

            basic_filtered = basic_filtered or []
            optional_filtered = optional_filtered or []

    items_count = cart_items_count(request.user)
    total_point = get_user_total_point(request.user)

    return render(request, 'food/recipe_ingredients.html', {
        'recipe': recipe_name,
        'basic': basic_filtered or [],
        'optional': optional_filtered or [],
        'optional_selected': request.session.get('optional_selected', []),
        'extra_ingredients': request.session.get('extra_selected', []),
        'items_count' : items_count,
        'total_point' : total_point,
    })

# Step 3. 장바구니 저장
@login_required
def confirm_shopping_list(request):
    shopping_list = get_or_create_active_shopping_list(request.user)

    # 1) 최종 선택 목록 수집
    if request.method == 'POST':
        # 폼에서 체크된 항목만
        selected_names = list(dict.fromkeys(request.POST.getlist('ingredients')))
    else:
        # PRG(GET)으로 들어온 경우: 직전 단계에서 세션에 저장해둔 "체크된 목록"만 사용
        # (우리가 recipe_ingredient_result에서 request.session['optional_selected'] = selected 로 저장했음)
        selected_names = list(dict.fromkeys(request.session.get('optional_selected', [])))

    # 2) DB 갱신(교체 저장): 체크된 것만 저장
    with transaction.atomic():
        ShoppingListIngredient.objects.filter(shopping_list=shopping_list).delete()
        if selected_names:
            name_to_id = dict(
                Ingredient.objects.filter(name__in=selected_names).values_list('name', 'id')
            )
            bulk = [
                ShoppingListIngredient(shopping_list=shopping_list, ingredient_id=name_to_id[n])
                for n in selected_names if n in name_to_id
            ]
            if bulk:
                ShoppingListIngredient.objects.bulk_create(bulk)

    # 3) 화면 표시용 현재 장바구니 조회
    items_qs = Ingredient.objects.filter(
        shoppinglistingredient__shopping_list=shopping_list
    ).order_by('name')
    ingredients_ctx = [
        {"name": ing.name, "image_url": (ing.image.url if getattr(ing, "image", None) else None)}
        for ing in items_qs
    ]

    # 4) 템플릿 호환: extra_ingredients는 '선택된 것 중' extra 후보에 속하는 것만 표시
    extra_pool = set(request.session.get('extra_selected', []))
    checked_extra_ingredients = [n for n in selected_names if n in extra_pool]

    request.session['shopping_list_id'] = shopping_list.id

    items_count = cart_items_count(request.user)
    total_point = get_user_total_point(request.user)

    return render(request, 'food/recipe_result.html', {
        "shopping_list": shopping_list,
        "ingredients": ingredients_ctx,              # 현재 장바구니(체크된 항목만 저장된 결과)
        "extra_ingredients": checked_extra_ingredients,
        'cart_items_count': items_count,
        "total_point": total_point,
    })


PER_CART_SESSION_KEYS = (
    'extra_selected',
    'optional_selected',
    'ing_search_started',
    'optional_selected_snapshot',
    'ing_added_temp',
)

@login_required
def ingredient_search_view(request):
    # 장바구니가 바뀌었는지 확인하고, 바뀌었다면 per-cart 세션 키 초기화
    sl = get_or_create_active_shopping_list(request.user)
    prev_sl_id = request.session.get('shopping_list_id')
    if prev_sl_id != sl.id:
        for k in PER_CART_SESSION_KEYS:
            request.session.pop(k, None)
        request.session['shopping_list_id'] = sl.id

    raw = request.GET.get('search')
    search_query = (raw or '').strip()
    did_click_search = request.GET.get('action') == 'search'

    if did_click_search and search_query == '':
        messages.warning(request, "검색어를 입력해주세요.")
        return redirect('food:ingredient_search')

    # 최근 검색어 업데이트(원하면 이건 유지해도 됨)
    if did_click_search and search_query:
        recent = request.session.get('recent_searches', [])
        if search_query in recent:
            recent.remove(search_query)
        recent.insert(0, search_query)
        request.session['recent_searches'] = recent[:6]

    # 장바구니 후보(세션 기반)
    extra_selected = request.session.get('extra_selected', [])
    selected_ingredients = Ingredient.objects.filter(name__in=extra_selected).order_by('name')

    if search_query:
        category_ingredients = (
            Ingredient.objects
            .filter(name__icontains=search_query)
            .exclude(name__in=extra_selected)
            .order_by('name')
        )
        if did_click_search and not category_ingredients.exists():
            messages.info(request, f"‘{search_query}’에 해당하는 재료가 없습니다.")
    else:
        category_ingredients = Ingredient.objects.none()

    return render(request, 'food/recipe_ingredients_search.html', {
        'search_query': search_query,
        'category_ingredients': category_ingredients,
        'selected_ingredients': selected_ingredients,
        'recent_searches': request.session.get('recent_searches', []),
    })


# 체크박스 클릭 → 즉시 '세션(extra_selected)'에만 추가
@login_required
def add_extra_ingredient(request):
    if request.method != 'POST':
        return redirect('food:ingredient_search')

    name = (request.POST.get('ingredient') or '').strip()
    search = (request.POST.get('search') or '').strip()
    if not name:
        return redirect('food:ingredient_search')

    # 유효성(존재 재료) 체크만
    if not Ingredient.objects.filter(name=name).exists():
        messages.error(request, f"{name} 재료를 찾을 수 없습니다.")
    else:
        extra_selected = request.session.get('extra_selected', [])
        if name not in extra_selected:
            extra_selected.append(name)
            request.session['extra_selected'] = extra_selected
        else:
            messages.info(request, f"{name}은(는) 이미 담겨 있어요.")

    base = reverse('food:ingredient_search')
    return redirect(f"{base}?{urlencode({'search': search})}" if search else base)


# (세션에서만) 장바구니 후보 제거
@login_required
def delete_extra_ingredient(request, name):
    if request.method != 'POST':
        return redirect('food:ingredient_search')

    search = (request.POST.get('search') or '').strip()

    extra_selected = request.session.get('extra_selected', [])
    if name in extra_selected:
        extra_selected.remove(name)
        request.session['extra_selected'] = extra_selected
    else:
        messages.info(request, f"{name}은(는) 후보에 없어요.")

    base = reverse('food:ingredient_search')
    return redirect(f"{base}?{urlencode({'search': search})}" if search else base)


# 최근 검색어 삭제
@login_required
def delete_recent_search(request, keyword):
    recent_searches = request.session.get('recent_searches', [])
    if keyword in recent_searches:
        recent_searches.remove(keyword)
        request.session['recent_searches'] = recent_searches
    return redirect('food:ingredient_search')


# 최근 검색어 전체 삭제
@login_required
def clear_recent_searches(request):
    request.session['recent_searches'] = []
    return redirect('food:ingredient_search')


# X(취소) → 이번 화면에서 새로 담은 것만 롤백(DB/세션 복원) 후 검색 화면으로
@login_required
def cancel_ingredient_search(request):
    if request.session.get('ing_search_started'):
        sl = get_active_shopping_list_from_session(request)

        added = request.session.get('ing_added_temp', [])
        if added:
            ShoppingListIngredient.objects.filter(
                shopping_list=sl,
                ingredient__name__in=added
            ).delete()

        snapshot = request.session.get('optional_selected_snapshot', [])
        request.session['optional_selected'] = snapshot

        for k in ('ing_search_started', 'optional_selected_snapshot', 'ing_added_temp'):
            request.session.pop(k, None)

    return redirect('food:recipe_ingredients')

@login_required
def recipe_ai(request):
    user = request.user
    # 대화 세션 초기화 + system 가이드 주입
    ingredient_names = list(Ingredient.objects.values_list('name', flat=True))
    ingredient_list_str = ', '.join(ingredient_names)

    if 'chat_history' not in request.session:
        request.session['chat_history'] = [{
            "role": "system",
            "content": (
                "넌 사용자의 기분과 상황을 듣고 요리를 제안하는 친절한 요리 도우미야. "
                "반드시 **하나의 요리만** 추천하고, 추천 끝에 요리명을 큰따옴표(\")로 감싸서 제시해. "
                "간단한 설명과 필요한 재료도 덧붙여."
                "추천 요리는 반드시 사용할 수 있는 재료 목록에서 만들 수 있는 요리만 추천해"
                "재료도 마찬가지로 반드시 사용할 수 있는 재료 목록에서 설명해줘"
                f"- 사용할 수 있는 재료 목록: {ingredient_list_str}\n"
                "한 문장이 끝나면 줄바꿈을 해"
            )
        }]

    chat = request.session['chat_history']

    if request.method == 'POST':
        user_msg = (request.POST.get('message') or '').strip()
        if not user_msg:
            return redirect('food:recipe_ai')

        # 1) 사용자 메시지 추가
        chat.append({"role": "user", "content": user_msg})

        # 2) GPT 대화 호출 (모듈 함수 그대로 사용)
        try:
            gpt_reply = gpt_conversational_cook(chat)
        except Exception as e:
            messages.error(request, f"AI 응답 실패: {e}")
            return redirect('food:recipe_ai')

        # 3) GPT 응답 저장
        chat.append({"role": "assistant", "content": gpt_reply})
        request.session['chat_history'] = chat
        request.session.modified = True

        # 4) 최신 응답에서 요리명 추출 (모듈 함수 그대로 사용)
        recipe_name = extract_recipe_name_from_gpt_response(gpt_reply)

        # 5) 요리명이 있으면: 버튼용 저장 + 재료 v2 분석 시도
        if recipe_name:
            request.session['latest_recipe']  = recipe_name
            request.session['recipe_input']   = recipe_name  # 이후 재료 페이지에서 사용

            # v2 분석기로 basic/optional 미리 세션에 저장
            try:
                # DB 재료 이름 리스트
                allowed = list(Ingredient.objects.values_list('name', flat=True))
                basic_v2, optional_v2 = extract_ingredients_from_recipe_v2(
                    recipe_name, allowed_ingredients=allowed
                )
                # v2가 실패(빈 리스트 반환)하면 그냥 저장 안 함 → 다음 단계에서 기존 로직이 처리
                if basic_v2 or optional_v2:
                    # 안전하게 DB에 존재하는 것만 유지
                    allowed_set = set(allowed)
                    basic_filtered    = [x for x in basic_v2    if x in allowed_set]
                    optional_filtered = [x for x in optional_v2 if x in allowed_set]
                    request.session['basic']    = basic_filtered
                    request.session['optional'] = optional_filtered
            except Exception:
                # 분석 실패는 조용히 무시 (대화는 계속)
                pass

        # 6) 다시 같은 페이지로 (대화 + 버튼 표시)
        return redirect('food:recipe_ai')

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    # GET 렌더
    return render(request, 'food/recipe_ai.html', {
        'chat_history': request.session['chat_history'],
        'latest_recipe': request.session.get('latest_recipe'),
        'user' : user,
        'cart_items_count': items_count,
        'total_point': total_point,
    })

# ------ 2. 식재료를 고를거야  ------

@login_required
def ingredient_input_view(request):
    # 검색어/액션
    raw = request.GET.get('search')
    search_query = (raw or '').strip()
    did_click_search = request.GET.get('action') == 'search'  # 검색 버튼 눌렀는지 여부

    # 빈 검색어 제출 방지
    if did_click_search and search_query == '':
        messages.warning(request, "검색어를 입력해주세요.")
        return redirect('food:ingredient_input')

    # 최근 검색어 업데이트(검색 버튼 눌렀을 때만)
    if did_click_search and search_query:
        recent = request.session.get('recent_searches', [])
        if search_query in recent:
            recent.remove(search_query)
        recent.insert(0, search_query)
        request.session['recent_searches'] = recent[:6]

    # 장바구니(확정된 항목): optional_selected 세션 기준
    optional_selected = request.session.get('optional_selected', [])
    selected_ingredients = Ingredient.objects.filter(name__in=optional_selected).order_by('name')

    # 검색 버튼 눌렀을 때만 결과 계산/표시, 이미 담긴 것 제외
    if did_click_search and search_query:
        category_ingredients = (
            Ingredient.objects
            .filter(name__icontains=search_query)
            .exclude(name__in=optional_selected)
            .order_by('name')
        )
        if not category_ingredients.exists():
            messages.info(request, f"‘{search_query}’에 해당하는 재료가 없습니다.")
    else:
        category_ingredients = Ingredient.objects.none()

    items_count = cart_items_count(request.user)
    total_point = get_user_total_point(request.user)

    return render(request, 'food/ingredient_input.html', {
        'search_query': search_query,
        'category_ingredients': category_ingredients,
        'selected_ingredients': selected_ingredients,
        'recent_searches': request.session.get('recent_searches', []),
        'cart_items_count': items_count,
        'total_point': total_point,
    })


# Step 1-1. 원하는 식재료 장바구니에 추가하기
@login_required
def add_ingredient(request):
    if request.method != 'POST':
        return redirect('food:ingredient_input')

    name = (request.POST.get('ingredient') or '').strip()
    search = (request.POST.get('search') or '').strip()

    if not name:
        messages.error(request, "내용을 입력해 주세요.")
        base = reverse('food:ingredient_input')
        return redirect(f"{base}?{urlencode({'search': search})}" if search else base)

    try:
        ingredient = Ingredient.objects.get(name=name)
    except Ingredient.DoesNotExist:
        messages.error(request, f"{name}은(는) 존재하지 않습니다.")
        base = reverse('food:ingredient_input')
        return redirect(f"{base}?{urlencode({'search': search})}" if search else base)

    shopping_list = get_or_create_active_shopping_list(request.user)

    # DB 추가 (중복 생성 방지)
    _, created = ShoppingListIngredient.objects.get_or_create(
        shopping_list=shopping_list,
        ingredient=ingredient
    )

    # 세션(optional_selected) 동기화
    optional_selected = request.session.get('optional_selected', [])
    if name not in optional_selected:
        optional_selected.append(name)
        request.session['optional_selected'] = optional_selected

    if not created:
        messages.info(request, f"{name}은(는) 이미 추가되어 있어요.")

    base = reverse('food:ingredient_input')
    return redirect(f"{base}?{urlencode({'search': search})}" if search else base)


# Step 1-2. 장바구니에 담은 식재료 제거하기
@login_required
def delete_ingredient(request, name):
    if request.method != 'POST':
        return redirect('food:ingredient_input')

    search = (request.POST.get('search') or '').strip()

    try:
        ingredient = Ingredient.objects.get(name=name)
    except Ingredient.DoesNotExist:
        messages.error(request, f"{name}은(는) 존재하지 않습니다.")
        base = reverse('food:ingredient_input')
        return redirect(f"{base}?{urlencode({'search': search})}" if search else base)

    shopping_list = get_or_create_active_shopping_list(request.user)

    # DB 제거
    ShoppingListIngredient.objects.filter(
        shopping_list=shopping_list, ingredient=ingredient
    ).delete()

    # 세션(optional_selected) 동기화
    optional_selected = request.session.get('optional_selected', [])
    if name in optional_selected:
        optional_selected.remove(name)
        request.session['optional_selected'] = optional_selected

    messages.success(request, f"{name}을(를) 장바구니에서 제거했어요.")

    base = reverse('food:ingredient_input')
    return redirect(f"{base}?{urlencode({'search': search})}" if search else base)


# 최근 검색어 삭제
@login_required
def delete_recent_ingredient(request, keyword):
    recent = request.session.get('recent_searches', [])
    if keyword in recent:
        recent.remove(keyword)
        request.session['recent_searches'] = recent
    return redirect('food:ingredient_input')


# 최근 검색어 전체 삭제
@login_required
def clear_recent_ingredient(request):
    request.session['recent_searches'] = []
    return redirect('food:ingredient_input')




# Step 2. 장바구니에 담은 식재료 모아보기
@login_required
def ingredient_result_view(request):
    user = request.user

    # 진행 중인 장바구니 가져오기 (없으면 생성)
    shopping_list = get_or_create_active_shopping_list(user)

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'food/ingredient_result.html', {
        'shopping_list': shopping_list, 'cart_items_count': items_count, 'total_point': total_point,
    })

def generate_recipe_chat(ingredient_name: str, followup: str | None = None) -> str:
    """
    내부 통일용 래퍼. 프로젝트에 이미 있는 generate_tip_text를 그대로 재사용.
    (별도의 모델 호출 로직을 쓰고 싶으면 이 함수만 바꾸면 됨)
    """
    return generate_tip_text(ingredient_name, followup=followup)

@login_required
@require_GET
def ingredient_idea_page(request):
    """
    페이지: ‘{name}로 이런 요리를 할 수 있어요’ + 채팅
    """
    name = (request.GET.get("name") or "").strip()
    if not name:
        return HttpResponseBadRequest("name required")
    return render(request, "food/ingredient_idea.html", {"name": name})

@login_required
@require_GET
def ingredient_idea_api(request):
    """
    AJAX: 초기 아이디어 or 후속 질문 답변
    - params: name=토마토, q=사용자질문(없으면 초기 추천)
    - return: {ok: True, text: "..."} 형태
    """
    name = (request.GET.get("name") or "").strip()
    q    = (request.GET.get("q") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "name required"}, status=400)

    if q:
        text = generate_recipe_chat(name, followup=q)
        return JsonResponse({"ok": True, "text": text})

    # 초기 추천은 캐시하여 재호출 줄이기
    key = f"idea:{name.lower()}"
    text = cache.get(key)
    if text is None:
        text = generate_recipe_chat(name)
        cache.set(key, text, 60 * 60 * 24)  # 24h
    return JsonResponse({"ok": True, "text": text})



# ------ 3. 남은 식재료로 요리 추천받기 ------

def _parse_title_and_description(text: str):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "이름 미상", text or ""
    return lines[0].strip(), "\n".join(lines[1:]).strip()

def _ids_seed(ids: List[int]) -> str:
    s = ",".join(map(str, sorted(map(int, ids))))
    return hashlib.sha1(s.encode()).hexdigest()

# ---------- 1) 재료 선택 ----------
@login_required
def select_recent_ingredients(request):
    user = request.user

    latest_list = (
        ShoppingList.objects.filter(user=request.user)
        .order_by('-created_at')
        .first()
    )
    if not latest_list:
        return render(request, 'food/leftover_save_no_ingredients.html', {
        "cart_items_count": items_count,
        "total_point": total_point,})

    ingredients = (
        ShoppingListIngredient.objects
        .filter(shopping_list=latest_list)
        .select_related('ingredient')
    )

    if request.method == 'POST':
        selected_ids = request.POST.getlist('ingredient_ids')  # ['3','8',...]
        if not selected_ids:
            messages.error(request, "재료를 최소 1개 선택해주세요.")
            return redirect('food:select_recent_ingredients')

        request.session['selected_ingredient_ids'] = selected_ids
        request.session['selected_seed'] = _ids_seed(selected_ids)
        request.session['recipe_chat'] = []            # 새 선택이므로 초기화
        request.session['last_recipe_text'] = None
        return redirect('food:chat_with_selected_ingredients')
    
    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'food/leftover_select_recent_ingredients.html', {
        'ingredients': ingredients,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

# ---------- 2) 채팅(자동 추천) ----------
@login_required
def chat_with_selected_ingredients(request):
    user = request.user

    selected_ids = request.session.get('selected_ingredient_ids', [])
    if not selected_ids:
        messages.error(request, "먼저 재료를 선택해주세요.")
        return redirect('food:select_recent_ingredients')

    ingredients = Ingredient.objects.filter(id__in=selected_ids).order_by('name')
    selected_names = [i.name for i in ingredients]

    chat = request.session.get('recipe_chat', [])
    last_recipe = request.session.get('last_recipe_text')

    # 첫 진입이면 자동 추천 1회
    if not chat:
        try:
            first = call_gpt(selected_names)
        except Exception as e:
            messages.error(request, str(e))
            return redirect('food:select_recent_ingredients')
        chat = [{"role": "assistant", "content": first}]
        request.session['recipe_chat'] = chat
        request.session['last_recipe_text'] = first
        last_recipe = first

    # 후속 질문 처리
    if request.method == 'POST':
        followup = request.POST.get('message', '').strip()
        if followup:
            try:
                answer = call_gpt(selected_names, followup)
            except Exception as e:
                messages.error(request, str(e))
                return redirect('food:chat_with_selected_ingredients')

            chat.append({"role": "user", "content": followup})
            chat.append({"role": "assistant", "content": answer})
            request.session['recipe_chat'] = chat
            request.session['last_recipe_text'] = answer
            last_recipe = answer
        return redirect('food:chat_with_selected_ingredients')
    
    # 렌더 직전: 방금 저장한 레시피 제목 있으면 모달로 보여주기
    saved_title = request.session.pop('just_saved_recipe_title', None)

    items_count = cart_items_count(user)
    total_point = get_user_total_point(user)

    return render(request, 'food/leftover_chat_with_ingredients.html', {
        'selected_names': selected_names,
        'chat': chat,
        'last_recipe': last_recipe,
        'last_recipe_title': _parse_title_and_description(last_recipe)[0] if last_recipe else None,
        'saved_title': saved_title,
        "cart_items_count": items_count,
        "total_point": total_point,
    })

# ---------- 3) 저장 ----------
@login_required
def save_last_recipe(request):
    text = request.session.get('last_recipe_text')
    if not text:
        messages.error(request, "저장할 레시피가 없습니다.")
        return redirect('food:chat_with_selected_ingredients')

    title, desc = _parse_title_and_description(text)
    SavedRecipe.objects.create(user=request.user, title=title[:200], description=desc)
    
    # 채팅 화면에서 모달을 띄우기 위해 세션에 제목 저장
    request.session['just_saved_recipe_title'] = title

    # 채팅 화면으로 리다이렉트 (거기서 모달 띄움)
    return redirect('food:chat_with_selected_ingredients')

# (선택) 대화 초기화
@login_required
def clear_recipe_chat(request):
    request.session.pop('recipe_chat', None)
    request.session.pop('last_recipe_text', None)
    messages.info(request, "대화를 초기화했어요.")
    return redirect('food:chat_with_selected_ingredients')



# 장바구니
@login_required
def cart_view(request):
    user = request.user

    shopping_list = (
        ShoppingList.objects
        .filter(user=user, is_done=False)
        .order_by('-created_at')
        .first()
    )

    if not shopping_list:
        return render(request, "food/cart.html", {"shopping_list": None, "items": []})

    items = (
        ShoppingListIngredient.objects
        .filter(shopping_list=shopping_list)
        .select_related("ingredient")
        .order_by("ingredient__name")
    )

    if request.method == "POST":
        action = request.POST.get("action")
        selected_ids = request.POST.getlist("selected")
        next_url = request.POST.get("next") or request.GET.get("next")

        # 전체 비우기
        if action == "clear_all":
            ShoppingListIngredient.objects.filter(
                shopping_list=shopping_list
            ).delete()
            # 선택 목록 세션도 초기화(선택)
            request.session.pop("optional_selected", None)

            # next가 있으면 거기로, 없으면 기존처럼 장바구니로
            if next_url:
                return redirect(next_url)
            return redirect("food:main")

        # 선택 삭제
        if action == "remove_selected":
            if selected_ids:
                ShoppingListIngredient.objects.filter(
                    id__in=selected_ids, shopping_list=shopping_list
                ).delete()
            return redirect("food:cart_view")

        # 개별 삭제
        remove_one_id = request.POST.get("remove_one")
        if remove_one_id:
            ShoppingListIngredient.objects.filter(
                id=remove_one_id, shopping_list=shopping_list
            ).delete()
            return redirect("food:cart_view")

        # 선택한 것만 confirm 으로
        if action == "go_confirm":
            if selected_ids:
                selected_names = list(
                    ShoppingListIngredient.objects
                    .filter(id__in=selected_ids, shopping_list=shopping_list)
                    .values_list("ingredient__name", flat=True)
                )
            else:
                selected_names = list(
                    ShoppingListIngredient.objects
                    .filter(shopping_list=shopping_list)
                    .values_list("ingredient__name", flat=True)
                )
            request.session["optional_selected"] = selected_names
            request.session.modified = True
            return redirect("food:confirm_shopping_list")

    return render(request, "food/cart.html", {"shopping_list": shopping_list, "items": items})
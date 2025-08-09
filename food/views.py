from django.shortcuts import render, redirect, get_object_or_404
from .ai import *
from .models import *
from market.models import ShoppingList, ShoppingListIngredient
from django.contrib import messages
from django.db import transaction
from django.db.models import Case, When, Value, IntegerField
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.conf import settings
import json
from openai import OpenAI



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

# 모든 재료 이름을 문자열로 나열
ingredient_names = Ingredient.objects.values_list('name', flat=True)
ingredient_list_str = ', '.join(ingredient_names)


# ---------- 뷰 함수 ----------

@login_required
def main(request):
    user = request.user
    hide_warn = request.GET.get('hide_warn') == '1'

    shopping_list = ShoppingList.objects.filter(user=user, is_done=False).order_by('-created_at').first()

    warn = False
    ingredients = []
    if shopping_list and shopping_list.shoppinglistingredient_set.exists() and not hide_warn:
        warn = True
        ingredients = shopping_list.shoppinglistingredient_set.values_list('ingredient__name', flat=True)

    return render(request, 'food/main.html', {
        'warn': warn,
        'shoppinglist_id': shopping_list.id if shopping_list else None,
        'ingredients': ingredients,  # 여기 추가
    })


@require_POST
@login_required
def reset_shoppinglist_view(request):
    shoppinglist_id = request.POST.get('shoppinglist_id')
    shopping_list = get_object_or_404(ShoppingList, id=shoppinglist_id, user=request.user, is_done=False)

    # 연결된 재료들 삭제
    shopping_list.shoppinglistingredient_set.all().delete()
    shopping_list.delete()

    # 새 ShoppingList 생성은 ingredient_input_view나 recipe_input_view에서 처리되므로 여기선 redirect만
    return redirect('food:main')

# ------ 1. 요리를 할거야  ------

# Step 1. 요리 입력
def recipe_input_view(request):
    initial_recipe = request.GET.get('recipe', '')  # GPT에서 넘겨준 요리명 (없으면 빈 문자열)

    if request.method == 'POST':
        recipe_name = request.POST.get('recipe')
        request.session['recipe_input'] = recipe_name

        # 새 요리를 입력했으므로 이전 재료들 초기화
        request.session.pop('basic', None)
        request.session.pop('optional', None)
        request.session.pop('extra_ingredients', None)

        return redirect('food:recipe_ingredients')

    return render(request, 'food/recipe_input.html', {'initial_recipe': initial_recipe})


# Step 2-1. GPT 분석 결과 보여주기

@login_required
def recipe_ingredient_result(request):
    recipe_name = request.GET.get('recipe') or request.session.get('recipe_input')
    if not recipe_name:
        return redirect('food:recipe_input')

    # === POST: 버튼 분기 ===
    if request.method == "POST":
        selected = request.POST.getlist('ingredients')  # ✔ 체크된 전체(기본+선택+직접추가)
        print("[DEBUG] POST /recipe/ingredients/ selected =", selected)

        basic = set(request.session.get('basic', []))
        optional_selected = [name for name in selected if name not in basic]
        request.session['optional_selected'] = optional_selected
        next_action = request.POST.get('next')
        print("[DEBUG] next_action =", next_action)

        # ➜ 재료 직접 추가하기
        if next_action == 'search':
            return redirect('food:ingredient_search')

        # ➜ 완료(확정 저장)
        if next_action == 'confirm':
            extra = request.session.get('extra_ingredients', [])
            selected_names = list(dict.fromkeys(list(basic) + optional_selected + extra))
            print("[DEBUG] names to save =", selected_names)

            if not selected_names:
                messages.warning(request, "선택된 재료가 없습니다.")
                return redirect('food:confirm_shopping_list')

            shopping_list = get_or_create_active_shopping_list(request.user)
            print("[DEBUG] shopping_list.id =", shopping_list.id)

            # DB 저장(덮어쓰기)
            with transaction.atomic():
                deleted = ShoppingListIngredient.objects.filter(shopping_list=shopping_list).delete()
                print("[DEBUG] deleted count =", deleted)

                # 이름→객체 매핑 (DB에 있는 것만 추가)
                ing_map = {n: i for n, i in Ingredient.objects.filter(
                    name__in=selected_names).values_list('name', 'id')}

                bulk = []
                for n in selected_names:
                    ing_id = ing_map.get(n)
                    if ing_id:
                        bulk.append(ShoppingListIngredient(
                            shopping_list=shopping_list,
                            ingredient_id=ing_id
                        ))
                    else:
                        print(f"[DEBUG] skip unknown ingredient: {n}")

                if bulk:
                    ShoppingListIngredient.objects.bulk_create(bulk)
                    print("[DEBUG] bulk created =", len(bulk))
                else:
                    print("[DEBUG] bulk empty!")

            request.session['shopping_list_id'] = shopping_list.id
            return redirect('food:confirm_shopping_list')

        # 그 외 값이면 그냥 현재 화면 리렌더
        return redirect('food:recipe_ingredients')

    # === GET: 세션 캐시 준비 후 렌더 ===
    basic_filtered = request.session.get('basic')
    optional_filtered = request.session.get('optional')
    if not basic_filtered or not optional_filtered:
        basic_raw, optional_raw = extract_ingredients_from_recipe(recipe_name)
        db_names = set(Ingredient.objects.values_list('name', flat=True))
        basic_filtered = [i for i in basic_raw if i in db_names]
        optional_filtered = [i for i in optional_raw if i in db_names]
        request.session['basic'] = basic_filtered
        request.session['optional'] = optional_filtered

    extra_ingredients = request.session.get('extra_ingredients', [])
    optional_selected = set(request.session.get('optional_selected', []))

    return render(request, 'food/recipe_ingredients.html', {
        'recipe': recipe_name,
        'basic': basic_filtered,
        'optional': optional_filtered,
        'extra_ingredients': extra_ingredients,
        'optional_selected': optional_selected,
    })

# Step 3. 장바구니 저장
@login_required
def confirm_shopping_list(request):
    shopping_list = get_or_create_active_shopping_list(request.user)

    # 1) 예전 흐름(POST로 직접 이 뷰를 호출): 넘어온 재료를 추가
    if request.method == 'POST':
        selected = request.POST.getlist('ingredients')  # 체크된 항목 (이름 리스트)
        if selected:
            add_ingredients_to_list(shopping_list, selected)

        # extra_ingredients 중 실제로 체크된 항목만 (POST일 때만 의미 있음)
        all_extra = request.session.get('extra_ingredients', [])
        checked_extra_ingredients = [name for name in all_extra if name in selected]
    else:
        # 2) 새로운 흐름(PRG): 이미 이전 단계에서 DB에 저장했으므로 DB에서 읽기만
        checked_extra_ingredients = request.session.get('extra_ingredients', [])

    # 화면 표시용으로 현재 장바구니 내용을 DB에서 읽어와서 ingredients 형태로 맞춰줌
    items_qs = Ingredient.objects.filter(
        shoppinglistingredient__shopping_list=shopping_list
    ).order_by('name')

    ingredients_ctx = [
        {"name": ing.name, "image_url": (ing.image.url if getattr(ing, "image", None) else None)}
        for ing in items_qs
    ]

    request.session['shopping_list_id'] = shopping_list.id

    return render(request, 'food/recipe_result.html', {
        "shopping_list": shopping_list,
        "ingredients": ingredients_ctx,              # 현재 장바구니 전체(이미 DB 저장된 내용)
        "extra_ingredients": checked_extra_ingredients,
    })

@login_required
def ingredient_search_view(request):
    search_query = request.GET.get('search', '').strip()
    selected_category = request.GET.get('category', '').strip()

    # 세션에서 현재 선택/추가된 재료 이름들
    basic_names = request.session.get('basic', [])
    extra_names = request.session.get('extra_ingredients', [])
    optional_selected = request.session.get('optional_selected', [])

    # 중복 제거(순서 보존)
    selected_names = list(dict.fromkeys(basic_names + optional_selected + extra_names))

    # 장바구니 목록: '직접 추가' 여부로 정렬(맨 아래로)
    selected_ingredients = (
        Ingredient.objects.filter(name__in=selected_names)
        .annotate(
            is_extra=Case(
                When(name__in=extra_names, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by('is_extra', 'name')  # 기본/선택 → 이름순, 그다음 직접추가 → 이름순
    )

    # 카테고리/검색
    categories = Category.objects.all().order_by('name')
    category_ingredients = Ingredient.objects.all().order_by('name')
    if selected_category:
        category_ingredients = category_ingredients.filter(category__name=selected_category)
    if search_query:
        category_ingredients = category_ingredients.filter(name__icontains=search_query)

    # 장바구니에 있는 건 리스트에서 제외
    if selected_names:
        category_ingredients = category_ingredients.exclude(name__in=selected_names)

    context = {
        'search_query': search_query,
        'selected_category': selected_category,
        'categories': categories,
        'category_ingredients': category_ingredients,
        'selected_ingredients': selected_ingredients,
        'extra_names': set(extra_names),  # 템플릿에서 (삭제) 표시용
    }
    return render(request, 'food/recipe_ingredients_search.html', context)

@login_required
def add_extra_ingredient(request):
    if request.method == 'POST':
        name = request.POST.get('ingredient', '').strip()
        category = request.POST.get('category', '').strip()

        if not name:
            messages.error(request, "재료 이름이 비어 있습니다.")
        else:
            # 세션에서 기존 목록 가져오기 (없으면 빈 리스트)
            extra_ingredients = request.session.get('extra_ingredients', [])

            if name not in extra_ingredients:
                extra_ingredients.append(name)
                request.session['extra_ingredients'] = extra_ingredients
            else:
                messages.info(request, f"{name}은(는) 이미 추가되어 있어요.")

        # 카테고리, 검색어 유지한 채로 리디렉션
        base_url = reverse('food:ingredient_search')
        query_params = {}
        if category:
            query_params['category'] = category
        query_string = urlencode(query_params)
        return redirect(f"{base_url}?{query_string}" if query_string else base_url)

    return redirect('food:ingredient_search')


@login_required
def delete_extra_ingredient(request, name):
    if request.method == 'POST':
        category = request.POST.get('category', '').strip()

        # 세션에 저장된 재료 목록 불러오기
        extra_ingredients = request.session.get('extra_ingredients', [])

        # 재료가 목록에 있으면 제거
        if name in extra_ingredients:
            extra_ingredients.remove(name)
            request.session['extra_ingredients'] = extra_ingredients
            messages.success(request, f"{name}을(를) 장바구니에서 제거했어요.")
        else:
            messages.info(request, f"{name}은(는) 장바구니에 없어요.")

        # 리디렉션
        redirect_url = reverse('food:ingredient_search')
        if category:
            redirect_url += f'?category={category}'
        return redirect(redirect_url)

    return redirect('food:ingredient_search')


# Step 4. 장바구니 결과 보여주기
@login_required
def recipe_result_view(request):
    list_id = request.session.get('shopping_list_id')
    shopping_list = get_object_or_404(ShoppingList, id=list_id, user=request.user)
    ingredients = get_shopping_list_ingredients(shopping_list)

    return render(request, 'food/recipe_result.html', {'shopping_list': shopping_list, 'ingredients': ingredients})


@login_required
def recipe_ai(request):
    # ?reset=1 오면 세션 초기화
    if 'reset' in request.GET:
        for key in [
            'recipe_input', 'basic', 'optional', 'extra_ingredients',
            'search_selected', 'chat_history', 'latest_recipe', 'shopping_list_id'
        ]:
            request.session.pop(key, None)
        return redirect('food:recipe_ai')

    # 대화 세션 초기화 + system 가이드 주입
    if 'chat_history' not in request.session:
        request.session['chat_history'] = [{
            "role": "system",
            "content": (
                "넌 사용자의 기분과 상황을 듣고 요리를 제안하는 친절한 요리 도우미야. "
                "반드시 **하나의 요리만** 추천하고, 추천 끝에 요리명을 큰따옴표(\")로 감싸서 제시해. "
                "예: 추천 요리: \"된장찌개\". 간단한 설명과 필요한 재료도 덧붙여."
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

    # GET 렌더
    return render(request, 'food/recipe_ai.html', {
        'chat_history': request.session['chat_history'],
        'latest_recipe': request.session.get('latest_recipe')
    })

# ------ 2. 식재료를 고를거야  ------

@login_required
def ingredient_input_view(request):
    user = request.user
    search_query = request.GET.get('search', '').strip()
    selected_category = request.GET.get('category', '').strip()

    categories = Category.objects.all().order_by('name')
    shopping_list = get_or_create_active_shopping_list(user)
    selected_ingredients = get_shopping_list_ingredients(shopping_list)

    if search_query:
        ingredients = Ingredient.objects.filter(name__icontains=search_query).order_by('name')
        if ingredients.exists():
            messages.success(request, f"'{search_query}' 관련 검색 결과입니다.")
        else:
            messages.error(request, f"'{search_query}'과(와) 관련된 재료가 없습니다.")
    elif selected_category:
        ingredients = Ingredient.objects.filter(category__name=selected_category).order_by('name')
    else:
        ingredients = Ingredient.objects.all().order_by('name')

    context = {
        'selected_category': selected_category,
        'search_query': search_query,
        'category_ingredients': ingredients,
        'categories': categories,
        'selected_ingredients': selected_ingredients,
    }
    return render(request, 'food/ingredient_input.html', context)

# Step 1-1. 원하는 식재료 장바구니에 추가하기
@login_required
def add_ingredient(request):
    if request.method == 'POST':
        name = request.POST.get('ingredient', '').strip()
        category = request.POST.get('category', '').strip()

        if not name:
            messages.error(request, "내용을 입력해 주세요.")
            return redirect('food:ingredient_input')

        try:
            ingredient = Ingredient.objects.get(name=name)
        except Ingredient.DoesNotExist:
            messages.error(request, f"{name}은(는) 마트에서 판매하지 않습니다.")
            return redirect('food:ingredient_input')

        shopping_list = get_or_create_active_shopping_list(request.user)

        if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ingredient).exists():
            ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ingredient)
        else:
            messages.info(request, f"{name}은(는) 이미 추가되어 있어요.")

        redirect_url = reverse('food:ingredient_input')
        if category:
            redirect_url += f'?category={category}'
        return redirect(redirect_url)

    return redirect('food:ingredient_input')

# Step 1-2. 장바구니에 담은 식재료 제거하기
@login_required
def delete_ingredient(request, name):
    if request.method == 'POST':
        category = request.POST.get('category', '').strip()

        try:
            ingredient = Ingredient.objects.get(name=name)
        except Ingredient.DoesNotExist:
            messages.error(request, f"{name}은(는) 존재하지 않습니다.")
            return redirect('food:ingredient_input')

        shopping_list = get_or_create_active_shopping_list(request.user)

        ShoppingListIngredient.objects.filter(
            shopping_list=shopping_list, ingredient=ingredient
        ).delete()

        redirect_url = reverse('food:ingredient_input')
        if category:
            redirect_url += f'?category={category}'
        return redirect(redirect_url)

    return redirect('food:ingredient_input')


# Step 2. 장바구니에 담은 식재료 모아보기
@login_required
def ingredient_result_view(request):
    user = request.user

    # 진행 중인 장바구니 가져오기 (없으면 생성)
    shopping_list = get_or_create_active_shopping_list(user)

    return render(request, 'food/ingredient_result.html', {
        'shopping_list': shopping_list
    })


# Step 3. 선택한 식재료의 요리 추천받기(AI활용)
@login_required
def ingredient_ai_view(request, name):

    # AI API를 통해 요리 추천 요청
    result = get_recipes_using_ingredient(name)

    # 에러인지 결과인지 구분
    if isinstance(result, str):  # 에러 메시지일 경우
        recipes_data = []
        ai_reply = result
    else:
        recipes_data = result
        ai_reply = json.dumps(result, ensure_ascii=False)

    # 세션에 AI 응답과 재료 이름 저장 (결과 페이지나 이후 단계에 활용 가능)
    request.session['last_ai_reply'] = ai_reply
    request.session['last_ingredient_name'] = name

    # 결과 템플릿 렌더링
    return render(request, 'food/ingredient_ai.html', {
        'ingredient_name': name,
        'recipes': recipes_data,
    })


# Step 3-1. 추천받은 요리의 원하는 식재료 장바구니에 추가하기
@login_required
def add_ingredient_ai(request):
    if request.method == "POST":
        selected_names = request.POST.getlist("ingredients")
        print("선택된 재료 이름 목록:", selected_names)

        selected_ingredients = Ingredient.objects.filter(name__in=selected_names)
        print("DB에서 매칭된 재료 객체 수:", selected_ingredients.count())

        shopping_list = get_or_create_active_shopping_list(request.user)

        for ingredient in selected_ingredients:
            ShoppingListIngredient.objects.get_or_create(
                shopping_list=shopping_list,
                ingredient=ingredient
            )

        request.session['shopping_list_id'] = shopping_list.id

    return redirect('food:ingredient_result')

@login_required
def show_recent_ingredients(request):
    # 가장 최근 장바구니
    latest_list = ShoppingList.objects.filter(user=request.user).order_by('-created_at').first()
    if not latest_list:
        return render(request, 'food/save_no_ingredients.html')

    ingredients = ShoppingListIngredient.objects.filter(
        shopping_list=latest_list
    ).select_related('ingredient')

    return render(request, 'food/save_recent_ingredients.html', {
        'ingredients': ingredients,
    })


# ------ 3. 남은 식재료로 요리 추천받기 ------

@login_required
def find_recipes_with_gpt(request):
    if request.method == 'POST':
        selected = request.POST.getlist('ingredient_ids')
        ingredients = Ingredient.objects.filter(id__in=selected)
        names = [i.name for i in ingredients]
        ingredient_names = Ingredient.objects.values_list('name', flat=True)
        ingredient_list_str = ', '.join(ingredient_names)

        try:
            result = generate_recipe_with_ingredients(names, ingredient_list_str)
        except Exception as e:
            messages.error(request, f"AI 응답 실패: {e}")
            return redirect('food:show_recent_ingredients')

        lines = [line.strip() for line in result.splitlines() if line.strip()]
        title = lines[0].strip() if lines else "추천 요리"

        SavedRecipe.objects.create(
            user=request.user,
            title=title,
            description=result
        )

        return render(request, 'food/save_gpt_recipe_result.html', {
            'result': result,
            'title': title
        })

    return redirect('food:show_recent_ingredients')
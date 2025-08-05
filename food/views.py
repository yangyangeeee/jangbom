from django.shortcuts import render, redirect, get_object_or_404
from .ai import *
from .models import *
from market.models import ShoppingList, ShoppingListIngredient
from django.contrib import messages
from django.db.models import Q
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.urls import reverse
from django.conf import settings
import json
from openai import OpenAI



# ---------- 유틸 함수 ---------- (추후 util.py로 나눌 예정)

# 유저의 '진행 중인 장바구니'가 있으면 가져오고, 없으면 새로 생성
def get_or_create_active_shopping_list(user, from_main=False):
    shopping_list = ShoppingList.objects.filter(user=user, is_done=False).first()

    # from_main으로 접근했으면 기존 장바구니 종료 후 새로 생성
    if from_main:
        if shopping_list:
            shopping_list.is_done = True
            shopping_list.save()
        shopping_list = ShoppingList.objects.create(user=user)

    # 기존 로직 유지
    elif not shopping_list:
        shopping_list = ShoppingList.objects.create(user=user)

    return shopping_list

# 특정 장바구니에 포함된 재료들을 이름순으로 정렬해 반환
def get_shopping_list_ingredients(shopping_list):
    return Ingredient.objects.filter(shoppinglistingredient__shopping_list=shopping_list).order_by('name')

# 장바구니에 재료 이름 리스트를 추가하고, 추가된 재료 목록(이름 + 이미지)을 반환
def add_ingredients_to_list(shopping_list, ingredient_names):
    added = []
    for name in ingredient_names:
        # 재료가 없으면 새로 생성
        ing, _ = Ingredient.objects.get_or_create(name=name)
        # 이미 추가되어 있지 않으면 장바구니에 추가
        if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ing).exists():
            ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ing)
        # 재료 이름과 이미지 URL을 추가 목록에 저장
        image_url = ing.image.url if ing.image else None
        added.append({'name': ing.name, 'image_url': image_url})
    return added

# 모든 재료 이름을 문자열로 나열
ingredient_names = Ingredient.objects.values_list('name', flat=True)
ingredient_list_str = ', '.join(ingredient_names)


# ---------- 뷰 함수 ----------

def main(request):
    user = request.user

    # 가장 최근의 완료되지 않은 장바구니
    shopping_list = ShoppingList.objects.filter(user=user, is_done=False).order_by('-created_at').first()

    warn = False
    if shopping_list and shopping_list.shoppinglistingredient_set.exists():
        warn = True  # 경고 메시지 띄움

    return render(request, 'food/main.html', {
        'warn': warn,
        'shoppinglist_id': shopping_list.id if shopping_list else None
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
def recipe_ingredient_result(request):
    recipe_name = request.GET.get('recipe') or request.session.get('recipe_input')
    if not recipe_name:
        return redirect('food:recipe_input')
    
    # 세션에 저장된 재료가 있으면 GPT 분석 건너뜀 (빈 리스트면 다시 분석)
    basic_filtered = request.session.get('basic')
    optional_filtered = request.session.get('optional')

    if not basic_filtered or not optional_filtered or \
        (len(basic_filtered) == 0 and len(optional_filtered) == 0):

        basic_raw, optional_raw = extract_ingredients_from_recipe(recipe_name, ingredient_list_str)

        db_ingredients = Ingredient.objects.values_list('name', flat=True)
        basic_filtered = [i for i in basic_raw if i in db_ingredients]
        optional_filtered = [i for i in optional_raw if i in db_ingredients]

        request.session['basic'] = basic_filtered
        request.session['optional'] = optional_filtered

    return render(request, 'food/recipe_ingredients.html', {
        'recipe': recipe_name,
        'basic': basic_filtered,
        'optional': optional_filtered,
        'extra_ingredients': request.session.get('extra_ingredients', []),
    })


# Step 3. 장바구니 저장
@login_required
def confirm_shopping_list(request):
    selected = request.POST.getlist('ingredients')     # 체크된 것만 들어옴
    shopping_list = get_or_create_active_shopping_list(request.user)
    added = add_ingredients_to_list(shopping_list, selected)     

    request.session['shopping_list_id'] = shopping_list.id

    return render(request, 'food/recipe_result.html', {
        'shopping_list': shopping_list,
        'ingredients': added,
        'extra_ingredients': request.session.get('extra_ingredients', [])
    })


# Step 4. 장바구니 결과 보여주기
@login_required
def recipe_result_view(request):
    list_id = request.session.get('shopping_list_id')
    shopping_list = get_object_or_404(ShoppingList, id=list_id, user=request.user)
    ingredients = get_shopping_list_ingredients(shopping_list)

    return render(request, 'food/recipe_result.html', {'shopping_list': shopping_list, 'ingredients': ingredients})

def recipe_ai(request):
    if 'reset' in request.GET:
        request.session.flush()
        return redirect('food:recipe_ai')      # 모든 세션 초기화

    # 대화 세션 초기화
    if 'chat_history' not in request.session:

        request.session['chat_history'] = [{
            "role": "system",
            "content": (
                "넌 사용자의 기분과 상황을 듣고 요리를 제안하는 친절한 요리 도우미야."
                "사용자가 요리나 식사에 대해 고민을 이야기하면 반드시 **하나의 요리**만 추천해줘."
                "요리명은 반드시 큰따옴표(\") 안에 넣어서 말해. 예: 추천 요리: \"된장찌개\"\n"
                "간단한 설명과 함께 필요한 재료들 포함해주고, 요리는 하나만 추천해."
                f"요리는 꼭 우리가 가지고 있는 재료 DB로만 만들 수 있는 요리를 추천해야돼. 가지고 있는 재료 DB:\\n{ingredient_list_str}"
            )
        }]

    if request.method == 'POST':
        user_msg = request.POST.get('message')
        # 사용자 메시지 저장
        request.session['chat_history'].append({"role": "user", "content": user_msg})
        # GPT 응답
        gpt_reply = gpt_conversational_cook(request.session['chat_history'])
        # GPT 메시지 추가
        request.session['chat_history'].append({"role": "assistant", "content": gpt_reply})
        request.session.modified = True
        # 최신 GPT 응답 1개만 분석
        request.session['latest_recipe'] = extract_recipe_name_from_gpt_response(gpt_reply)

    return render(request, 'food/recipe_ai.html', {
        'chat_history': request.session['chat_history'],
        'latest_recipe': request.session.get('latest_recipe')
    })


# ------ 2. 식재료를 고를거야  ------

# Step 1. 식재료 검색하는 화면
@login_required
def ingredient_input_view(request):
    # 현재 로그인한 사용자
    user = request.user

    # 검색어 및 선택된 카테고리 정보 가져오기
    search_query = request.GET.get('search', '').strip()
    selected_category = request.GET.get('category', '').strip()
    from_main = request.GET.get('from') == 'main'

    if from_main:
        request.session['from'] = 'main'  # 뒤로가기 시에도 유지되도록 세션에 저장

    # 모든 카테고리 불러오기 (정렬 포함)
    categories = Category.objects.all().order_by('name')

    # 사용자의 활성 쇼핑리스트 가져오기 (없으면 생성)
    shopping_list = get_or_create_active_shopping_list(user)
    selected_ingredients = get_shopping_list_ingredients(shopping_list)
    # 세션에 직접 추가한 재료 이름 목록 저장 (어떤 경로에서 들어오든 항상/'recipe : 직접 재료 추가하기'에서 사용)
    request.session['extra_ingredients'] = [i.name for i in selected_ingredients]

    # 검색어가 있을 경우 해당 이름이 포함된 재료 필터링
    if search_query:
        ingredients = Ingredient.objects.filter(name__icontains=search_query).order_by('name')
        if ingredients.exists():
            messages.success(request, f"'{search_query}' 관련 검색 결과입니다.")
        else:
            messages.error(request, f"'{search_query}'과(와) 관련된 재료가 없습니다.")
    # 카테고리 필터링
    elif selected_category:
        ingredients = Ingredient.objects.filter(category__name=selected_category).order_by('name')
    # 아무 조건 없으면 전체 재료 출력
    else:
        ingredients = Ingredient.objects.all().order_by('name')

    # 템플릿 렌더링
    return render(request, 'food/ingredient_input.html', {
        'selected_category': selected_category,
        'search_query': search_query,
        'category_ingredients': ingredients,
        'categories': categories,
        'selected_ingredients': selected_ingredients,
        'from_main': from_main,
    })


# Step 1-1. 원하는 식재료 장바구니에 추가하기
@login_required
def add_ingredient(request):
    if request.method == 'POST':
        name = request.POST.get('ingredient', '').strip()
        selected_category = request.POST.get('category', '').strip()
        from_main = request.POST.get('from') == 'main'
        user = request.user

        if len(name) < 1:
            messages.error(request, "내용을 입력해 주세요.")
        else:
            try:
                ingredient = Ingredient.objects.get(name=name)

                # 세션에 있는 shopping_list_id 우선 사용하되, 실제 존재하지 않으면 새로 생성
                list_id = request.session.get('shopping_list_id')
                shopping_list = None
                if list_id:
                    try:
                        shopping_list = ShoppingList.objects.get(id=list_id, user=user)
                    except ShoppingList.DoesNotExist:
                        shopping_list = None
                if not shopping_list:
                    shopping_list = get_or_create_active_shopping_list(user)
                    request.session['shopping_list_id'] = shopping_list.id

                if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ingredient).exists():
                    ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ingredient)
                else:
                    messages.info(request, f"{name}은(는) 이미 추가되어 있어요.")
            except Ingredient.DoesNotExist:
                messages.error(request, f"{name}은(는) 마트에서 판매하지 않습니다.")

        query_params = {}
        if selected_category:
            query_params['category'] = selected_category
        if from_main:
            query_params['from'] = 'main'
        query_string = urlencode(query_params)

        return redirect(f"{reverse('food:ingredient_input')}?{query_string}" if query_string else 'food:ingredient_input')

    return redirect('food:ingredient_input')

# Step 1-2. 장바구니에 담은 식재료 제거하기
@login_required
def delete_ingredient(request, name):
    if request.method == 'POST':
        from_main = request.POST.get('from') == 'main'  # from=main 유지 여부 확인
        try:
            # 재료 객체 찾고 장바구니에서 제거
            ingredient = Ingredient.objects.get(name=name)
            shopping_list = get_or_create_active_shopping_list(request.user)
            ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ingredient).delete()
        except Ingredient.DoesNotExist:
            messages.error(request, f"{name}은(는) 존재하지 않습니다.")

        # from=main 유지 리디렉션
        return redirect(f"{reverse('food:ingredient_input')}?from=main") if from_main else redirect('food:ingredient_input')

    return redirect('food:ingredient_input')


# Step 2. 장바구니에 담은 식재료 모아보기
@login_required
def ingredient_result_view(request):
    user = request.user

    # 'from=main' 여부 확인 (GET 또는 세션)
    from_main = request.GET.get('from') == 'main' or request.session.get('from') == 'main'
    if from_main:
        request.session['from'] = 'main'  # 세션에 저장 (뒤로가기로도 유지되게)

    # 세션에 저장된 쇼핑리스트 ID로 장바구니 불러오되, 없거나 잘못된 ID일 경우 새로 생성
    shopping_list = None
    list_id = request.session.get('shopping_list_id')
    if list_id:
        try:
            shopping_list = ShoppingList.objects.get(id=list_id, user=user)
        except ShoppingList.DoesNotExist:
            shopping_list = None

    # 없으면 생성
    if not shopping_list:
        shopping_list = get_or_create_active_shopping_list(user, from_main=from_main)
        request.session['shopping_list_id'] = shopping_list.id  # 세션 갱신

    # 기존 장바구니에 재료가 있어도 새 장바구니 만들던 로직 제거 → 장바구니 초기화 문제 해결

    return render(request, 'food/ingredient_result.html', {
        'shopping_list': shopping_list,
        'from_main': from_main
    })

# Step 3. 선택한 식재료의 요리 추천받기(AI활용)
@login_required
def ingredient_ai_view(request, name):

    # AI API를 통해 요리 추천 요청
    result = get_recipes_using_ingredient(name, ingredient_list_str)

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
def add_ingredient_ai(request):
    if request.method == "POST":
        selected_names = request.POST.getlist("ingredients")
        selected_ingredients = Ingredient.objects.filter(name__in=selected_names)

        shopping_list = get_or_create_active_shopping_list(request.user)

        for ingredient in selected_ingredients:
            ShoppingListIngredient.objects.get_or_create(
                shopping_list=shopping_list,
                ingredient=ingredient
            )

        request.session['shopping_list_id'] = shopping_list.id

    return redirect('food:ingredient_result')

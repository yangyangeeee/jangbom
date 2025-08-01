from django.shortcuts import render, redirect, get_object_or_404
from .ai import extract_ingredients_from_recipe, gpt_conversational_cook, extract_recipe_name_from_gpt_response
from .models import *
from django.contrib.auth.decorators import login_required

# Create your views here.
def main(request):
    return render(request, 'food/main.html')

# Step 1. 요리 입력
def recipe_input_view(request):
    initial_recipe = request.GET.get('recipe', '')  # GPT에서 넘겨준 요리명 (없으면 빈 문자열)

    if request.method == 'POST':
        recipe_name = request.POST.get('recipe')
        request.session['recipe_input'] = recipe_name
        return redirect('food:recipe_ingredients')
    
    return render(request, 'food/recipe_input.html', {'initial_recipe': initial_recipe})

# Step 2. GPT 분석 결과 보여주기
def recipe_ingredient_result(request):
    recipe_name = request.GET.get('recipe') or request.session.get('recipe_input')

    if not recipe_name:
        return redirect('food:recipe_input')

    # 세션에 저장된 재료가 있으면 GPT 분석 건너뜀
    basic_filtered = request.session.get('basic')
    optional_filtered = request.session.get('optional')

    if not basic_filtered or not optional_filtered:
        # GPT 재료 분석
        basic_raw, optional_raw = extract_ingredients_from_recipe(recipe_name)

        # DB에 존재하는 재료만 필터링
        db_ingredients = Ingredient.objects.values_list('name', flat=True)

        basic_filtered = [i for i in basic_raw if i in db_ingredients]
        optional_filtered = [i for i in optional_raw if i in db_ingredients]

        # 세션 저장 (한 번만)
        request.session['basic'] = basic_filtered
        request.session['optional'] = optional_filtered

    # 검색에서 추가한 재료는 따로 유지
    extra_ingredients = request.session.get('extra_ingredients', [])

    return render(request, 'food/recipe_ingredients.html', {
        'recipe': recipe_name,
        'basic': basic_filtered,
        'optional': optional_filtered,
        'extra_ingredients': extra_ingredients,
    })

# Step 2. 직접 재료 검색 & 선택
def ingredient_search_view(request):
    # 기존 선택 재료 가져오기 (세션 or GET)
    selected = request.session.get('search_selected', [])

    # 사용자가 '추가 완료' 눌렀을 때
    if request.method == 'POST':
        selected = request.POST.getlist('ingredients')
        request.session['extra_ingredients'] = selected
        request.session['search_selected'] = []
        return redirect('food:recipe_ingredients')

    # 검색 시: 새 재료 자동 추가
    query = request.GET.get('q', '')
    if query:
        # DB에서 재료 검색
        ingredients = Ingredient.objects.filter(name__icontains=query)
        for ing in ingredients:
            if ing.name not in selected:
                selected.append(ing.name)

    # 선택 재료 누적 저장
    request.session['search_selected'] = selected

    return render(request, 'food/ingredient_search.html', {
        'query': query,
        'selected': selected,
    })

# Step 3. 장바구니 저장
@login_required
def confirm_shopping_list(request):
    selected = request.POST.getlist('ingredients')  # 체크된 것만 들어옴

    # 로그인된 사용자로 장바구니 생성
    shopping_list = ShoppingList.objects.create(
        user=request.user,
        destination="미지정"
    )

    for name in selected:
        ing, _ = Ingredient.objects.get_or_create(name=name)

        # 중복 방지: 이미 이 재료가 장바구니에 있는지 확인
        if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ing).exists():
            ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ing)


    request.session['shopping_list_id'] = shopping_list.id
    request.session['extra_ingredients'] = []  # 직접 추가했던 재료 초기화
    request.session['search_selected'] = []  # 검색 상태 초기화

    return redirect('food:shopping_list_result')


# Step 4. 장바구니 결과 보여주기
@login_required
def shopping_list_result(request):
    list_id = request.session.get('shopping_list_id')
    shopping_list = get_object_or_404(ShoppingList, id=list_id, user=request.user)

    return render(request, 'food/shopping_list_result.html', {
        'shopping_list': shopping_list,
    })

def chat_with_gpt(request):
    if 'reset' in request.GET:
        request.session.flush()  # 모든 세션 초기화
        return redirect('food:chat')

    # 대화 세션 초기화
    if 'chat_history' not in request.session:
        request.session['chat_history'] = [
            {
                "role": "system",
                "content": (
                    "넌 사용자의 기분과 상황을 듣고 요리를 제안하는 친절한 요리 도우미야. "
                    "사용자가 요리나 식사에 대해 고민을 이야기하면 반드시 **하나의 요리**만 추천해줘. "
                    "요리명은 반드시 큰따옴표(\") 안에 넣어서 말해. 예: 추천 요리: \"된장찌개\"\n"
                    "간단한 설명과 함께 필요한 재료들 포함해주고, 요리는 하나만 추천해."
                )
            }
        ]

    if request.method == 'POST':
        user_msg = request.POST.get('message')

        # 사용자 메시지 저장
        request.session['chat_history'].append({
            "role": "user",
            "content": user_msg
        })

        # GPT 응답
        gpt_reply = gpt_conversational_cook(request.session['chat_history'])

        # GPT 메시지 추가
        request.session['chat_history'].append({
            "role": "assistant",
            "content": gpt_reply
        })

        request.session.modified = True

        # 최신 GPT 응답 1개만 분석
        recipe_name = extract_recipe_name_from_gpt_response(gpt_reply)
        request.session['latest_recipe'] = recipe_name  # 저장해두기

    return render(request, 'food/chat.html', {
        'chat_history': request.session['chat_history'],
        'latest_recipe': request.session.get('latest_recipe')
    })
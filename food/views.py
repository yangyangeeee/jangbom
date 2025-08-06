import json
from django.shortcuts import render, redirect, get_object_or_404
from .ai import *
from .models import *
from market.models import ShoppingList, ShoppingListIngredient
from django.contrib import messages
from django.db.models import Q
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.conf import settings
from openai import OpenAI

def main(request):
    return render(request, 'food/main.html')

# 1. 요리를 할거야
# 요리 입력
def recipe_input_view(request):
    initial_recipe = request.GET.get('recipe', '')  # GPT에서 넘겨준 요리명 (없으면 빈 문자열)

    if request.method == 'POST':
        recipe_name = request.POST.get('recipe')
        request.session['recipe_input'] = recipe_name
        return redirect('food:recipe_ingredients')
    
    return render(request, 'food/recipe_input.html', {'initial_recipe': initial_recipe})

# GPT 분석 결과 보여주기
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

# 직접 재료 검색 & 선택
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

# 장바구니 저장
@login_required
def confirm_shopping_list(request):
    selected = request.POST.getlist('ingredients')  # 체크된 것만 들어옴

    # 로그인된 사용자로 장바구니 생성
    shopping_list = ShoppingList.objects.create(user=request.user)

    added_ingredients = []  # 템플릿에 넘기기 위한 데이터 저장 리스트

    for name in selected:
        ing, _ = Ingredient.objects.get_or_create(name=name)

        # 중복 방지: 이미 이 재료가 장바구니에 있는지 확인
        if not ShoppingListIngredient.objects.filter(shopping_list=shopping_list, ingredient=ing).exists():
            ShoppingListIngredient.objects.create(shopping_list=shopping_list, ingredient=ing)

        # 이미지 URL 추가 (이미지 없으면 None)
        image_url = ing.image.url if ing.image else None
        added_ingredients.append({'name': ing.name, 'image_url': image_url})

    request.session['shopping_list_id'] = shopping_list.id
    request.session['extra_ingredients'] = []  # 직접 추가했던 재료 초기화
    request.session['search_selected'] = []  # 검색 상태 초기화

    return render(request, 'food/recipe_result.html', {
    'shopping_list': shopping_list,
    'ingredients': added_ingredients
})


# 장바구니 결과 보여주기
@login_required
def recipe_result_view(request):
    list_id = request.session.get('shopping_list_id')
    shopping_list = get_object_or_404(ShoppingList, id=list_id, user=request.user)

    return render(request, 'food/recipe_result.html', {
        'shopping_list': shopping_list,
    })

def recipe_ai(request):
    if 'reset' in request.GET:
        keys_to_clear = [
            'recipe_input',
            'basic',
            'optional',
            'extra_ingredients',
            'search_selected',
            'chat_history',
            'latest_recipe',
            'shopping_list_id'
        ]
        for key in keys_to_clear:
            request.session.pop(key, None)
        return redirect('food:recipe_ai')

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

    return render(request, 'food/recipe_ai.html', {
        'chat_history': request.session['chat_history'],
        'latest_recipe': request.session.get('latest_recipe')
    })


# 2. 식재료를 고를거야
@login_required
def ingredient_input_view(request):
    user = request.user
    search_query = request.GET.get('search', '').strip()
    selected_category = request.GET.get('category', '').strip()

    categories = Category.objects.all().order_by('name')

    # 유저의 가장 최근 ShoppingList 가져오기 (없으면 생성)
    shopping_list, _ = ShoppingList.objects.get_or_create(user=user)

    # 장바구니에 담긴 재료들 불러오기
    selected_ingredients = Ingredient.objects.filter(
        shoppinglistingredient__shopping_list=shopping_list
    ).order_by('name')

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

@login_required
def add_ingredient(request):
    if request.method == 'POST':
        name = request.POST.get('ingredient', '').strip()
        selected_category = request.POST.get('category', '').strip()
        user = request.user

        if len(name) < 1:
            messages.error(request, "내용을 입력해 주세요.")
        else:
            try:
                ingredient = Ingredient.objects.get(name=name)

                # 유저의 쇼핑리스트 가져오기 또는 생성
                shopping_list, _ = ShoppingList.objects.get_or_create(user=user)

                # 이미 추가된 재료인지 확인
                already_exists = ShoppingListIngredient.objects.filter(
                    shopping_list=shopping_list,
                    ingredient=ingredient
                ).exists()

                if not already_exists:
                    ShoppingListIngredient.objects.create(
                        shopping_list=shopping_list,
                        ingredient=ingredient
                    )
                else:
                    messages.info(request, f"{name}은(는) 이미 추가되어 있어요.")
            except Ingredient.DoesNotExist:
                messages.error(request, f"{name}은(는) 마트에서 판매하지 않습니다.")

        # 리디렉션 시 선택된 카테고리를 포함해서 보냄
        base_url = reverse('food:ingredient_input')
        query_string = urlencode({'category': selected_category}) if selected_category else ''
        url = f"{base_url}?{query_string}" if query_string else base_url
        return redirect(url)

    return redirect('food:ingredient_input')

@login_required
def delete_ingredient(request, name):
    if request.method == 'POST':
        user = request.user
        try:
            ingredient = Ingredient.objects.get(name=name)
            shopping_list, _ = ShoppingList.objects.get_or_create(user=user)

            # 해당 재료가 장바구니에 있는 경우 삭제
            ShoppingListIngredient.objects.filter(
                shopping_list=shopping_list,
                ingredient=ingredient
            ).delete()
        except Ingredient.DoesNotExist:
            messages.error(request, f"{name}은(는) 존재하지 않습니다.")

    return redirect('food:ingredient_input')

@login_required
def ingredient_result_view(request):
    list_id = request.session.get('shopping_list_id')
    
    if list_id:
        shopping_list = get_object_or_404(ShoppingList, id=list_id, user=request.user)
    else:
        # 없을 경우 가장 최근 리스트를 보여주거나 새로 생성
        shopping_list, _ = ShoppingList.objects.get_or_create(user=request.user)

    return render(request, 'food/ingredient_result.html', {
        'shopping_list': shopping_list
    })

client = OpenAI(api_key=settings.OPENAI_API_KEY)

@login_required
def ingredient_ai_view(request, name):
    # DB 재료 목록 추출
    ingredient_names = Ingredient.objects.values_list('name', flat=True)
    ingredient_list_str = ', '.join(ingredient_names)

    # GPT 프롬프트 구성 (tip 제거됨)
    prompt = (
        f"'{name}'에 대해 아래 형식의 JSON으로만 응답해줘. 다른 설명, 인사말, 공백, 줄바꿈 없이 JSON 데이터만 줘.\n\n"
        f"조건:\n"
        f"- 'recipes'는 요리 2개를 추천. 각각:\n"
        f"  • name: 요리 이름\n"
        f"  • description: 간단한 요리 설명(100자 이내) 말투는 조금 귀엽게\n"
        f"  • ingredients: 해당 요리에 필요한 재료들. 우리 재료 DB 내에서만 선택해서 3~6개. 단 {name}은 제외하고 나머지 재료들만 출력 필수\n\n"
        f"사용 가능한 재료 목록:\n{ingredient_list_str}\n\n"
        f"JSON 형식 예시는 아래와 같아. 반드시 이와 똑같은 키 이름을 쓰고, 형식은 변형하지 마.:\n\n"
        f"{{\n"
        f'  "recipes": [\n'
        f'    {{\n'
        f'      "name": "요리 이름",\n'
        f'      "description": "간단한 설명",\n'
        f'      "ingredients": ["재료1", "재료2", "..."]\n'
        f'    }},\n'
        f'    {{\n'
        f'      "name": "요리 이름",\n'
        f'      "description": "간단한 설명",\n'
        f'      "ingredients": ["재료1", "재료2", "..."]\n'
        f'    }}\n'
        f'  ]\n'
        f"}}\n\n"
        f"다시 말하지만, 반드시 JSON만 출력해줘. JSON 외 다른 텍스트는 포함하지 마!"
    )

    try:
        chat_completion = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        ai_reply = chat_completion.choices[0].message.content
        recipes_data = json.loads(ai_reply)["recipes"]
    except Exception as e:
        ai_reply = f"AI 응답 실패: {e}"
        recipes_data = []

    request.session['last_ai_reply'] = ai_reply
    request.session['last_ingredient_name'] = name

    return render(request, 'food/ingredient_ai.html', {
        'ingredient_name': name,
        'recipes': recipes_data,
    })


@login_required
def add_ingredient_ai(request):
    if request.method == "POST":
        selected_names = request.POST.getlist("ingredients")

        # 유효한 재료만 필터링
        selected_ingredients = Ingredient.objects.filter(name__in=selected_names)

        # 현재 유저의 쇼핑리스트 (없으면 생성)
        shopping_list, _ = ShoppingList.objects.get_or_create(user=request.user)

        for ingredient in selected_ingredients:
            # 중복 방지: 이미 있으면 추가 안함
            ShoppingListIngredient.objects.get_or_create(
                shopping_list=shopping_list,
                ingredient=ingredient
            )

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


@login_required
def find_recipes_with_gpt(request):
    if request.method == 'POST':
        selected = request.POST.getlist('ingredient_ids')
        ingredients = Ingredient.objects.filter(id__in=selected)
        names = [i.name for i in ingredients]

        prompt = (
            f"다음 재료를 활용한 간단한 요리법을 추천해줘: {', '.join(names)}. "
            "아래 형식을 반드시 지켜줘:\n\n"
            "1. 첫 줄에는 요리 이름만 간결하게 써줘 (예: 달걀볶음밥)\n"
            "2. 두 번째 줄부터는 '필요한 재료:' 라고 적고, 사용할 재료 목록을 써줘\n"
            "3. 그 다음에는 '조리 방법:'이라고 적고, 총 5단계로 나눠서 설명해줘\n"
            "4. 말투는 친절하고 초보자도 이해하기 쉽게 써줘\n"
            "5. 다른 말은 하지 말고 위 형식만 지켜줘"
        )

        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "넌 사용자의 재료를 활용해 요리를 추천하는 요리 전문가야."},
                    {"role": "user", "content": prompt}
                ]
            )
            result = response.choices[0].message.content.strip()
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
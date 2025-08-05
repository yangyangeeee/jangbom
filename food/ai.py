import re, json
from openai import OpenAI
from django.conf import settings
from .models import Ingredient

client = OpenAI(api_key=settings.OPENAI_API_KEY)


# ------ 1. 요리를 할거야  ------
def extract_ingredients_from_recipe(recipe_name, ingredient_list_str):
    ingredient_names = Ingredient.objects.values_list('name', flat=True)
    ingredient_list_str = ', '.join(ingredient_names)
    prompt = f"""
    "{recipe_name}"를 만들기 위해 필요한 식재료를 기본 재료와 선택 재료로 나눠서 알려줘. 
    예: 기본 재료: 된장, 두부 / 선택 재료: 고추, 소고기
    우리 재료 DB 내에서만 꼭 선택해줘. 사용 가능한 재료 목록:\\n{ingredient_list_str}
    기본 재료의 추천 재료 개수는 4~6개, 선택 재료의 추천 재료 개수는 1~3개로 해줘. 그 이상으로 추천해주마 추천한 재료가 너무 많으면 안돼.
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    content = response.choices[0].message.content

    basic, optional = [], []
    for line in content.split('\n'):
        if "기본" in line and ':' in line:
            basic = [i.strip() for i in line.split(':')[1].split(',')]
        elif "선택" in line and ':' in line:
            optional = [i.strip() for i in line.split(':')[1].split(',')]
    return basic, optional

def gpt_conversational_cook(chat_history):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=chat_history,
        temperature=0.7,
    )
    return response.choices[0].message.content

# 요리명 추출 함수 추가
def extract_recipe_name_from_gpt_response(text):
    # 큰따옴표(" ~ ") 안에 있는 내용만 추출
    match = re.search(r'["“](.+?)["”]', text)
    if match:
        return match.group(1).strip()
    return None


# ------ 2. 식재료를 구할거야  ------
def get_recipes_using_ingredient(name, ingredient_list_str):
    prompt = (
        f"'{name}'에 대해 아래 형식의 JSON으로만 응답해줘. 다른 설명, 인사말, 공백, 줄바꿈 없이 JSON 데이터만 줘.\\n\\n"
        f"조건:\\n- 'recipes'는 요리 2개를 추천. 각각:\\n  • name: 요리 이름\\n  • description: 간단한 요리 설명(100자 이내) 말투는 조금 귀엽게\\n"
        f"  • ingredients: 해당 요리에 필요한 재료들. 우리 재료 DB 내에서만 선택해서 3~6개. 단 {name}은 제외하고 나머지 재료들만 출력 필수\\n\\n"
        f"사용 가능한 재료 목록:\\n{ingredient_list_str}\\n\\n"
        f"JSON 형식 예시는 아래와 같아. 반드시 이와 똑같은 키 이름을 쓰고, 형식은 변형하지 마.:\\n\\n"
        f"{{\\n  \\\"recipes\\\": [\\n    {{\\n      \\\"name\\\": \\\"요리 이름\\\",\\n      \\\"description\\\": \\\"간단한 설명\\\",\\n      \\\"ingredients\\\": [\\\"재료1\\\", \\\"재료2\\\"]\\n    }},\\n    {{\\n      \\\"name\\\": \\\"요리 이름\\\",\\n      \\\"description\\\": \\\"간단한 설명\\\",\\n      \\\"ingredients\\\": [\\\"재료1\\\", \\\"재료2\\\"]\\n    }}\\n  ]\\n}}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return json.loads(response.choices[0].message.content)["recipes"]
    except Exception as e:
        return f"AI 응답 실패: {e}"
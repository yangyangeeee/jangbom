import re, json
from openai import OpenAI
from django.conf import settings
from .models import Ingredient

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def _safe_json(content: str):
    """모델이 JSON 외 텍스트를 섞어 보내도 최대한 파싱."""
    # 1) 순수 시도
    try:
        return json.loads(content)
    except Exception:
        pass
    # 2) 본문에서 가장 바깥쪽 {...} 추출
    m = re.search(r'\{.*\}', content, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ------ 1. 요리를 할거야  ------
def extract_ingredients_from_recipe(recipe_name):
    # 모든 재료 이름을 문자열로 나열
    ingredient_names = Ingredient.objects.values_list('name', flat=True)
    ingredient_list_str = ', '.join(ingredient_names)
    prompt = (
        f'"{recipe_name}"를 만들기 위해 필요한 식재료를 아래 JSON 형식으로만 응답해줘.'
        f'조건은 무조건 우리 재료 DB 내에서만 조합해서 "{recipe_name}"를 만들기 위해 필요한 식재료들을 추천해야 돼'
        f'우리 재료 DB:\\n{ingredient_list_str}'
        f'다른 설명, 인사말, 공백, 줄바꿈 없이 **JSON 데이터만** 줘.\n\n'
        f'조건:\n'
        f'- basic: 반드시 필요한 재료 목록 (예: 된장, 두부)\n'
        f'- optional: 선택적으로 넣을 수 있는 재료 목록 (예: 고추, 소고기)\n\n'
        f'응답 형식:\n'
        f'{{\n  "basic": ["된장", "두부"],\n  "optional": ["소고기", "고추"]\n}}'
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # 또는 gpt-3.5-turbo
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        content = response.choices[0].message.content.strip()

        data = json.loads(content)  # JSON 파싱
        return data.get("basic", []), data.get("optional", [])

    except json.JSONDecodeError:
        return [], []  # 파싱 실패 시 빈 리스트 반환
    except Exception as e:
        return [], []  # GPT 호출 실패 시도 빈 리스트 반환
    

def extract_ingredients_from_recipe_v2(recipe_name, allowed_ingredients=None):
    """
    - recipe_name: 요리 이름 (필수)
    - allowed_ingredients: DB에 존재하는 재료 이름 리스트 (선택)
    - 반환: (basic:list[str], optional:list[str])
    - GPT는 JSON으로만 응답하도록 강제
    """
    allowed_block = ""
    if allowed_ingredients:
        allowed_block = (
            "\n사용 가능한 재료 목록(이 중에서만 선택):\n" +
            ", ".join(allowed_ingredients)
        )

    prompt = (
        f'"{recipe_name}"를 만들기 위한 재료를 아래 JSON 형식으로만 응답해줘. '
        f'다른 설명, 인사말, 공백 없이 **JSON 데이터만** 줘.\n\n'
        f'응답 형식 예시:\n'
        '{\n  "basic": ["재료1","재료2"],\n  "optional": ["재료3","재료4"]\n}\n'
        f'{allowed_block}'
    )

    try:
        res = client.chat.completions.create(
            model="gpt-4o",      
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = res.choices[0].message.content.strip()
        data = json.loads(content)
        basic = data.get("basic", [])
        optional = data.get("optional", [])
        # 문자열만 남기고 정리
        basic = [str(x).strip() for x in basic if isinstance(x, (str, int, float))]
        optional = [str(x).strip() for x in optional if isinstance(x, (str, int, float))]
        return basic, optional
    except Exception:
        # v2 실패 시 빈 리스트 반환 (뷰에서 v1로 폴백)
        return [], []
    

def gpt_conversational_cook(chat_history):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
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
def get_recipes_using_ingredient(name):
    # DB 재료 목록 문자열 (너무 길면 필요 재료만 보내도록 줄이세요)
    ingredient_names = list(Ingredient.objects.values_list('name', flat=True))
    ingredient_list_str = ', '.join(ingredient_names)

    prompt = (
        f"재료 '{name}'로 만들 수 있는 요리 2개를 추천해줘.\n\n"
        f"다음 형식의 JSON으로만 답변해. 다른 텍스트, 인사말, 설명 금지:\n"
        f'{{"recipes":[{{"name":"요리명","description":"100자 이내","ingredients":["재료A","재료B"]}},'
        f'{{"name":"요리명","description":"100자 이내","ingredients":["재료A","재료B"]}}]}}\n\n'
        f"- ingredients 항목은 우리 재료 DB 목록에서만 3~6개 고르고, 반드시 '{name}'는 제외해.\n"
        f"- 사용할 수 있는 재료 목록:\n{ingredient_list_str}\n"
    )

    try:
        # JSON 모드 강제
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = _safe_json(content)
        if not data or "recipes" not in data:
            raise ValueError("모델 응답이 JSON 형식이 아님")
        # 최소 검증
        recipes = data.get("recipes") or []
        # 문자열로 통일
        norm = []
        for r in recipes:
            norm.append({
                "name": str(r.get("name", "")).strip(),
                "description": str(r.get("description", "")).strip(),
                "ingredients": [str(x).strip() for x in (r.get("ingredients") or [])]
            })
        return norm
    except Exception as e:
        return f"AI 응답 실패: {e}"
    

# ------ 3. 남은 식재료로 요리 추천받기 ------
def generate_recipe_with_ingredients(selected_names, ingredient_db_list):
    prompt = (
        f"다음 재료를 활용한 간단한 요리법을 추천해줘: {', '.join(selected_names)}. "
        "아래 형식을 반드시 지켜줘:\n\n"
        "1. 첫 줄에는 요리 이름만 간결하게 써줘 (예: 달걀볶음밥)\n"
        "2. 두 번째 줄부터는 '필요한 재료:' 라고 적고, 사용할 재료 목록을 써줘\n"
        f"내가 넘겨주는 DB 식재료들로만 조합해서 요리를 추천해줘. 전체 식재료 DB 목록:\\n{ingredient_db_list}\\n"
        "3. 그 다음에는 '조리 방법:'이라고 적고, 총 5단계로 나눠서 설명해줘\n"
        "4. 말투는 친절하고 초보자도 이해하기 쉽게 써줘\n"
        "5. 다른 말은 하지 말고 위 형식만 지켜줘"
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "넌 사용자의 재료를 활용해 요리를 추천하는 요리 전문가야."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()
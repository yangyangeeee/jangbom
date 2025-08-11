import re, json
from typing import List
import os, time
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
        model="gpt-4o",
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
def _build_prompt(selected_names: List[str], ingredient_db_list: str) -> str:
    max_chars = 8000
    safe_db = (ingredient_db_list or "")[:max_chars]
    return (
        f"다음 재료를 활용한 간단한 요리법을 추천해줘: {', '.join(selected_names)}.\n"
        "아래 형식을 반드시, 정확히 지켜줘. 다른 말은 절대 쓰지 마:\n\n"
        "1) 첫 줄: 요리 이름만 (예: 달걀볶음밥)\n"
        "2) 다음 줄부터 '필요한 재료:'\n"
        "   - 사용할 재료 목록을 줄바꿈으로 나열 (재료명만, 수량/단위는 쓰지 않기)\n"
        "   - 반드시 내가 넘겨준 DB 식재료들에서만 고르기.\n"
        "3) 다음에 '조리 방법:'\n"
        "   - 총 5단계 번호 목록으로 간결히 설명\n\n"
        "아래는 전체 식재료 DB 목록이야. 이 목록에 있는 재료만 써야 해.\n"
        f"{safe_db}\n"
    )

def generate_recipe_with_ingredients(selected_names: List[str], ingredient_db_list: str) -> str:
    if not selected_names:
        return "재료가 비어 있습니다."

    prompt = _build_prompt(selected_names, ingredient_db_list)

    for attempt in range(2):  # 0~1번 시도 (간단 재시도)
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                temperature=0.2,
                max_tokens=700,
                messages=[
                    {"role": "system",
                    "content": (
                        "넌 사용자가 가진 재료로 요리를 설계하는 한국어 요리 비서야. "
                        "요청 형식을 반드시 지켜야 하며, 사족을 절대 덧붙이지 마."
                    )},
                    {"role": "user", "content": prompt}
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise Exception("빈 응답")
            return text
        except Exception as e:
            if attempt == 1:
                raise RuntimeError(f"AI 응답 실패: {e}")
            time.sleep(0.8)  # 짧게 한 번만 대기 후 재시도
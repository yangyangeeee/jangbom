import re, json
from typing import List
import os, time
from openai import OpenAI
from django.conf import settings
from .models import Ingredient
from typing import List
import time

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
    

def extract_ingredients_from_recipe_v2(recipe_name, allowed_ingredients=None, model="gpt-4o"):
    """
    주어진 요리명으로 필요한 재료를 GPT에 물어보고 (basic, optional) 리스트를 돌려준다.
    - allowed_ingredients가 주어지면 그 목록에 '정규화 매핑'으로 매칭되는 항목만 반환.
    - 항상 문자열 리스트 2개를 반환하며, 실패 시 ([], []).
    """

    def norm(s: str) -> str:
        # 공백 제거 + 소문자화로 너그럽게 매칭
        return re.sub(r"\s+", "", str(s)).strip().casefold()

    # 허용 재료 매핑 (정규화된 키 -> 원본 DB명)
    allowed_map = None
    allowed_block = ""
    if allowed_ingredients:
        allowed_map = {norm(a): a for a in allowed_ingredients}
        allowed_block = "\n사용 가능한 재료 목록(이 중에서만 선택):\n" + ", ".join(allowed_ingredients)

    messages = [
        {
            "role": "system",
            "content": (
                "당신은 주어진 요리의 재료만을 JSON으로 반환하는 도우미입니다. "
                "설명/인사/코드블록/추가 텍스트 금지. 오직 JSON 오브젝트만 출력하세요."
            ),
        },
        {
            "role": "user",
            "content": (
                f'"{recipe_name}"를 만들기 위한 재료를 아래 JSON 형식으로만 응답해줘.\n'
                '응답 형식:\n{"basic": ["재료1","재료2"], "optional": ["재료3","재료4"]}\n'
                + allowed_block
            ),
        },
    ]

    try:
        res = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
        )
        content = (res.choices[0].message.content or "").strip()

        # ```json ... ``` 제거
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL)

        # 혹시 앞뒤에 잡텍스트가 섞였으면 첫 번째 JSON 오브젝트만 추출
        if not content.lstrip().startswith("{"):
            m = re.search(r"\{[\s\S]*\}", content)
            if m:
                content = m.group(0)

        data = json.loads(content)
    except Exception:
        return [], []

    def clean_list(x):
        if not isinstance(x, list):
            return []
        out, seen = [], set()
        for item in x:
            s = str(item).strip()
            if not s:
                continue
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    basic = clean_list(data.get("basic", []))
    optional = clean_list(data.get("optional", []))

    # 허용 재료 필터링 + DB 원본명으로 복구
    if allowed_map is not None:
        def map_and_filter(seq):
            mapped, seen = [], set()
            for item in seq:
                k = norm(item)
                if k in allowed_map:
                    val = allowed_map[k]
                    if val not in seen:
                        seen.add(val)
                        mapped.append(val)
            return mapped
        basic = map_and_filter(basic)
        optional = map_and_filter(optional)

    return basic, optional
    

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
def _all_ingredient_names() -> str:
    """DB의 전체 재료명을 줄바꿈으로 나열 (캐시 없이 실시간 반영)."""
    names = Ingredient.objects.values_list("name", flat=True).order_by("name")
    return "\n".join(names)

def _build_prompt(selected_names: List[str], ingredient_db_list: str, followup: str = "") -> str:
    max_chars = 8000
    safe_db = (ingredient_db_list or "")[:max_chars]
    base = (
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
    if followup.strip():
        base += f"\n[사용자 추가 요청]\n{followup.strip()}\n"
    return base

def call_gpt(selected_names: List[str], followup: str = "") -> str:
    """선택 재료 + (옵션) 후속요청을 넣어 완성 텍스트 반환."""
    prompt = _build_prompt(selected_names, _all_ingredient_names(), followup)
    system_msg = {
        "role": "system",
        "content": (
            "넌 사용자가 가진 재료로 요리를 설계하는 한국어 요리 비서야. "
            "요청 형식을 반드시 지켜야 하며, 사족을 절대 덧붙이지 마."
        ),
    }
    user_msg = {"role": "user", "content": prompt}

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                temperature=0.2,
                max_tokens=700,
                messages=[system_msg, user_msg],
            )
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise RuntimeError("빈 응답")
            return text
        except Exception as e:
            if attempt == 1:
                raise RuntimeError(f"AI 응답 실패: {e}")
            time.sleep(0.7)
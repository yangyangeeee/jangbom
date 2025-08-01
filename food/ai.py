import re
from openai import OpenAI
from django.conf import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def extract_ingredients_from_recipe(recipe_name):
    prompt = f"""
    "{recipe_name}"를 만들기 위해 필요한 식재료를 기본 재료와 선택 재료로 나눠서 알려줘. 
    예: 기본 재료: 된장, 두부 / 선택 재료: 고추, 소고기
    """

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
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
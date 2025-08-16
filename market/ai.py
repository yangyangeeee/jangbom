from django.conf import settings
from openai import OpenAI

AI_MODEL_TIPS = getattr(settings, "AI_MODEL_TIPS", "gpt-4o-mini")
AI_TEMPERATURE_DEFAULT = getattr(settings, "AI_TEMPERATURE_DEFAULT", 0.6)

client = OpenAI(api_key=settings.OPENAI_API_KEY)

def generate_tip_text(name: str, followup: str | None = None) -> str:
    # 형식 강제: 마크다운/기호 금지, 접두사 없이 문장만 줄바꿈으로
    system_prompt = (
        "너는 신선식품 구매 도우미야. 출력 형식을 반드시 지켜.\n"
        "형식: 줄마다 한 문장, 줄 앞에 어떤 기호도 붙이지 말 것(하이픈, 별표, 불릿, 번호 금지), "
        "마크다운 금지, 굵게 금지. 예:\n"
        "\n색: ...\n향: ...\n식감: ...\n크기: ...\n손상: ...\n벌레: ...\n보관법: ..."
    )
    if followup:
        user_prompt = f"{name}에 대해 사용자가 이렇게 물었어: '{followup}'. 3~6줄의 문장으로 답해줘."
    else:
        user_prompt = (
            f"{name} 구매 팁을 6~10줄로 제공해줘. "
            "색/향/식감 → 크기 → 손상/벌레 → 보관법 순서로, 각 줄은 접두사 없이 '주제: 설명' 문장으로."
        )

    resp = client.chat.completions.create(
        model=AI_MODEL_TIPS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=AI_TEMPERATURE_DEFAULT,
    )
    return (resp.choices[0].message.content or "").strip()

def generate_arrival_praises(market_name: str, dong: str | None, distance_m: int | None) -> list[str]:
    """
    도착 화면용 칭찬 문구 2줄 생성. 마크다운/불릿 없이 '문장만' 반환.
    """
    system_prompt = (
        "너는 한국어 카피라이터야. 아래 규칙을 지켜 두 줄짜리 문구를 만든다.\n"
        "- 출력은 정확히 두 줄\n"
        "- 각 줄 15~20자 사이, 존댓말, 끝에 마침표 없기\n"
        "- 각 줄은 문장이 아니라 '명사구(헤드라인/슬로건체)'로 작성\n"
        "- 불릿/번호/대시/별표/이모지/따옴표/마크다운 금지\n"
        "- 지역·시장명을 자연스럽게 녹여 칭찬과 격려의 톤으로 (다만 너무 딱딱한 말투는 지양)"
    )

    # 서비스 핵심 메시지 요약(프롬프트에 주입)
    service_pitch = (
        "쌍문동의 동네 마트를 디지털로 연결하여 사용자가 직접 걷고 직접 사고 직접 건강해지는 "
        "걷기형 로컬 장보기 플랫폼. 걷기·소비·건강·지역경제를 '나의 한 끼 식사'로 연결. "
        "디지털 플랫폼을 지역에게 돌려주는 상생 모델."
    )

    user_prompt = (
        f"장소: {dong or ''} {market_name}\n"
        f"사용자는 총 {distance_m or 0}m를 걸어 도착했어.\n"
        f"아래 서비스 특징을 바탕으로 사용자에게 칭찬과 격려 문구 2줄을 만들어줘:\n"
        f"{service_pitch}\n"
        "두 줄은 줄바꿈으로 구분하고, 형식 규칙을 반드시 지켜."
    )

    resp = client.chat.completions.create(
        model=AI_MODEL_TIPS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=AI_TEMPERATURE_DEFAULT,
    )
    text = (resp.choices[0].message.content or "").strip()

    # 후처리: 혹시 모를 기호/불릿 제거 & 2줄만 추출
    import re
    lines = [re.sub(r'^[\s\-\*\•\d\.\)\(]+', '', ln).strip()
             for ln in text.splitlines() if ln.strip()]
    return lines[:2]
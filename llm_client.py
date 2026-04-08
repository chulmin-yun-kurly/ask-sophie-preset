"""
OpenAI 클라이언트 및 공통 유틸리티
"""
import os
import re
import json
import asyncio
from openai import AsyncOpenAI, BadRequestError
from config import OPENAI_API_KEY

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'prompts')

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# 배경 지식 (상품별 캐시)
_knowledge_cache: dict[str, str] = {}


def load_prompt(filename: str) -> str:
    """prompts 디렉토리에서 프롬프트 파일을 읽어오고, {product_name}을 치환합니다."""
    with open(os.path.join(PROMPTS_DIR, filename), 'r', encoding='utf-8') as f:
        text = f.read()
    from product_config import get_current_product
    product = get_current_product()
    if product:
        text = text.replace('{product_name}', product.product_name)
    return text


def load_knowledge() -> str:
    """상품별 knowledge 파일을 읽어 캐시합니다. 파일이 없거나 비어있으면 빈 문자열."""
    from product_config import get_current_product
    product = get_current_product()
    knowledge_file = product.knowledge_file if product else 'olive_oil.md'
    product_id = product.product_id if product else 'olive_oil'

    if product_id not in _knowledge_cache:
        path = os.path.join(PROMPTS_DIR, 'shared', 'knowledge', knowledge_file)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                _knowledge_cache[product_id] = f.read().strip()
        else:
            _knowledge_cache[product_id] = ''
    return _knowledge_cache[product_id]


def build_system_prompt(base_prompt: str) -> str:
    """시스템 프롬프트에 배경 지식을 결합합니다."""
    knowledge = load_knowledge()
    if knowledge:
        return f"{base_prompt}\n\n## 배경 지식\n{knowledge}"
    return base_prompt


_HTML_TAG_RE = re.compile(r'<[^>]+>')


def strip_html(text):
    """문자열에서 HTML 태그를 제거합니다. 문자열이 아니면 그대로 반환."""
    if not isinstance(text, str):
        return text
    return _HTML_TAG_RE.sub('', text)


def _sanitize(text: str) -> str:
    """JSON 직렬화를 깨는 제어 문자 및 서로게이트 문자를 제거합니다."""
    # 서로게이트 문자 제거 후 제어 문자 제거
    text = text.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    return ''.join(c for c in text if c == '\n' or c == '\r' or c == '\t' or ord(c) >= 32)


def _is_reasoning_model(model: str) -> bool:
    """o-시리즈 reasoning 모델 여부를 판별합니다."""
    return model.startswith('o1') or model.startswith('o3') or model.startswith('o4')


async def chat_json(model: str, system: str, user: str, temperature: float = 0.3, max_retries: int = 3) -> dict:
    """JSON 응답을 반환하는 LLM 호출. BadRequestError 시 재시도."""
    system = _sanitize(system)
    user = _sanitize(user)
    reasoning = _is_reasoning_model(model)

    for attempt in range(max_retries):
        try:
            if reasoning:
                # reasoning 모델: temperature/response_format 미지원
                # system → developer 메시지, JSON 출력을 프롬프트로 지시
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {'role': 'developer', 'content': system},
                        {'role': 'user', 'content': user + '\n\n반드시 JSON 형식으로만 응답하세요.'}
                    ],
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {'role': 'system', 'content': system},
                        {'role': 'user', 'content': user}
                    ],
                    temperature=temperature,
                    response_format={'type': 'json_object'}
                )
            # 응답이 잘렸는지 확인
            choice = response.choices[0]
            if choice.finish_reason == 'length':
                raise json.JSONDecodeError("응답이 max_tokens로 잘림", "", 0)
            content = choice.message.content
            # reasoning 모델은 markdown 코드 블록으로 감쌀 수 있음
            if content.startswith('```'):
                content = content.split('\n', 1)[1].rsplit('```', 1)[0]
            return json.loads(content)
        except (BadRequestError, json.JSONDecodeError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"   ⚠ {type(e).__name__}: {e}, {wait}초 후 재시도 ({attempt + 1}/{max_retries})...")
                await asyncio.sleep(wait)
            else:
                raise


async def get_embeddings(texts: list[str], model: str, batch_size: int = 100) -> list[list[float]]:
    """텍스트 리스트의 임베딩을 배치로 생성합니다."""
    all_embeddings = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        response = await client.embeddings.create(model=model, input=batch)
        all_embeddings.extend([item.embedding for item in response.data])
        print(f"   {min(start + batch_size, len(texts))}/{len(texts)} 완료")
    return all_embeddings

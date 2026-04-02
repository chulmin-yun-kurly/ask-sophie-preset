"""
컬리 상품 상세 JSON에서 실제 노출되는(isExposure=true) 콘텐츠만 파싱하는 모듈.

사용법:
    from parse_product_content import parse_exposed_content
    result = parse_exposed_content(json_data)
"""

import json
import re
from typing import Any


def strip_html(html: str) -> str:
    """HTML 태그를 제거하고 텍스트만 추출한다."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html)
    # </li> 태그 뒤에 줄바꿈 삽입 (리스트 항목 구분)
    text = re.sub(r"</li>\s*", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_images(module: dict) -> list[str]:
    """모듈에서 이미지 URL을 추출한다."""
    urls = []
    if "data" in module and isinstance(module["data"], dict):
        for device in ("pc", "mobile"):
            src = module["data"].get(device, {}).get("src", "")
            if src:
                urls.append(src)
    return urls


def extract_text_from_module(module: dict) -> str:
    """모듈의 data에서 텍스트를 추출한다."""
    data = module.get("data")
    if data is None:
        return ""
    if isinstance(data, str):
        return strip_html(data)
    if isinstance(data, dict):
        parts = []
        # TITLE3_TEXT 등 복합 구조
        for key in ("title", "text"):
            sub = data.get(key)
            if sub and isinstance(sub, dict):
                sub_data = sub.get("data", "")
                if isinstance(sub_data, str):
                    parts.append(strip_html(sub_data))
        # IMAGE_TITLE3_TEXT
        if "image" in data:
            for key in ("title", "text"):
                sub = data.get(key)
                if sub and isinstance(sub, dict):
                    sub_data = sub.get("data", "")
                    if isinstance(sub_data, str) and strip_html(sub_data) not in parts:
                        parts.append(strip_html(sub_data))
        return "\n".join(p for p in parts if p)
    return ""


def parse_check_point_list(module: dict) -> list[dict]:
    """CHECK_POINT_LIST 모듈을 파싱한다."""
    items = module.get("items", [])
    results = []
    for item in items:
        if not item.get("isExposure", False):
            continue
        title_type = item.get("titleType", "")
        custom_title = item.get("customTitleText", "")
        main = item.get("main", {})
        main_text = strip_html(main.get("data", "")) if main.get("isExposure", False) else ""
        results.append({
            "titleType": title_type,
            "customTitle": custom_title,
            "content": main_text,
        })
    return results


def parse_review_list(module: dict) -> list[dict]:
    """REVIEW_LIST 모듈을 파싱한다."""
    items = module.get("data", [])
    results = []
    for item in items:
        if not item.get("isExposure", False):
            continue
        title = ""
        if item.get("title") and item["title"].get("isExposure", False):
            title = strip_html(item["title"].get("data", ""))
        content = ""
        if item.get("data") and isinstance(item["data"], dict) and item["data"].get("isExposure", False):
            content = strip_html(item["data"].get("data", ""))
        results.append({"title": title, "content": content})
    return results


def parse_accordion(module: dict) -> dict:
    """ACCORDION 모듈을 파싱한다."""
    title = ""
    if module.get("title") and module["title"].get("isExposure", False):
        title = strip_html(module["title"].get("data", ""))
    images = []
    for img in module.get("images", []):
        if img.get("isExposure", False):
            images.extend(extract_images(img))
    return {"title": title, "images": images}


def parse_module(module: dict) -> dict | None:
    """개별 모듈을 파싱한다. isExposure=false면 None 반환."""
    if not module.get("isExposure", False):
        return None

    mod_type = module.get("type", "")
    result: dict[str, Any] = {"type": mod_type}

    if mod_type == "IMAGE":
        result["images"] = extract_images(module)
    elif mod_type == "CHECK_POINT_LIST":
        result["items"] = parse_check_point_list(module)
    elif mod_type == "REVIEW_LIST":
        result["items"] = parse_review_list(module)
    elif mod_type == "ACCORDION":
        acc = parse_accordion(module)
        result["title"] = acc["title"]
        result["images"] = acc["images"]
    elif mod_type == "IMAGE_TITLE3_TEXT":
        data = module.get("data", {})
        result["text"] = extract_text_from_module({"data": data})
        if data.get("image", {}).get("isExposure", False):
            result["images"] = extract_images({"data": data["image"].get("data", {})})
    else:
        text = extract_text_from_module(module)
        if text:
            result["text"] = text

    return result


def parse_exposed_content(json_data: dict) -> list[dict]:
    """
    상품 상세 JSON에서 isExposure=true인 블록/모듈만 추출한다.

    Args:
        json_data: 상품 상세 JSON (blocks 키를 포함하는 dict)

    Returns:
        노출되는 블록 목록. 각 블록은 type, modules 키를 가짐.
    """
    blocks = json_data.get("blocks", [])
    exposed_blocks = []

    for block in blocks:
        if not block.get("isExposure", False):
            continue

        block_type = block.get("type", "")
        modules = block.get("modules", [])
        parsed_modules = []

        for module in modules:
            parsed = parse_module(module)
            if parsed is not None:
                parsed_modules.append(parsed)

        if parsed_modules:
            exposed_blocks.append({
                "blockType": block_type,
                "modules": parsed_modules,
            })

    return exposed_blocks


def extract_plain_text(json_data: dict) -> str:
    """
    상품 상세 JSON에서 노출되는 텍스트를 평문으로 추출한다.
    이미지 URL은 제외하고 텍스트만 반환.
    """
    blocks = parse_exposed_content(json_data)
    lines = []

    for block in blocks:
        lines.append(f"\n=== {block['blockType']} ===")
        for mod in block["modules"]:
            if "text" in mod and mod["text"]:
                lines.append(mod["text"])
            if "items" in mod:
                for item in mod["items"]:
                    if isinstance(item, dict):
                        title = item.get("titleType") or item.get("title", "")
                        content = item.get("content", "")
                        if title:
                            lines.append(f"[{title}] {content}")
                        elif content:
                            lines.append(content)
    return "\n".join(lines)


# ── CLI 실행 ──────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python parse_product_content.py <json_file>")
        print("  또는 stdin으로 JSON을 전달하세요.")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        data = json.load(f)

    # 구조화된 결과
    result = parse_exposed_content(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 평문 텍스트
    print("\n" + "=" * 60)
    print(extract_plain_text(data))

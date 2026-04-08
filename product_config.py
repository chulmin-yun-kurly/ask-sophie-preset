"""
상품별 설정 관리
"""
import os
import yaml
from dataclasses import dataclass

PRODUCTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'products')


@dataclass
class ProductConfig:
    product_id: str
    product_name: str
    sheet_id: str
    knowledge_file: str
    categories_file: str
    id_prefix: str


def load_product_config(product_id: str) -> ProductConfig:
    """products/{product_id}.yaml 파일을 로드하여 ProductConfig를 반환합니다."""
    path = os.path.join(PRODUCTS_DIR, f'{product_id}.yaml')
    if not os.path.exists(path):
        raise FileNotFoundError(f"상품 설정 파일을 찾을 수 없습니다: {path}")
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return ProductConfig(
        product_id=data['product_id'],
        product_name=data['product_name'],
        sheet_id=data['sheet_id'],
        knowledge_file=data['knowledge_file'],
        categories_file=data.get('categories_file', ''),
        id_prefix=str(data.get('id_prefix', '')),
    )


def load_all_product_configs() -> list[ProductConfig]:
    """products/ 디렉토리의 모든 상품 설정을 로드합니다."""
    configs = []
    for fname in sorted(os.listdir(PRODUCTS_DIR)):
        if fname.endswith('.yaml'):
            product_id = fname[:-5]
            configs.append(load_product_config(product_id))
    return configs


_current: ProductConfig | None = None


def get_current_product() -> ProductConfig | None:
    """현재 설정된 상품을 반환합니다."""
    global _current
    if _current is None:
        product_id = os.environ.get('PRODUCT_ID', 'olive_oil')
        _current = load_product_config(product_id)
    return _current


def set_current_product(product_id: str) -> ProductConfig:
    """현재 상품을 설정합니다."""
    global _current
    _current = load_product_config(product_id)
    return _current


def get_output_dir() -> str:
    """현재 상품의 출력 디렉토리 경로를 반환합니다. 디렉토리가 없으면 생성합니다."""
    product = get_current_product()
    output_dir = os.path.join('output', product.product_id)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

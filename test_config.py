"""
테스트 모드 설정 관리
"""
import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass
class TestConfig:
    enabled: bool = False
    sample_size: int = 0
    random: bool = False
    sheet_id: str = ''
    comment: str = ''


_test_config: TestConfig | None = None


def get_test_config() -> TestConfig | None:
    """현재 테스트 설정을 반환합니다."""
    global _test_config
    if _test_config is None:
        enabled = os.environ.get('TEST_ENABLED', '') == '1'
        if enabled:
            _test_config = TestConfig(
                enabled=True,
                sample_size=int(os.environ.get('TEST_SAMPLE_SIZE', '10')),
                random=os.environ.get('TEST_RANDOM', '') == '1',
                sheet_id=os.environ.get('TEST_SHEET_ID', ''),
                comment=os.environ.get('TEST_COMMENT', ''),
            )
    return _test_config


def set_test_config(config: TestConfig):
    """테스트 설정을 지정합니다."""
    global _test_config
    _test_config = config


def sample_dataframe(df: pd.DataFrame, size: int, random: bool = False) -> pd.DataFrame:
    """DataFrame에서 top N 또는 랜덤 N개를 추출합니다."""
    if size >= len(df):
        return df
    if random:
        return df.sample(n=size, random_state=42).reset_index(drop=True)
    return df.head(size).reset_index(drop=True)


def create_test_spreadsheet(comment: str = '') -> str:
    """테스트용 새 스프레드시트를 생성하고 ID를 반환합니다."""
    from sheet_reader import get_credentials
    from googleapiclient.discovery import build

    timestamp = datetime.now().strftime('%y%m%d%H%M')
    title = f"test_{timestamp}"
    if comment:
        title += f"_{comment}"

    creds = get_credentials()
    service = build('sheets', 'v4', credentials=creds)

    spreadsheet = service.spreadsheets().create(
        body={'properties': {'title': title}}
    ).execute()

    sheet_id = spreadsheet['spreadsheetId']
    print(f"   테스트 스프레드시트 생성: {title}")
    print(f"   https://docs.google.com/spreadsheets/d/{sheet_id}")
    return sheet_id

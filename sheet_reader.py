import pandas as pd
import re
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEET_ID = '19c8o63Lck04VWeOHyEXiEcYDBv92LcISR17xP7UZpfs'
SHEET_URL = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit'

# 원본에서만 읽어야 하는 소스 시트 (테스트 모드에서도 원본 사용)
SOURCE_SHEETS = {'merged_final'}

# 시트 이름 -> gid 매핑
SHEET_GIDS = {
    '상품_코어_테이블': 539029483,
    'OCR_results': 1748479979,
    'OCR_results_2': 1171309228,
    'result': 328911425,
}


def get_credentials(client_secret_path: str = None) -> Credentials:
    """
    OAuth 인증을 통해 credentials를 가져옵니다.

    Args:
        client_secret_path: OAuth 클라이언트 시크릿 JSON 파일 경로

    Returns:
        Credentials: 인증된 credentials
    """
    if client_secret_path is None:
        client_secret_path = os.path.expanduser('~/.config/gws/client_secret.json')

    token_path = os.path.expanduser('~/.config/gws/token.json')

    creds = None
    # 저장된 토큰이 있는지 확인
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # 유효한 credentials가 없으면 새로 로그인
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # 토큰 저장
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def read_google_sheet(sheet_url: str = None, sheet_name: str = None, sheet_id: str = None, client_secret_path: str = None) -> pd.DataFrame:
    """
    구글 스프레드시트 URL에서 데이터를 읽어 DataFrame으로 반환합니다.

    Args:
        sheet_url: 구글 스프레드시트 URL (기본값: None, SHEET_ID 사용)
        sheet_name: 읽을 시트 이름 (기본값: None, gid의 시트 또는 첫 번째 시트)
        sheet_id: 스프레드시트 ID (기본값: None, 상품 설정에서 가져옴)
        client_secret_path: OAuth 클라이언트 시크릿 JSON 파일 경로 (기본값: ~/.config/gws/client_secret.json)

    Returns:
        pd.DataFrame: 시트 데이터
    """
    # 스프레드시트 ID 추출
    if sheet_url:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            raise ValueError("유효하지 않은 구글 스프레드시트 URL입니다.")
        sheet_id = match.group(1)

        # gid 추출 (특정 시트)
        gid = None
        if '#gid=' in sheet_url:
            gid_match = re.search(r'#gid=(\d+)', sheet_url)
            if gid_match:
                gid = gid_match.group(1)
    else:
        # 기본 스프레드시트 사용
        if sheet_id is None:
            # 테스트 모드: 소스 시트가 아니면 테스트 시트 사용
            from test_config import get_test_config
            test = get_test_config()
            if test and test.enabled and test.sheet_id and sheet_name not in SOURCE_SHEETS:
                sheet_id = test.sheet_id
            else:
                from product_config import get_current_product
                product = get_current_product()
                sheet_id = product.sheet_id if product else SHEET_ID

        # sheet_name이 주어진 경우 gid 찾기
        gid = None
        if sheet_name and sheet_name in SHEET_GIDS:
            gid = str(SHEET_GIDS[sheet_name])

    # Google Sheets API 사용
    creds = get_credentials(client_secret_path)
    service = build('sheets', 'v4', credentials=creds)

    # 시트 메타데이터 가져오기
    spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheets = spreadsheet.get('sheets', [])

    # 시트 이름 결정
    target_sheet_name = None
    if sheet_name:
        target_sheet_name = sheet_name
    elif gid:
        for sheet in sheets:
            if str(sheet['properties']['sheetId']) == gid:
                target_sheet_name = sheet['properties']['title']
                break
    else:
        target_sheet_name = sheets[0]['properties']['title']

    if not target_sheet_name:
        raise ValueError(f"시트를 찾을 수 없습니다.")

    # 데이터 가져오기
    range_name = f"{target_sheet_name}!A:ZZ"
    result = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=range_name
    ).execute()

    values = result.get('values', [])
    if not values:
        return pd.DataFrame()

    # DataFrame 생성 (Google Sheets는 행 끝 빈 셀을 잘라내므로 패딩)
    headers = values[0]
    num_cols = len(headers)
    padded_rows = [row + [''] * (num_cols - len(row)) for row in values[1:]]
    df = pd.DataFrame(padded_rows, columns=headers)

    return df


def write_dataframe_to_sheet(
    df: pd.DataFrame,
    sheet_name: str,
    sheet_url: str = None,
    sheet_id: str = None,
    replace_if_exists: bool = True,
    client_secret_path: str = None
) -> None:
    """
    데이터프레임을 구글 스프레드시트의 새 시트로 작성합니다.

    Args:
        df: 작성할 데이터프레임
        sheet_name: 생성할 시트 이름
        sheet_url: 구글 스프레드시트 URL (기본값: None, SHEET_ID 사용)
        sheet_id: 스프레드시트 ID (기본값: None, 상품 설정에서 가져옴)
        replace_if_exists: 시트가 이미 존재하면 삭제 후 재생성 (기본값: True)
        client_secret_path: OAuth 클라이언트 시크릿 JSON 파일 경로

    Returns:
        None
    """
    # 스프레드시트 ID 추출
    if sheet_url:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            raise ValueError("유효하지 않은 구글 스프레드시트 URL입니다.")
        sheet_id = match.group(1)
    elif sheet_id is None:
        # 테스트 모드: 테스트 시트에 쓰기
        from test_config import get_test_config
        test = get_test_config()
        if test and test.enabled and test.sheet_id and sheet_name not in SOURCE_SHEETS:
            sheet_id = test.sheet_id
        else:
            from product_config import get_current_product
            product = get_current_product()
            sheet_id = product.sheet_id if product else SHEET_ID

    # Google Sheets API 사용
    creds = get_credentials(client_secret_path)
    service = build('sheets', 'v4', credentials=creds)

    # 시트 메타데이터 가져오기
    spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheets = spreadsheet.get('sheets', [])

    # 기존 시트 확인 및 삭제
    existing_sheet_id = None
    for sheet in sheets:
        if sheet['properties']['title'] == sheet_name:
            existing_sheet_id = sheet['properties']['sheetId']
            break

    if existing_sheet_id is not None:
        if replace_if_exists:
            # 기존 시트 삭제
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={'requests': [{'deleteSheet': {'sheetId': existing_sheet_id}}]}
            ).execute()
        else:
            raise ValueError(f"시트 '{sheet_name}'이(가) 이미 존재합니다.")

    # 새 시트 생성
    rows = len(df) + 1  # 헤더 포함
    cols = len(df.columns)

    service.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id,
        body={
            'requests': [{
                'addSheet': {
                    'properties': {
                        'title': sheet_name,
                        'gridProperties': {
                            'rowCount': rows,
                            'columnCount': cols
                        }
                    }
                }
            }]
        }
    ).execute()

    # 데이터 준비 (헤더 + 데이터)
    values = [df.columns.tolist()] + df.fillna('').values.tolist()

    # 데이터 쓰기
    range_name = f"{sheet_name}!A1"
    service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption='RAW',
        body={'values': values}
    ).execute()

    print(f"'{sheet_name}' 시트가 생성되었습니다. (Shape: {df.shape})")


if __name__ == "__main__":
    # 사용 예시
    url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=0"
    df = read_google_sheet(url)
    print(df.head())

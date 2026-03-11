import os
import pandas as pd
import gspread
import traceback
from gspread_dataframe import set_with_dataframe

print("🚀 구글 시트 전송 시스템을 가동합니다...")

# 1. 환경 설정
home = os.path.expanduser("~")
desktop_path = os.path.join(home, "Desktop")
json_path = os.path.join(desktop_path, "google_key.json")
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

try:
    print(f"📂 파일 확인: {json_path}")
    if not os.path.exists(json_path):
        print("❌ 에러: 바탕화면에 google_key.json 파일이 실제로 존재하지 않습니다!")
        exit()

    # 2. 로봇 로그인
    gc = gspread.service_account(filename=json_path)
    print("✅ 1단계: 로봇 로그인 성공")

    # 3. 시트 열기
    sh = gc.open_by_key(spreadsheet_id)
    print("✅ 2단계: 구글 시트 연결 성공")

except Exception:
    print("❌ [실패] 상세 에러 리포트:")
    print("-" * 50)
    traceback.print_exc()  # 에러의 정체를 상세히 출력합니다.
    print("-" * 50)
    exit()

# 4. 데이터 업로드 (연결 성공 시에만 실행)
etfs = {
    "TIME 코스닥액티브": "TIME_코스닥액티브_30일추적.xlsx",
    "TIME K바이오액티브": "TIME_K바이오액티브_30일추적.xlsx",
    "TIME 코리아밸류업액티브": "TIME_코리아밸류업액티브_30일추적.xlsx",
    "TIME K신재생에너지액티브": "TIME_K신재생에너지액티브_30일추적.xlsx",
    "TIME K이노베이션액티브": "TIME_K이노베이션액티브_30일추적.xlsx",
    "KoAct 코스닥액티브": "KoAct_코스닥액티브_30일추적.xlsx",
    "KoAct 바이오헬스케어액티브": "KoAct_바이오헬스케어_30일추적.xlsx",
    "KoAct 배당성장액티브": "KoAct_배당성장_30일추적.xlsx",
    "KoAct 코리아밸류업액티브": "KoAct_코리아밸류업_30일추적.xlsx",
    "KoAct K수출핵심기업TOP30액티브": "KoAct_K수출핵심기업_30일추적.xlsx",
    "KoAct 테크핵심공급망액티브": "KoAct_테크핵심공급망_30일추적.xlsx",
    "KoAct K-컬처밸류체인액티브": "KoAct_K컬처밸류체인_30일추적.xlsx"
}

for name, file in etfs.items():
    path = os.path.join(desktop_path, file)
    if os.path.exists(path):
        df = pd.read_excel(path)
        try:
            ws = sh.worksheet(name)
        except:
            ws = sh.add_worksheet(title=name, rows="100", cols="30")
        ws.clear()
        set_with_dataframe(ws, df)
        print(f"🚀 [{name}] 업로드 완료")

print("\n🎉 모든 과정이 끝났습니다!")
on:
  schedule:
    - cron: '50 21 * * 0-4' 
  workflow_dispatch: 
  push:
    branches: [main]

jobs:
  run-bot:
    runs-on: ubuntu-latest
    steps:
    - name: 1. 저장소 체크아웃
      uses: actions/checkout@v4
      with:
        fetch-depth: 0

    - name: 2. 파이썬 환경 세팅
      uses: actions/setup-python@v5
      with:
        python-version: '3.10'

    - name: 3. 필수 패키지 설치
      run: |
        sudo apt-get update
        sudo apt-get install -y xvfb
        pip install -r requirements.txt

    - name: 4. 구글 시트 비밀키(JSON) 복원
      env:
        GCP_KEY_BASE64: ${{ secrets.GCP_KEY }}
      run: |
        # 💡 Base64 외계어를 다시 원본 JSON 파일로 해독합니다.
        echo -n "$GCP_KEY_BASE64" | base64 --decode > google_key.json

    - name: 5. 데이터 수집 및 업로드 실행 (핵심!)
      run: |
        # 💡 빠졌던 실행 단계를 다시 넣었습니다!
        xvfb-run -a python ETF_collector.py
        python 일괄변환기.py

    - name: 6. 보안 정리 및 결과 저장
      run: |
        git config --global user.name "github-actions[bot]"
        git config --global user.email "github-actions[bot]@users.noreply.github.com"
        
        # 💡 [보안] 깃허브에 올리기 전에 열쇠 파일을 삭제하여 유출을 막습니다.
        rm -f google_key.json
        
        git add .
        git commit -m "🤖 일일 수집 및 업로드 완료: $(date +'%Y-%m-%d')" || exit 0
        git pull --rebase origin main
        git push origin main

#!/usr/bin/env bash
# AI 신입사원 백엔드 실행 스크립트
# 사용법: 터미널에서  ./run.sh   (또는  bash run.sh)
set -e

# 스크립트가 있는 backend 폴더로 이동 (어디서 실행해도 동작)
cd "$(dirname "$0")"

echo "▶ 백엔드를 켭니다… (끄려면 Ctrl + C)"
echo "   확인용 주소: http://127.0.0.1:8000"
uv run uvicorn main:app --reload

# Slice-1 Staged Rollout Checklist

## 1) 서버(main) 업데이트
- `git pull --ff-only`

## 2) 서버 검증
- `python -m compileall src`
- `PYTHONPATH=src pytest -q`

## 3) control_tower 재시작
- systemd 사용 시: `systemctl --user restart income33-control-tower`
- 프로세스 직접 실행 시: 기존 프로세스 종료 후 재기동

## 4) 윈도우 sender/reporter 업데이트
- 최신 main pull
- agent 재시작

## 5) 운영 확인 체크리스트
- dashboard에 `send-expected-tax-amounts-list` 폼 노출
- sender에서 목록 붙여넣기 발송 1회 성공
- reporter 대상 sender-only 명령 enqueue 시 400 확인
- agent 측 sender-only 명령 수신 시 실패 처리/heartbeat 반영 확인

## 6) 롤백
- 문제 시 직전 커밋으로 `git revert <sha>` 후 동일 절차로 재배포

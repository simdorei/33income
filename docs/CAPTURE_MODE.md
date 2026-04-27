# Capture Mode: 로그인된 브라우저 request 자동 수집

목표: 사람이 이미 로그인한 로컬 Chrome/Edge에서 평소처럼 클릭하면, `fetch`/`XMLHttpRequest` request/response를 자동으로 로컬 파일에 저장한다. DevTools에서 헤더와 raw body를 하나씩 복사하지 않기 위한 MVP이다.

## 결론

별도 레포를 새로 만들기보다 기존 `33income` 레포 안에 넣는다.

이유:

- 나중에 reporter/sender bot의 request-first 자동화와 바로 연결된다.
- Windows 배포 ZIP에 같이 포함할 수 있다.
- 캡처 파일(`captures/`)은 `.gitignore`에 들어가므로 민감 자료가 git에 올라가지 않는다.

## 구성

```text
run_capture_helper.bat                  # Windows 실행 파일
browser_capture_snippet.js              # 로그인된 페이지 DevTools에 붙여넣는 캡처 스니펫
src/income33/capture/app.py             # 127.0.0.1:33133 로컬 수집 서버
captures/YYYYMMDD/captures.jsonl        # 실제 캡처 결과; git 제외
```

## 사용 순서

### 1. 로컬 헬퍼 실행

```bat
cd /d C:\33income
setup_windows.bat
run_capture_helper.bat
```

정상 확인:

```text
http://127.0.0.1:33133/health
```

### 2. 로그인된 웹페이지에서 스니펫 실행

1. 대상 웹사이트에 평소처럼 로그인한다.
2. Chrome/Edge DevTools를 연다. (`F12`)
3. Console 또는 Sources > Snippets에 `browser_capture_snippet.js` 내용을 붙여넣고 실행한다.
4. 콘솔에 아래 메시지가 보이면 성공:

```text
[33income-capture] installed. Run your workflow...
```

### 3. 평소처럼 버튼 클릭

대본 생성/저장/조회 흐름을 직접 수행한다. 스니펫이 브라우저 안의 `fetch`/`XHR`을 후킹해서 로컬 헬퍼로 보낸다.

### 4. 파일 전달

결과 파일:

```text
C:\33income\captures\YYYYMMDD\captures.jsonl
```

이 파일을 zip으로 묶어서 분석자에게 전달한다.

## 보안 기본값

헬퍼와 스니펫은 기본적으로 다음 헤더 값을 저장하지 않는다.

- `Cookie`
- `Set-Cookie`
- `Authorization`
- 이름에 `token`, `secret`, `session`, `auth`, `csrf`, `xsrf`가 들어가는 헤더

대신 다음처럼 존재 여부/쿠키 이름 정도만 남긴다.

```json
{
  "Cookie": {
    "redacted": true,
    "cookie_names": ["SESSION", "XSRF-TOKEN"]
  }
}
```

즉, 캡처 파일은 request 구조 분석용이며, 로그인 권한 자체를 넘기는 용도가 아니다.

## 왜 쿠키를 저장하지 않는가

쿠키는 어차피 자주 바뀐다. 중요한 것은 `현재 로그인 세션에서 어떤 endpoint가 어떤 payload와 response schema로 움직이는지`를 파악하는 것이다.

나중에 자동화는 쿠키 문자열을 복붙하는 방식이 아니라:

1. 로그인된 브라우저 context 안에서 실행하거나
2. 로컬 에이전트가 브라우저 프로필을 유지하면서 request를 수행하거나
3. 필요한 순간 최신 token/cookie를 읽는 방식

으로 가야 한다.

## 한계

- 페이지가 Service Worker, WebSocket, EventSource만 쓰는 경우 일부 요청이 안 잡힐 수 있다.
- `<form>` submit / 문서 navigation은 fetch/XHR이 아니면 안 잡힐 수 있다.
- response가 binary/blob이면 본문 대신 요약만 남긴다.
- 사이트의 CSP나 브라우저 보안 정책에 따라 Console snippet 실행이 제한될 수 있다.

이 경우 다음 단계는 Chrome Extension 또는 Playwright CDP 기반 캡처로 승격한다.

## 다음 단계

1. 대상 웹에서 대본 생성 흐름 1회 캡처
2. `captures.jsonl`을 보고 request 후보 분류
   - list/read
   - detail/read
   - generate/start
   - status/poll
   - save/export
3. request로 재현 가능한 단계와 UI fallback이 필요한 단계 분리
4. 검증된 요청만 bot/reporter 로직으로 승격

# web-capture-helper 빠른 사용법

## 1) 실행

`web-capture-helper.exe`를 더블클릭합니다.

확인 URL:

```text
http://127.0.0.1:33133/health
```

`frozen=true` 이고 `capture_dir`, `log_dir`가 기대 경로인지 먼저 확인하세요.

---

## 2) 스니펫 실행

1. 대상 사이트에 로그인합니다. (이미 로그인된 세션 그대로 사용 가능)
2. `F12`로 DevTools를 엽니다.
3. `browser_capture_snippet.js` 내용을 Console/Snippets에 붙여넣고 실행합니다.
4. 콘솔에 `[web-capture-helper] installed`가 보이면 성공입니다.

---

## 3) 평소처럼 작업

대본 생성/저장/조회 등 분석할 흐름을 평소처럼 클릭합니다.

---

## 4) 결과 전달

결과 위치:

```text
captures\YYYYMMDD\captures.jsonl
```

전체 캡처 zip 다운로드:

```text
http://127.0.0.1:33133/zip
```

---

## 5) 로그 위치

기본 로그 파일:

```text
logs\web-capture-helper.log
```

로그에는 startup/캡처요약/validation error/download/zip 요청이 남고,
민감값(Cookie/Auth/token/session/csrf)과 request/response body 원문은 남기지 않습니다.

# web-capture-helper 빠른 사용법

## 1. 실행

`web-capture-helper.exe`를 더블클릭합니다.

확인 URL:

```text
http://127.0.0.1:33133/health
```

## 2. 스니펫 실행

1. 대상 웹사이트에 로그인합니다.
2. `F12`로 DevTools를 엽니다.
3. `browser_capture_snippet.js` 내용을 Console에 붙여넣고 Enter를 누릅니다.
4. 콘솔에 `[web-capture-helper] installed`가 보이면 성공입니다.

## 3. 평소처럼 작업

대본 생성/저장/조회 등 분석할 흐름을 평소처럼 클릭합니다.

## 4. 결과 전달

결과 위치:

```text
captures\YYYYMMDD\captures.jsonl
```

전체 캡처 파일 zip 다운로드:

```text
http://127.0.0.1:33133/zip
```

## 보안

기본적으로 Cookie/Authorization/token/session/csrf 계열 헤더 값은 저장하지 않습니다.

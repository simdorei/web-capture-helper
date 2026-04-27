# web-capture-helper

로그인된 로컬 브라우저에서 발생하는 `fetch` / `XMLHttpRequest` 요청과 응답을 자동으로 캡처해 JSONL 파일로 저장하는 로컬 헬퍼입니다.

목표는 DevTools에서 `headers`, `request body`, `response body`를 하나씩 복사하지 않고, 사람이 평소처럼 클릭한 흐름을 분석 가능한 파일로 남기는 것입니다.

## 운영 원칙

- 로그인은 사용자가 직접 합니다.
- 헬퍼는 `127.0.0.1`에서만 실행됩니다.
- 기본적으로 `Cookie`, `Authorization`, `Set-Cookie`, `token/session/auth/csrf/xsrf` 계열 헤더 값은 저장하지 않고 redaction합니다.
- 캡처 결과(`captures/`)는 git에 올리지 않습니다.

---

## 공용 PC 권장 방식: exe 실행

공용 PC에 Python이 없어도 쓰기 위해 Windows exe 빌드를 기본 목표로 합니다.

GitHub Actions가 빌드한 artifact 또는 release ZIP을 받은 뒤:

```text
web-capture-helper.exe
browser_capture_snippet.js
README_QUICKSTART.md
```

사용 순서:

1. `web-capture-helper.exe` 실행
2. 브라우저에서 확인: `http://127.0.0.1:33133/health`
3. 로그인된 대상 웹페이지에서 DevTools 열기 (`F12`)
4. `browser_capture_snippet.js` 내용을 Console 또는 Snippets에 붙여넣고 실행
5. 평소처럼 대본 생성/저장/조회 흐름 클릭
6. 결과 파일 전달:

```text
captures\YYYYMMDD\captures.jsonl
```

또는 브라우저에서 zip 다운로드:

```text
http://127.0.0.1:33133/zip
```

---

## 개발자용: Python 실행

```bat
setup_windows.bat
run_capture_helper.bat
```

Linux/macOS 개발 검증:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m web_capture_helper.main
```

---

## Windows exe 직접 빌드

Python이 설치된 개발 PC에서만 필요합니다.

```bat
build_exe.bat
```

출력:

```text
dist\web-capture-helper.exe
```

---

## API

- `GET /` : 간단 안내 페이지
- `GET /health` : 실행 상태 확인
- `POST /capture` : 브라우저 스니펫이 캡처 이벤트 전송
- `GET /latest?limit=20` : 최근 캡처 확인
- `GET /download` : 오늘 `captures.jsonl` 다운로드
- `GET /zip` : `captures/` 폴더 zip 다운로드

---

## 한계

- fetch/XHR이 아닌 일반 form navigation, WebSocket, Service Worker 내부 요청은 일부 안 잡힐 수 있습니다.
- binary/blob response는 본문 대신 요약만 저장됩니다.
- 페이지 CSP/브라우저 정책에 따라 Console snippet 실행이 제한될 수 있습니다. 이 경우 Chrome Extension 방식으로 승격합니다.

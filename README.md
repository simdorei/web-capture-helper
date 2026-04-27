# web-capture-helper

로그인된 로컬 브라우저에서 발생하는 `fetch` / `XMLHttpRequest` 요청과 응답을 자동 캡처해 JSONL로 저장하는 로컬 헬퍼입니다.

핵심 목표는 DevTools에서 `headers`, `request body`, `response body`를 수동 복사하지 않고, 사람이 평소처럼 클릭한 흐름을 분석 가능한 파일로 남기는 것입니다.

자세한 설계/한계/Fiddler 비교는 `docs/CAPTURE_PLAN.md`를 참고하세요.

---

## 운영 원칙

- 로그인은 사용자가 직접 수행합니다.
- 헬퍼는 기본적으로 `127.0.0.1`에서만 실행됩니다.
- 민감 헤더(`Cookie`, `Authorization`, `Set-Cookie`, token/session/auth/csrf/xsrf 계열)는 redaction 처리됩니다.
- 로그 URL은 민감값 노출 방지를 위해 origin(스킴+호스트+포트) 수준으로 축약됩니다.
- 캡처 결과(`captures/`)와 로그(`logs/`)는 git에 올리지 않습니다.

---

## 공용 PC 권장 방식: EXE 실행 (EXE-first)

공용 PC에 Python이 없어도 사용 가능하도록 EXE 실행을 기본 경로로 둡니다.

릴리즈 ZIP(또는 Actions artifact) 구성 예시:

```text
web-capture-helper.exe
browser_capture_snippet.js
README_QUICKSTART.md
```

사용 순서:

1. `web-capture-helper.exe` 실행
2. 브라우저에서 `http://127.0.0.1:33133/health` 확인
3. 로그인된 대상 페이지에서 DevTools(`F12`) 열기
4. `browser_capture_snippet.js`를 Console/Snippets에서 실행
5. 평소처럼 분석 대상 흐름 클릭
6. 결과 파일 전달

```text
captures\YYYYMMDD\captures.jsonl
```

또는 브라우저에서 zip 다운로드:

```text
http://127.0.0.1:33133/zip
```

### EXE 실행 시 파일 저장 위치

`web-capture-helper.exe`가 있는 폴더 기준으로 자동 생성됩니다.

```text
captures\
logs\web-capture-helper.log
```

---

## 개발자용: Python 실행

### Windows

```bat
setup_windows.bat
run_capture_helper.bat
```

### Linux/macOS

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m web_capture_helper.main
```

source/venv 실행 시 기본 저장 경로는 **현재 실행 위치(`cwd`) 기준**입니다.

```text
captures/
logs/
```

---

## 환경변수 (override)

- `WEB_CAPTURE_HELPER_DIR`: 캡처 디렉터리 override
- `WEB_CAPTURE_HELPER_LOG_DIR`: 로그 디렉터리 override
- `WEB_CAPTURE_HELPER_PORT`: 포트 override (기본 `33133`)
- `WEB_CAPTURE_HELPER_HOST`: 바인딩 호스트 override (기본 `127.0.0.1`)

예시:

```bash
WEB_CAPTURE_HELPER_DIR=/tmp/captures WEB_CAPTURE_HELPER_LOG_DIR=/tmp/logs WEB_CAPTURE_HELPER_PORT=44133 PYTHONPATH=src python -m web_capture_helper.main
```

---

## Windows EXE 직접 빌드

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

- `GET /` : 상태 안내 페이지
- `GET /health` : 실행 상태/경로 확인
- `POST /capture` : 브라우저 snippet이 캡처 이벤트 전송
- `GET /latest?limit=20` : 최근 캡처 확인
- `GET /download` : 당일 `captures.jsonl` 다운로드
- `GET /zip` : `captures/` 폴더 zip 다운로드

`/health` 주요 필드:

- `capture_dir`
- `log_dir`
- `capture_file`
- `log_file`
- `frozen` (PyInstaller EXE 실행 여부)

---

## 한계

- fetch/XHR이 아닌 일반 form navigation은 부분/미지원일 수 있음
- WebSocket, Service Worker 내부 요청은 부분/미지원일 수 있음
- binary/blob 응답은 원문 대신 요약으로 저장될 수 있음
- CSP/브라우저 정책에 따라 Console snippet 실행이 제한될 수 있음

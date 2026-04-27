# Web Capture Plan (스크립팅/자동화 분석용)

## 1) Capture mode 목적

`web-capture-helper`의 capture mode는 **이미 로그인된 브라우저 세션에서 사람이 수행한 실제 클릭/조회/저장 흐름**의 HTTP 트래픽을 분석 가능한 형태(JSONL)로 남기는 것이 목적입니다.

핵심 목표:
- DevTools에서 요청/응답을 수동 복사하는 반복 작업 제거
- 재현 가능한 분석 산출물(`captures/YYYYMMDD/captures.jsonl`) 확보
- 공용 PC 환경에서도 EXE만으로 실행 가능

---

## 2) 데이터 흐름

```text
[브라우저 DevTools snippet]
  └─ fetch/XHR 후킹
      └─ 이벤트(JSON) 전송
          └─ http://127.0.0.1:<port>/capture
              └─ local helper가 redaction + 저장
                  └─ captures/YYYYMMDD/captures.jsonl
```

부가 흐름:
- `/latest` : 최근 캡처 확인
- `/download` : 당일 JSONL 다운로드
- `/zip` : `captures/` 전체 zip 다운로드

---

## 3) 보안 / redaction 정책

저장 시 기본 redaction:
- `Cookie`, `Set-Cookie`, `Authorization`, `Proxy-Authorization`
- `token`, `secret`, `session`, `auth`, `csrf`, `xsrf` 패턴이 포함된 헤더명

저장되지 않도록 관리되는 항목:
- 민감 헤더 원문 값

로그(`logs/web-capture-helper.log`) 정책:
- 남김: startup, host/port/path, 캡처 저장 성공 요약(method/url-origin/status/duration), validation error, download/zip 요청
- 남기지 않음: request body 원문, response body 원문, Cookie/Auth/token/session/csrf 원문 값
- URL은 query/path 민감값 유출을 줄이기 위해 origin(스킴+호스트+포트)만 기록

---

## 4) 이미 켜져 있는 로그인 세션 적용 여부

**가능합니다.**

조건:
1. 대상 탭이 이미 로그인 상태여야 함
2. 해당 탭 DevTools Console/Snippets에서 `browser_capture_snippet.js`를 실행해야 함
3. snippet 실행 이후 발생한 fetch/XHR부터 캡처됨

주의:
- 기존 로그인 쿠키는 브라우저가 그대로 사용하지만, helper 저장물에는 쿠키 값이 redaction됨
- 탭/새로고침/도메인 변경 시 snippet 재주입이 필요할 수 있음

---

## 5) Fiddler와의 차이

| 항목 | web-capture-helper | Fiddler/프록시형 도구 |
|---|---|---|
| 설치/배포 | EXE 1개 + snippet | 프록시 설치/인증서 설정 필요 가능 |
| 캡처 범위 | snippet이 주입된 탭의 fetch/XHR 중심 | 시스템/브라우저 전역 트래픽 관찰 가능 |
| 로그인 맥락 | 실제 사용자 세션 탭 그대로 사용 | 가능하나 프록시 설정 영향 고려 필요 |
| 민감정보 보호 | 저장 시 기본 redaction 내장 | 별도 필터/후처리 필요 |
| 심층 디버깅 | 제한적(앱 중심) | 프로토콜/저수준 디버깅 강함 |

정리:
- 실무 분석용(빠른 재현/공유)에는 helper가 가볍고 안전
- 네트워크 전역/저수준 분석은 Fiddler가 강함

---

## 6) 현재 한계

다음 항목은 부분 캡처 또는 미지원 가능:
- 일반 form navigation 요청
- WebSocket 프레임
- Service Worker 내부 요청
- 페이지 CSP/브라우저 정책으로 인한 Console snippet 실행 제한
- binary/blob 응답 원문

---

## 7) 다음 단계 (승격 옵션)

1. **Chrome Extension 방식**
   - snippet 수동 주입 제거
   - 탭 이동/재주입 UX 개선

2. **CDP/Playwright capture 방식**
   - 네트워크 이벤트 수집 범위 확대
   - 자동 시나리오 실행 + 수집 파이프라인 일원화

3. **정책 확장**
   - URL query 파라미터 redaction 룰셋 추가
   - 프로젝트별 allowlist/denylist 정책 파일화

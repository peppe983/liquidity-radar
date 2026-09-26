# MCP 개념 정리

> 3단계에서 직접 만들어보며 정리한 내용. 2026-09-24.
> 실제 구현은 [[mcp_server.py]] 참고.

---

## 한 줄 정의

**MCP(Model Context Protocol)** = AI가 외부 데이터·기능을 **도구로 호출**할 수 있게 하는 표준 규격.

내 프로그램을 AI가 쓸 수 있는 형태로 바꿔주는 **어댑터**라고 보면 된다.

---

## 왜 필요한가

**문제:** AI는 내 컴퓨터의 `update.py`가 존재하는지도, 어떻게 실행하는지도 모른다.

**해결:** 규격에 맞춰 "내가 제공하는 도구는 이거야"라고 알려주는 창구를 둔다.

그 창구가 하는 일은 딱 두 가지뿐이다:

1. `list_tools` — "내가 가진 도구 목록은 이거야"
2. `call_tool` — "이 도구를 이 인자로 실행해줘" → 실행하고 결과 반환

요청받아 응답하는 쪽이니까 **서버**라고 부른다.

---

## 구조

```
[클라이언트]              [서버]              [내 코드]
Claude Code    ←→    mcp_server.py    →    update.py
Claude 웹                (wrapper)          assess.py
Claude 데스크톱
```

핵심: **서버는 wrapper일 뿐**이다. 로직을 새로 짜는 게 아니라 기존 함수를 감싸기만 한다.

---

## ⚠️ 헷갈렸던 지점

### "서버"라고 해서 원격 컴퓨터가 필요한 게 아니다

전송 방식(transport)이 두 가지고, 자원 조달이 완전히 다르다.

| | **stdio** | **streamable-http** |
|---|---|---|
| 동작 | 클라이언트가 내 PC에서 프로세스를 직접 띄움 | 네트워크 주소로 접속 |
| 통신 | 표준입출력(stdin/stdout) | HTTP + JSON-RPC |
| 주소 | 없음 | 필요 (`https://...`) |
| 24시간 가동 | 불필요 (쓸 때만 뜸) | 필요 |
| 자원 | **내 PC** | 내 PC + 터널, 또는 클라우드 |
| 쓰는 곳 | Claude Code, 데스크톱 | Claude 웹, 외부 서비스 |

**코드는 똑같고 마지막 한 줄만 다르다:**

```python
mcp.run(transport="stdio")            # 로컬
mcp.run(transport="streamable-http")  # 원격
```

### "웹사이트"가 아니다

HTTP 모드여도 브라우저로 열면 볼 게 없다. 사람이 읽을 HTML을 주는 게 아니라
JSON으로 도구 목록과 실행 결과만 주고받는 **API 엔드포인트**다.

### 그래서 "서버가 필요한가"의 진짜 기준

wrapper가 필요하냐가 아니라 → **클라이언트가 내 PC에 접근할 수 있느냐**

- Claude Code: 내 PC에서 프로세스를 띄울 수 있음 → stdio로 충분, 호스팅 불필요
- Claude 웹: 브라우저 안에 갇혀 있음 → 인터넷으로 닿을 주소 필요

---

## 만드는 법

### 1. 설치

```bash
pip install "mcp[cli]"    # 파이썬 3.10 이상 필요
```

### 2. 서버 작성

```python
from mcp.server import MCPServer

mcp = MCPServer("liquidity")

@mcp.tool()
def get_current_state() -> dict:
    """지금 유동성 상태와 압력 단계를 반환한다."""
    return json.load(open("latest.json"))["assessment"]

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

포인트 두 개:

- **타입 힌트가 곧 스키마** — `date: str | None = None`을 쓰면 JSON Schema가 자동 생성된다. 별도 정의 불필요.
- **docstring이 곧 설명서** — AI가 이걸 읽고 언제 어떤 도구를 쓸지 판단한다. 그래서 docstring을 성의 없이 쓰면 도구를 엉뚱하게 쓴다. 인자 설명과 주의사항까지 적어야 한다.

### 3. 등록

```bash
claude mcp add liquidity -- /절대경로/.venv/bin/python /절대경로/mcp_server.py
claude mcp list    # ✔ Connected 확인
```

---

## 실제로 만든 것 (이 프로젝트)

도구 7개:

| 도구 | 하는 일 |
|---|---|
| `get_current_state` | 지금 상태·단계·주요 수치 |
| `list_series` | 조회 가능한 지표 목록 |
| `get_series` | 특정 지표 시계열 |
| `assess_date` | **과거 특정일**의 사다리 단계 재계산 |
| `decompose_change` | 유동성 변화의 원인 분해 |
| `find_stress_periods` | L2 이상이었던 구간 검색 |
| `explain_indicator` | 지표·규칙 설명 |

### 설계하며 배운 것

**캐싱이 필수다.** 도구를 부를 때마다 FRED에서 13개 시리즈를 새로 받으면 매번 10초씩
걸린다. 서버 안에 DataFrame을 1시간 캐시해뒀다. 원본이 하루 한 번 갱신되는 성격이라
그 정도면 충분히 신선하다.

**입력을 관대하게 받아야 한다.** 사용자가 "2026-09-20"처럼 주말 날짜를 물어볼 수 있다.
에러를 내는 대신 직전 영업일로 자동 보정하게 했다.

**불확실성을 숨기면 안 된다.** SRF 사용액은 최근치만 조회 가능해서, 과거 날짜를 물으면
SRF 조건이 빠진 채 판정된다. 그래서 `pressure_data_complete: false`를 같이 반환해
"확인 못 함"과 "압력 없음"을 구분한다.

---

## 언제 쓰고 언제 안 쓰나

**필요한 경우**
- Claude 웹/모바일에서 내 데이터를 쓰고 싶을 때 (유일한 방법)
- 남에게 공유할 때 (상대가 저장소 클론 없이 사용 가능)
- 다른 프로그램이 내 로직을 호출해야 할 때

**굳이 필요 없는 경우**
- Claude Code에서만 쓸 거라면. 이미 셸·파일 접근 권한이 있어서 스크립트로 다 된다.

---

## 다음에 해볼 것

- [ ] HTTP 모드 + 터널(cloudflared)로 Claude 웹에서 연결해보기
- [ ] Resources(도구 말고 읽기 전용 데이터 노출) 써보기
- [ ] Prompts(미리 정의된 질문 템플릿) 써보기

관련: [[유동성 지표 정리]] · [[FRED 데이터 수집]]

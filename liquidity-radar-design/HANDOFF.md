# Liquidity Radar — 구현 핸드오프

이 폴더는 Liquidity Radar 대시보드의 **디자인 시스템과 탭별 시안**이다. 이걸 기준으로 GitHub Pages 정적 사이트를 구현한다.

## 1. 폴더 구성

```
liquidity-radar-design/
├─ HANDOFF.md                  ← 이 문서 (먼저 읽기)
├─ design-system/
│  ├─ README.md                ← 디자인 규칙 (색·타이포·차트·레이아웃·문구 원칙). 반드시 지킬 것
│  ├─ tokens.json              ← 토큰 원본 (색 라이트/다크, 타이포, 간격, 모서리, 그림자)
│  ├─ tokens.css               ← tokens.json을 CSS 변수로 변환한 것 (라이트 기본, 다크 자동)
│  └─ components/
│     ├─ bundle.css            ← 모든 컴포넌트 스타일 (lr- 접두사)
│     ├─ bundle.js             ← 차트 엔진 + 시안용 예시 데이터 (window.LiquidityRadar, 의존성 없음)
│     └─ <컴포넌트>/README.md, preview.html   ← 컴포넌트별 사용 규칙과 마크업 예시
└─ preview/                    ← 브라우저로 바로 열어보는 시안 (index.html부터)
   ├─ SummaryPage.html, SummaryPageMobile.html   요약 탭 (1440 / 390)
   ├─ LevelPage.html                              수위 탭
   ├─ PressurePage.html                           압력 탭
   ├─ LearnPage.html                              알아두기 탭
   └─ 나머지                                       개별 컴포넌트
```

`preview/*.html`은 `design-system/`의 CSS·JS를 상대경로로 불러온다. 폴더 구조를 유지한 채 열 것.

## 2. 구현 목표

- 한 페이지 정적 사이트, 탭 4개(요약 · 수위 · 압력 · 알아두기). 시안 4개를 한 페이지로 합치고 탭 전환을 실제로 동작시킨다(URL 해시 `#summary` `#level` `#pressure` `#learn` 권장).
- 빌드 도구 없이 동작하는 순수 HTML/CSS/JS가 기본. 프레임워크를 쓰더라도 결과물은 GitHub Pages에 올릴 정적 파일.
- 마크업·클래스는 시안의 것을 그대로 쓴다. `tokens.css` → `bundle.css` → 페이지 순서로 로드.
- 차트는 `bundle.js`의 `LiquidityRadar.chart(el, spec)`를 재사용한다. 단 `LiquidityRadar.demo`(예시 데이터)는 **실데이터로 교체**하고 bundle에서 떼어낸다.
- 평일 자동 갱신 파이프라인이 `data/latest.json`, `data/history.json`을 만든다고 가정하고, 페이지는 이 두 파일만 `fetch`한다.

## 3. 차트 엔진 API (bundle.js)

| 호출 | 설명 |
|---|---|
| `LiquidityRadar.chart(el, spec)` | 선/누적영역/로그막대 차트. 등록된 차트는 리사이즈·기간 변경 시 다시 그려짐 |
| `spec` 공통 | `dates`(YYYY-MM-DD 배열), `series:[{label, short?, color:"series-netliq", values, dash?}]`, `fmt(v)` |
| 선 옵션 | `thresholds:[{value,label,color}]`, `includeZero`, `index100`(시작=100 지수화), `mini`(작은 차트), `endLabels`, `overlay:false`(S&P 띠 끄기), `demoAt`(시안용 툴팁 고정 — 실서비스에선 빼기) |
| 누적 | `stacked:true`, series는 아래층→위층 |
| 로그 막대 | `kind:"bars", dates, values`($B 단위, SRF용) |
| `setPeriod("6m"|"1y"|"3y")` | 모든 차트 기간 변경 |
| `setOverlay(bool)` / `overlayToggle(btn)` | S&P 500 비교 띠(별도 y축, x축·크로스헤어 공유) |
| `chips(group, cb)` / `subtabs(group, scope, onShow)` | 칩 그룹, 하위 탭 패널 전환 |
| `fmt.tn / pct / rate / bp / idx` | 숫자 포맷(조$, %, 금리, bp, 지수) |

## 4. 데이터 계약 (제안 — 파이프라인과 맞춰 확정할 것)

`bundle.js` 안의 `LiquidityRadar.demo`가 `history.json`의 모양 그대로다. 이 구조를 따르면 차트 코드를 고칠 필요가 없다.

```jsonc
// data/history.json
{
  "weekly": {                       // 수요일 기준 주간 (H.4.1 등)
    "dates": ["2023-09-27", ...],
    "walcl": [], "tga": [], "rrp": [], "currency": [], "other": [],   // 조$
    "netliq": [], "reserves": [],   // 조$ (파이프라인에서 계산)
    "ratio": [],                    // 지급준비금 ÷ 은행 총자산, %
    "spx": []                       // S&P 500 종가(지수화는 프런트에서)
  },
  "daily": {                        // 미국 영업일
    "dates": [...],
    "iorb": [], "sofr": [],         // %
    "spread": [],                   // SOFR − IORB, bp
    "srf": [],                      // SRF 사용액, $B
    "level": []                     // 압력 단계 0~3 (파이프라인에서 판정)
  }
}
```

```jsonc
// data/latest.json — 요약 탭과 헤더에 필요한 값
{
  "asOf": "2026-09-25", "updatedAt": "2026-09-26T18:31:00+09:00",
  "status": { "level": "caution", "headline": "자금시장 압력은 없지만(L0), 유동성 수위가 30일간 0.026조$ 줄었습니다" },
  "pressureLevel": 0,
  "metrics": {
    "netliq": { "value": 5.77, "chg30d": -0.026 },
    "reserves": { "value": 2.93, "ratio": 11.4 },
    "spread": { "value": -2, "z6m": 0.17, "threshold": 5 },
    "srf": { "value": 0, "threshold": 1 }
  },
  "factors30d": [                   // 지급준비금에 준 영향(조$) + 항목 자체 변화
    { "key": "treast", "effect": 0.020, "change": 0.020 },
    { "key": "tga", "effect": -0.013, "change": 0.013 },
    { "key": "rrp", "effect": -0.0003, "change": 0.0003 },
    { "key": "residual", "effect": -0.0207 },
    { "key": "reserves", "effect": -0.014 }
  ],
  "freshness": {                    // 지표별 최신 값 날짜
    "RRP": "2026-09-25", "IORB": "2026-09-25", "SPX": "2026-09-25", "SOFR": "2026-09-24",
    "WALCL": "2026-09-23", "TGA": "2026-09-23", "WRESBAL": "2026-09-23", "BANK_ASSETS": "2026-09-16"
  },
  "releaseCalendar": { "H41": ["2026-09-03", ...], "H8": ["2026-09-04", ...], "holidays": ["2026-09-07"] }
}
```

## 5. 반드시 지킬 디자인 규칙 (요약 — 자세한 건 design-system/README.md)

- y축은 차트마다 하나. 단위가 다르면 지수화(시작=100)하거나 차트를 나눈다(S&P 비교 띠가 그 예).
- 지표 색 고정: Net Liquidity 파랑 · TGA 주황 · 지급준비금 청록 · RRP 노랑 · 유통화폐 보라 · S&P 500 분홍 · 기타 회색 · IORB 진회색 · SOFR 하늘색. 토큰 이름(`series-*`)으로만 지정.
- 상태 색(양호·중립·주의·경고·위험)은 예약. 항상 색 + 아이콘 + 글자. 시리즈 색으로 재사용 금지.
- 막대는 모서리 0. 격자선은 옅은 실선만. 모든 차트에 크로스헤어 + 툴팁.
- 용어는 줄이지 않는다: "지준" ✕ → "지급준비금".
- 예측선·목표가·매수/매도 신호·게이지·도넛·그라데이션 금지.
- 모바일 390px에서 페이지 가로 스크롤 없음(칩 줄만 가로 스크롤).
- 라이트/다크 모두 지원(`tokens.css`가 `prefers-color-scheme`과 `[data-theme]`을 처리).

## 6. 확인이 필요한 것 (구현 전 사용자에게 물어볼 것)

1. **요인 분해가 맞아떨어지지 않는다.** 국채 +0.020 − TGA 0.013 − RRP 0.0003 ≈ +0.007인데 지급준비금 변화는 −0.014. 차이 −0.021을 "그 외(잔차)"로 표시 중. 연준 총자산(MBS 등)·유통화폐를 별도 요인으로 넣을지 결정 필요.
2. **종합 판정표**(압력 × 수위 방향)는 브리프에 있는 규칙 두 개(압력 L2 이상이면 최소 경고, 지금 L0·수위 줄어듦 → 주의)만 확정이고 나머지 칸은 시안 예시.
3. **예시 데이터**: 3년 히스토리는 브리프의 현재값·범위에 맞춰 만든 가짜다. IORB 경로(2025-10 이후 3.90% 유지)도 가정이므로 실데이터로 교체.
4. `demoAt`(툴팁 고정)과 시안에서 S&P 비교를 켠 채 여는 설정은 시안 전용. 실서비스 기본값은 툴팁 숨김·S&P 비교 꺼짐.

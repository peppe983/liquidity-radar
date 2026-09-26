미국 달러 유동성을 한 페이지로 보여주는 대시보드의 디자인 시스템. 이 화면은 **날씨 예보**다. 방향과 환경을 말하고, 매매 신호를 주지 않는다. 차분하고 신뢰감 있는 금융 리서치 도구처럼 보이게 만든다.

## 내용 원칙

- 용어는 줄이지 않는다. "지준"이 아니라 **지급준비금**.
- UI는 한국어. 지표 코드(`WALCL`, `SOFR`, `TGA`)는 `code` 스타일, `ink-muted` 색의 보조 텍스트로만 쓴다.
- 사용자는 금융 지식이 깊지 않은 개인 투자자와 학습자다. 용어가 처음 나오는 카드에는 쉬운 한 줄 설명(`body-sm`, `ink-muted`)을 붙인다. 예: "은행이 연준에 맡겨 둔 돈. 시장 유동성의 실제 연료".
- 문장은 존댓말 평서문. "~습니다". 감탄, 이모지, 느낌표를 쓰지 않는다.
- 결론 대신 근거를 말한다. 좋은 예: "자금시장 압력은 없지만(L0), 유동성 수위가 30일간 0.026조$ 줄었습니다". 나쁜 예: "지금은 매수 타이밍이 아닙니다".
- 숫자는 단위를 붙여 쓴다: `5.77조$`, `−2bp`, `11.4%`. 음수는 하이픈이 아니라 마이너스 기호(−)를 쓴다. 숫자에는 `font-variant-numeric: tabular-nums`.
- 한계는 숨기지 않는다. 한계 고지 박스는 접을 수는 있어도 제목 줄은 항상 보인다.
- 넣지 않는 것: 예측선, 목표가, "매수/매도" 신호, 단독 결론.

## 색

- 바탕은 `surface`, 카드·패널은 `surface-raised`에 `line` 테두리와 `shadow-card`. 계산식 블록과 칩 트랙은 `surface-sunken`.
- 글자는 `ink`, 보조는 `ink-muted`. 둘 다 세 가지 바탕 위에서 라이트·다크 모두 4.5:1 이상.
- **시리즈 색은 지표에 고정한다.** 모든 차트, 범례, 요인 막대에서 같은 지표는 같은 색:
  Net Liquidity `series-netliq`(파랑) · TGA `series-tga`(주황) · 지급준비금 `series-reserves`(청록) · RRP `series-rrp`(노랑) · 유통화폐 `series-currency`(보라) · S&P 500 `series-spx`(분홍) · 기타 `series-other`(회색). 모든 시리즈 색은 `surface-raised` 위 3:1 이상.
- **상태 색은 예약되어 있다.** 양호 `status-good` · 중립 `status-neutral` · 주의 `status-caution` · 경고 `status-warning` · 위험 `status-danger`. 배지는 `*-soft` 바탕 위에 같은 이름의 진한 색으로 아이콘과 글자를 쓴다. 상태 색을 시리즈 색으로, 시리즈 색을 상태로 재사용하지 않는다. 색만으로 상태를 전달하지 않는다: 항상 **색 + 아이콘 + 글자**.
- 압력 단계는 `pressure-0`(회색) → `pressure-1`(노랑) → `pressure-2`(주황) → `pressure-3`(빨강). 타임라인에서는 색과 함께 **막대 높이**로도 단계를 구분한다(L1 짧게, L3 길게). `pressure-0`은 얇은 바탕 띠라 대비가 낮은 게 의도다.
- 데이터 발표주기의 '이전 값'(기준일보다 앞선 값)은 `stale` 점 + "이전 값" 글자.
- 포커스 링은 `focus` 2px 실선, 2px 오프셋.

## 타이포

- 한 가족만: `sans`(Pretendard, 없으면 시스템 한글 산세리프). 세리프·장식 폰트 금지. 코드와 계산식만 `mono`.
- 큰 숫자는 `kpi-value`(32px 700), 바로 옆에 단위 `kpi-unit`(14px, `ink-muted`).
- 상태 헤드라인 근거 문장은 `headline`(24px 700)으로 화면에서 가장 크다. 섹션 제목 `title`, 카드 이름·탭 `label`, 해설 `body`, 보조 줄 `body-sm`, 날짜·축·범례 `caption`.
- 읽을거리(알아두기 탭) 본문 폭은 680px.

## 차트

- **y축은 하나만.** 단위가 다른 두 값은 시작일=100으로 지수화하거나 차트를 나눈다.
- 시리즈 선 `stroke-series`(2px). 막대는 모서리 0의 직사각형(둥글리지 않는다). 격자선은 `stroke-grid` 1px `line` 실선, 가로만. 점선 격자 금지. 0 기준선은 `line-strong`.
- 시리즈가 2개 이상이면 범례와 선 끝 직접 라벨을 함께 둔다.
- 모든 점에 숫자를 찍지 않는다. 값은 마우스를 올리면 뜨는 **세로 크로스헤어 + 툴팁**(날짜, 모든 시리즈 값; `surface-raised`, `radius-md`, `shadow-pop`)으로 보여준다.
- 기간 선택(6개월 · 1년 · 3년, 기본 1년)은 차트 위 한 줄의 칩 그룹이며 모든 차트에 적용된다.
- 각 차트 아래 해설 카드 2~3개: "무엇인가 / 어떻게 읽나 / 주의".
- 게이지, 도넛, 3D, 그라데이션, 네온 효과를 쓰지 않는다.

## 레이아웃

- 데스크톱 기준 1440px, 본문 최대 폭 1200px, 좌우 여백 `space-6`. 카드 패딩 `space-5`, 카드 사이 `space-4`, 섹션 사이 `space-6`.
- 모바일 390px: 좌우 여백 `space-4`, 카드 패딩 `space-3~4`. 핵심 숫자 카드 4개는 데스크톱 4열 → 태블릿 2×2 → 모바일 1열. 탭·칩 줄만 가로 스크롤을 허용하고 페이지 가로 스크롤은 없다.
- 헤더(서비스 이름, 부제, 기준일, 갱신 시각, 출처)와 탭 4개(요약 · 수위 · 압력 · 알아두기)는 모든 탭에서 같은 위치.
- 수위·압력 탭 안은 차트를 한 화면에 늘어놓지 않고 하위 칩으로 하나씩 고른다.
- 모서리: 카드 `radius-lg`, 안쪽 블록 `radius-md`, 칩·배지 `radius-pill`. 차트 막대는 0.

## 아이콘

- 아이콘 세트는 없다. 상태 배지용 네 모양(원=양호, 가로 막대 원=중립, 삼각형=주의, 마름모=경고, 팔각형=위험)을 인라인 SVG 1.75px 선으로 그리고 `currentColor`로 상태 색을 받는다. 모양 자체가 단계를 구분하므로 색각 이상이어도 읽힌다.
- 방향 화살표(▲▼)는 증감 표시에만 쓰고 색을 입히지 않는다(`ink-muted`). 감소가 곧 나쁨은 아니기 때문이다.

## 컴포넌트 (요약 탭)

- `AppHeader` 헤더 + 탭 + 기간 선택
- `StatusHeadline` 최상단 상태 배지 + 근거 문장
- `StatusBadge` 5단계 배지
- `MetricCard` 핵심 숫자 카드
- `FactorBars` 무엇이 움직였나(요인 분해)
- `PressureTimeline` 압력 단계 타임라인(호버 툴팁 포함)
- `DataFreshness` 데이터 발표주기: 매일/매주 구분 + 이번 달 발표일 캘린더
- `LimitsNotice` 접을 수 있는 한계 고지
- `SummaryPage`, `SummaryPageMobile` 위 요소를 조합한 요약 탭 전체 시안(1440 / 390)

## 컴포넌트 (수위 · 압력 · 알아두기)

- 차트: `LineChart`, `StackedAreaChart`, `SmallMultiples`, `LogBarChart` — 모두 `window.LiquidityRadar.chart(el, spec)` 하나로 그린다.
- `FormulaBlock` 계산식 블록, `ExplainCards` 무엇인가/어떻게 읽나/주의
- `PressureLadder` 압력 4단계 계단, `VerdictMatrix` 압력×수위 판정표
- `RateCorridorDiagram` 연준 금리 구조 도식, `ReservePathDiagram` 국채 발행 자금의 두 경로, `Glossary` 용어 사전
- `LevelPage`, `PressurePage`, `LearnPage` 탭 전체 시안(1440)

탭 페이지 구조는 같다: 탭 소개 한 줄 → 툴바(하위 칩 + 기간 칩) → 차트 카드(제목, 질문 한 줄, 계산식, 차트) → 해설 카드 3개. 하위 칩은 `LiquidityRadar.subtabs`, 기간 칩은 `LiquidityRadar.chips(..., LiquidityRadar.setPeriod)`로 연결한다.

컴포넌트는 `components/bundle.css`의 `lr-` 클래스와 정적 HTML, 차트는 `components/bundle.js`(의존성 없음)로 되어 있다. `LiquidityRadar.demo`는 브리프의 현재값·범위에 맞춘 시안용 예시 데이터다. 시안 수치는 2026-09-25 기준 예시이며, 구현에서는 `latest.json` / `history.json`에서 읽는다.

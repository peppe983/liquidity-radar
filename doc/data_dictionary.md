# 데이터 사전 — 수집 지표 및 파생값

> `update.py`가 FRED에서 수집하는 원본 지표와, 그걸로 계산하는 파생값을 정리한 문서.
> 1단계(FRED 데이터 수집 파이프라인) 구현 중 실측을 거쳐 확정된 내용.
> 개념적 배경(왜 이 지표들을 골랐는지 등)은 [research.md](research.md) 참고.

## 1. 수집 지표 (원본, FRED에서 그대로 받아옴)

| FRED 코드 | 이름 | 의미 | 발표 주기 | 원본 단위 |
|---|---|---|---|---|
| `WALCL` | 연준 총자산 | 연준 대차대조표의 자산 총액. Net Liquidity 계산의 기준값 | 주간 (목요일 H.4.1 발표) | 백만 달러 |
| `WTREGEN` | TGA (재무부 일반계정) | 정부가 연준에 갖고 있는 금고. 여기 쌓이면 그만큼 은행 시스템 밖으로 돈이 빠짐 | **주간** (⚠️ research.md 초안엔 "영업일"로 기술했으나, 1단계 구현 중 실측 결과 실제로는 7일 간격 확인) | 백만 달러 |
| `RRPONTSYD` | ON RRP (익일물 역레포) | MMF 등이 연준에 하루짜리로 돈을 맡기는 창구. 여기 쌓인 돈도 시스템 밖에 있는 셈 | 영업일 | 십억 달러 |
| `WRESBAL` | 은행 지급준비금 | 은행들이 연준에 갖고 있는 계좌 잔액. WALCL보다 "유통화폐 노이즈"가 없어서 더 정직한 유동성 지표 | 주간 | 백만 달러 |
| `TREAST` | 연준 보유 국채 | 연준이 갖고 있는 국채 총량. QT(양적긴축)/QE(양적완화)가 실제로 진행 중인지 실측하는 용도 | 주간 | 백만 달러 |
| `WSHOMCB` | 연준 보유 MBS | 연준이 갖고 있는 주택저당증권. 국채보다 줄어드는 속도가 훨씬 느림(조기상환 의존) | 주간 | 백만 달러 |
| `WSHOSHO` | 연준 보유 증권 전체 | ⚠️ 원래 "단기 국채"로 적어뒀으나 실측 확인 결과 FRED 정식 명칭은 *Assets: Securities Held Outright: Securities Held Outright*, 즉 연준이 매입 보유 중인 **증권 총액**(국채+MBS+기관채)이다. 실측 검산: TREAST 4.554조 + WSHOMCB 1.914조 = WSHOSHO 6.470조 | 주간 | 백만 달러 |
| `TLAACBW027SBOG` | 은행권 총자산 | 전체 상업은행의 자산 총액. 지급준비금을 이걸로 나누면 "은행 몸집 대비 유동성 비율" 계산 가능 (실측: 3.01조 ÷ 25.80조 = 11.7%) | 주간 | **십억 달러** (⚠️ 이 문서와 코드 모두 처음엔 "백만 달러"로 적어뒀으나, 실측 결과 FRED 표기는 Billions of U.S. Dollars. 1000배 축소 버그였음) |
| `DFII10` | 10년물 물가연동국채 실질금리 | 자금 조달 비용 지표. 유동성이 많아도 조달금리가 비싸면 위험자산에 잘 안 감 | 영업일(매일) | % (그대로 사용) |
| `DTWEXBGS` | 달러 인덱스 (광의) | 달러 강세/약세 지표. 원래 `DXY`를 쓰려 했으나 FRED에 없는 시리즈라(404 확인) 이걸로 대체. 해외 달러 부족(유로달러 사각지대)을 간접적으로 포착 | 영업일(매일) | 지수(index) |
| `WCURCIR` | 유통화폐 | 지갑·ATM 속 현금. 연준 부채 5칸 중 가장 안정적(3년 변동폭 0.16조)이라, Net Liquidity에서 빼면 지준+기타에 도달한다 | 주간 | 백만 달러 |
| `SP500` | S&P 500 지수 | 대시보드에서 유동성 지표와 **오버레이 비교**하기 위한 위험자산 기준선. 유동성→위험자산 관계는 체제 의존적이라 인과가 아닌 대조용으로만 본다 | 영업일(매일) | 지수(index) ⚠️ FRED의 SP500은 라이선스 제약으로 **최근 10년치만** 제공 (실측: 2016-09-26 시작, 2608행). 장기 백테스트엔 부족 |

## 2. 파생값 (`compute_derived`에서 계산)

| 파생값 | 계산식 | 의미 |
|---|---|---|
| `net_liquidity_trillions` | WALCL − WTREGEN − RRPONTSYD | **핵심 지표.** 연준 자산에서 "시스템 밖에 묶인 돈"(정부금고+RRP)을 뺀, 실제로 시장에 도는 유동성 |
| `net_liquidity_30d_change_trillions` | Net Liquidity의 30일 전 대비 변화 | 최근 한 달 새 유동성이 늘었는지 줄었는지 |
| `walcl_wow_change_trillions` | WALCL의 7일 전 대비 변화 | 연준 대차대조표가 주간 단위로 얼마나 변했는지 |
| `reserves_trillions` | WRESBAL 그대로 (조 달러 단위 별칭) | |
| `fed_ust_holdings_trillions` | TREAST 그대로 | |
| `fed_mbs_holdings_trillions` | WSHOMCB 그대로 | |

원본 지표 10여 개를 단위 통일 + 날짜 정렬(ffill)한 뒤 이 파생값들을 계산하고,
최신 값만 뽑아 `latest.json`에 저장하는 흐름은 `update.py`의 `main()` 함수를 참고.

## 3. 압력 지표 (2단계 추가) — 자금시장 스트레스

수량 지표(위 1장)만으로는 "지금 수위가 충분한가"에 답할 수 없다. 가격은 수량보다 먼저
반응하므로, 아래 지표들이 조기 경보 역할을 한다.

| 코드 / 항목 | 출처 | 의미 | 발표 주기 | 단위 |
|---|---|---|---|---|
| `SOFR` | FRED | 담보부 조달금리(레포시장 본체). 담보시장 압력의 조기 신호 | 영업일 | % |
| `IORB` | FRED | 지급준비금 부리금리. 연준이 직접 정하는 값이라 스프레드의 기준선 역할. ⚠️ 2021-07-29부터 존재(그 이전엔 IOER) | 영업일 | % |
| SRF 사용량 | **뉴욕 연은 Markets API** (FRED에 없음) | 상시레포기구 사용액. 민간 조달 실패를 뜻해 0 이탈 자체가 신호 | 영업일 | 달러 |

SRF 조회 방식: `GET https://markets.newyorkfed.org/api/rp/results/search.json?startDate=…&endDate=…&operationTypes=Repo`
→ `operationType=="Repo" AND operationMethod=="Full Allotment"`인 항목만 클라이언트에서
필터링해 날짜별 `totalAmtAccepted` 합산. (API의 `securityType=srf` 파라미터는 항상 빈
배열을 반환하므로 쓸 수 없음 — 실측 확인.)

## 4. 판단 결과 (`latest.json`의 `pressure` / `assessment`)

| 필드 | 의미 |
|---|---|
| `pressure.spreads_bp.sofr_minus_iorb` | (SOFR − IORB) × 100, bp 단위. 담보시장 압력 |
| `pressure.zscore.<스프레드>.{2M,6M,1Y,2Y}` | 각 기간 대비 Z-score. 절대 임계값 대신 Z-score를 쓰는 이유는 체제가 바뀌면 같은 수치의 의미가 달라지기 때문 |
| `pressure.zscore_undefined_reason` | Z-score가 `null`인 칸의 사유. `insufficient_data`(관측치 부족) / `zero_variance`(윈도우 내내 완전히 일정) / `missing_series`(시리즈 자체 없음) |
| `pressure.zscore_window_default` | 신호 판정에 쓰는 기본 윈도우 (`6M`) |
| `pressure.zscore_threshold` | 신호 발동 임계치 (`2.0`) |
| `pressure.srf_usage` | 최근 SRF 사용액. **조회 실패 시 전체가 `null`** — "0"과 구분됨 |
| `pressure.signals.*_zscore_triggered` | 해당 스프레드의 기본 윈도우 Z-score가 임계치를 넘었는지. 판정 불가 시 `null` |
| `pressure.signals.srf_usage_nonzero` | SRF 사용액 > 0 여부. 조회 실패 시 `null` |
| `pressure.signals.pressure_signal_active` | 위 신호 중 하나라도 켜졌는지 (OR 조건) |
| `pressure.signals.pressure_data_complete` | 모든 압력 신호를 실제로 판정했는지. `false`면 "압력 없음"으로 해석하면 안 됨 |
| `pressure.level` / `level_label` | 압력 사다리 단계 0~3 / `L0`~`L3` |
| `pressure.level_reasons` | 그 단계가 발동한 구체적 조건 목록 (예: `sofr_spread_+16bp`, `srf_74.6B_critical`) |
| `pressure.thresholds` | 판정에 쓴 임계값 전체. 값을 바꾸면 여기에도 반영되므로 소비자가 기준을 확인할 수 있다 |
| `assessment.quantity_direction` | 30일 Net Liquidity 변화 방향 (`up`/`flat`/`down`). 지준 대비 ±0.5% 안쪽은 `flat` |
| `assessment.quantity_deadzone_trillions` | 그 ±0.5%가 실제 얼마인지 (조 달러) |
| `assessment.pressure_level` | 압력 사다리 단계 (0~3) |
| `assessment.status` | 최종 판정: `healthy` / `neutral` / `watch` / `warning` / `critical` / `unknown` |
| `assessment.status_reasons` | 그 판정이 나온 근거 신호 목록 |
| `assessment.decomposition.delta_*_trillions` | 30영업일간 TREAST/WTREGEN/RRPONTSYD/WRESBAL 변화량 |
| `assessment.decomposition.primary_driver` | 변화를 주도한 요인: `QT`/`QE`(연준발), `TGA_refill`/`TGA_drawdown`(재무부발), `RRP_inflow`/`RRP_outflow` |
| `assessment.decomposition.interpretation` | research.md 3.4절 시소 표 기반 해석: `buffer_absorbed`(완충 작동) / `reserve_drain_warning`(실질 흡수, 경계) / `government_spending_supply`(정부지출 공급) / `mixed_or_other` / `insufficient_data` |

### 압력 사다리 (L0~L3)

각 단계의 조건은 OR다. 임계값은 전부 실측 분포에서 뽑았다.

| 단계 | 조건 | 뜻 |
|---|---|---|
| L0 | 아래 어느 것도 아님 | 정상 |
| L1 | SOFR−IORB의 6M Z-score ≥ 2 **또는** 스프레드 ≥ +5bp (95분위) | 딜러 여력 부족 |
| L2 | 그 이탈이 3영업일 중 2일 지속 **또는** ≥ +15bp (99분위) **또는** SRF ≥ $1B | 지준 희소성 의심 |
| L3 | SOFR−IORB ≥ +30bp **또는** SRF ≥ $10B | 조달 실패 수준 |

⚠️ Z-score는 **단측**이다. 스프레드가 평소보다 크게 *낮은* 것(−2σ)은 유동성이 넉넉하다는
뜻이지 압력이 아니다. 절대값으로 보면 평온한 구간이 경보로 잡힌다(백테스트에서 확인된 버그).

ℹ️ EFFR−IORB(은행 본체 압력)는 사용자 요청으로 **제외**했다. 수집도 하지 않는다.
되살리려면 `assess.py`의 `SPREAD_DEFINITIONS` 위 주석을 참고.

### 최종 판정 (압력 우선)

```
L3                 → critical (위험)
L2                 → warning  (경고)
L1 + 수량 ↓        → warning  (경고로 격상)
L1 + 수량 ↑/보합   → watch    (주의)
L0 + 수량 ↑        → healthy  (양호)
L0 + 수량 보합     → neutral  (중립)
L0 + 수량 ↓        → watch    (주의)
```

### 백테스트

`python backtest.py`로 임계값을 검증한다. 현재 결과 (2018-04~2026-09, 2211영업일):
L0 88.6% / L1 3.4% / L2 7.2% / L3 0.8%. **2019-09-16**(레포 발작 당일)과
**2020-03-17**에 L3 도달, **2021~2023년은 L2 이상 0일**.

수량이 늘고 있어도 압력 신호가 켜지면 경고다 — 가격(압력)이 수량보다 먼저 반응한다는 게
이 지표 체계의 전제이므로 이 우선순위를 뒤집으면 안 된다.

⚠️ SRF 사용액이 0이라고 해서 압력이 없다는 뜻은 아니다(낙인 효과). 반드시 스프레드와
병행해서 봐야 하며, 그래서 `pressure_data_complete`가 `false`일 때의 "압력 없음"은
"확인하지 못함"으로 읽어야 한다.


## 5. 대시보드용 시계열 (`history.json`)

`latest.json`은 스냅샷 하나뿐이라 선 그래프를 못 그린다. 그래서 `update.py`가
차트용 시계열을 따로 뱉는다.

| 항목 | 값 |
|---|---|
| 기간 | 최근 3년 (RRP가 1.57조 → 0으로 고갈되는 궤적이 다 들어감) |
| 해상도 | **영업일별** (약 785개) |
| 크기 | 약 176KB |
| 구조 | `dates` 배열 1개 + 시리즈별 값 배열 (레코드 배열보다 훨씬 작다) |
| 담긴 것 | 원본 11개 + 파생 3개(`net_liquidity_trillions`, 30일 변화, `sofr_minus_iorb_bp`) |

⚠️ **주 단위로 솎으면 안 된다.** 분기말 레포 스파이크가 통째로 사라진다. 실제로
2025-10-31의 +32bp는 주간 샘플링에서 누락되어, 진짜 스트레스 구간이 평온해 보이게 된다.

스프레드는 브라우저가 두 시리즈를 빼는 대신 여기서 미리 계산해 둔다 — 단위 실수
여지를 없애기 위함.

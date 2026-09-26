"""
유동성 상태 판단 로직 (2단계).

update.py가 수집·정렬한 DataFrame을 받아, 자금시장 압력 지표를 계산하고
"압력 우선" 규칙으로 최종 상태(양호/중립/경고)를 판정한다.

update.py와 분리한 이유: update.py는 "수집 + 정렬"이라는 단일 책임에 머무르게 하고,
여기(판단 로직)는 네트워크 없이도 테스트 가능한 순수 함수 위주로 구성하기 위함.
latest.json을 다시 읽는 별도 스크립트가 아니라, update.py의 main()이 메모리 상의
DataFrame을 그대로 넘겨 호출하는 라이브러리 모듈이다.

판단 규칙 (research.md 6장, 압력 우선):
    수량 ↑ + 압력 없음 → healthy
    수량 ↓ + 압력 없음 → neutral
    압력 신호 발생     → warning (수량 무관)
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd
import requests

log = logging.getLogger(__name__)

NYFED_REPO_SEARCH_URL = "https://markets.newyorkfed.org/api/rp/results/search.json"
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "liquidity-alert/0.1 (+https://github.com/)"

# SRF는 "0보다 크면 그 자체로 신호"인 임계치형 지표라 Z-score용 장기 히스토리가
# 필요 없다. 주말·공휴일 버퍼 목적으로 최근 2주만 조회한다.
SRF_LOOKBACK_DAYS = 14

# Z-score 윈도우(영업일 수 근사). research.md 6장의 기간 선택(2M/6M/1Y/2Y) 요구사항.
ZSCORE_WINDOWS = {"2M": 42, "6M": 126, "1Y": 252, "2Y": 504}

# 신호 판정에 쓰는 기본 윈도우. 2M은 분기말 레포 스파이크 같은 단기 노이즈에 과민하고,
# 1Y/2Y는 FOMC 금리 사이클 전체를 포함해 최근 체제 변화에 둔감해진다. 6M이 절충점.
DEFAULT_ZSCORE_WINDOW = "6M"
ZSCORE_THRESHOLD = 2.0

# ── 압력 사다리 임계값 ────────────────────────────────────────────────
# 전부 실측 분포에서 뽑았다 (2023-09~2026-09, 798영업일). 감으로 정한 값이 아니다.

# SOFR−IORB 절대 수준(bp). 평상시 중앙값이 -6bp라 양수 자체가 이미 비정상이다.
# +5bp 초과가 53일(6.6%), +15bp 초과가 11일(1.4%)로 드물다.
SPREAD_BP_WATCH = 5.0
SPREAD_BP_ELEVATED = 15.0
SPREAD_BP_CRITICAL = 30.0

# SRF 사용액(달러). "0보다 크면 경고"는 쓸 수 없다 — 3년 중 119일이 논제로인데
# 대부분 수백만 달러짜리 노이즈라 경고가 상시 켜진다. $1B 초과는 10일, $10B 초과는
# 7일뿐이라 여기서 끊는다.
SRF_USD_ELEVATED = 1e9
SRF_USD_CRITICAL = 10e9

# 지속성: 최근 N영업일 중 K일 이상 이탈하면 "지속"으로 본다.
# 2019-09(그달 평균 +29bp, 지속형)와 2020-03(최대 +44bp지만 평균 +1bp, 단발형)을
# 가르기 위한 조건.
PERSISTENCE_WINDOW_DAYS = 3
PERSISTENCE_MIN_DAYS = 2

# 수량 방향 데드존. 지준 수준 대비 이 비율 안쪽 변화는 "보합"으로 본다
# (부호만 보면 +0.001조도 "증가"로 잡힌다).
QUANTITY_DEADZONE_RATIO = 0.005

# 요인분해 윈도우. compute_derived의 net_liquidity_30d_change_trillions와 동일 기간으로
# 맞춰야 "그 변화가 무엇 때문이었나"를 같은 기준으로 비교할 수 있다.
DECOMPOSITION_WINDOW_DAYS = 30

# 지준 변화가 이 값보다 작으면 "거의 변화 없음"으로 본다 (요인분해 해석용, 조 달러).
RESERVES_FLAT_THRESHOLD_TRILLIONS = 0.05

# EFFR−IORB는 사용자 요청으로 제외했다 (개념이 어렵고 당장 볼 필요가 없다는 판단).
# 되살리려면 아래에 "effr_minus_iorb": ("EFFR", "IORB")를 추가하고, update.py의
# SERIES에 EFFR을 되돌리고, classify_pressure_level의 L3 조건에 EFFR 항목을 넣으면
# 된다. 참고: 백테스트상 EFFR은 2020-03을 L3로 올린 유일한 근거였다.
SPREAD_DEFINITIONS = {
    "sofr_minus_iorb": ("SOFR", "IORB"),
}

# signals dict에 함께 담기지만 "압력 신호"가 아니라 요약/메타인 키들.
# 신호 목록을 순회할 때 반드시 제외해야 한다 (안 그러면 status_reasons에 섞인다).
META_SIGNAL_KEYS = {"pressure_signal_active", "pressure_data_complete"}


def is_srf_operation(op: dict) -> bool:
    """뉴욕 연은 레포 오퍼레이션 한 건이 SRF 사용인지 판별한다.

    2021-07 SRF 도입 이후 연준의 레포 오퍼레이션(operationType=="Repo")은 전부 SRF다.
    operationMethod로 거르면 안 된다 — 2025-12에 경매 방식이 "Multiple Price"에서
    "Full Allotment"로 바뀌어서, Full Allotment만 세면 그 이전 사용액이 전부 0이 된다
    (2025-10-31 $50.4B, 2025-06-30 $11.1B 등 $1B 이상 25일이 누락됐던 버그).
    "Small Value Exercise"는 운영 점검용 소액 테스트라 실제 수요가 아니므로 뺀다.
    """
    if op.get("operationType") != "Repo":
        return False
    return "Small Value Exercise" not in (op.get("note") or "")


def fetch_srf_usage(lookback_days: int = SRF_LOOKBACK_DAYS) -> dict | None:
    """뉴욕 연은 Markets API에서 최근 SRF(상시레포기구) 사용액을 가져온다.

    SRF 식별은 is_srf_operation을 따른다.
    (API의 securityType=srf 파라미터는 실측 결과 항상 빈 배열을 반환해 쓸 수 없다.)
    하루에 여러 차례 오퍼레이션이 있을 수 있어 같은 날짜의 totalAmtAccepted를 합산한다.

    실패 시 None을 반환한다 — "조회했더니 0"과 "조회 자체를 실패"는 반드시 구분해야
    한다. SRF는 낙인 효과(stigma) 때문에 사용액 0이 "압력 없음"을 뜻하지 않으므로,
    데이터를 못 받아온 것을 0으로 뭉뚱그리면 판단이 조용히 틀어진다.
    """
    end = pd.Timestamp.utcnow().normalize()
    start = end - timedelta(days=lookback_days)
    by_date = fetch_srf_by_date(start, end)
    if by_date is None:
        return None
    if not by_date:
        log.warning("SRF 오퍼레이션이 조회 기간(%d일) 내에 없습니다", lookback_days)
        return None
    return latest_srf_result(by_date)


def latest_srf_result(by_date: dict[str, dict]) -> dict | None:
    """fetch_srf_by_date 결과에서 가장 최근 날짜의 사용액을 latest.json 형태로 뽑는다."""
    if not by_date:
        return None
    latest_date = max(by_date)
    bucket = by_date[latest_date]
    return {
        "operation_date": latest_date,
        "total_accepted_usd": bucket["total"],
        "total_accepted_trillions": bucket["total"] / 1e12,
        "operation_count": bucket["count"],
        "source": NYFED_REPO_SEARCH_URL,
    }


def fetch_srf_by_date(
    start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, dict] | None:
    """기간 내 SRF 사용액을 날짜별로 합산해 {"YYYY-MM-DD": {"total", "count"}}로 반환한다.

    조회 실패는 None, 조회는 됐지만 오퍼레이션이 없으면 빈 dict다 (둘을 섞지 않는다).
    """
    params = {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
        "operationTypes": "Repo",
    }

    try:
        resp = requests.get(
            NYFED_REPO_SEARCH_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        operations = resp.json().get("repo", {}).get("operations", [])
    except Exception as exc:  # noqa: BLE001 - 조회 실패는 None으로 표현하고 계속 진행
        log.warning("SRF 사용량 조회 실패: %s", exc)
        return None

    by_date: dict[str, dict] = {}
    for op in operations:
        if not is_srf_operation(op):
            continue
        date = op.get("operationDate")
        if not date:
            continue
        bucket = by_date.setdefault(date, {"total": 0.0, "count": 0})
        bucket["total"] += float(op.get("totalAmtAccepted") or 0.0)
        bucket["count"] += 1

    return by_date


def compute_spread_bp(
    df: pd.DataFrame, rate_col: str, benchmark_col: str = "IORB"
) -> pd.Series | None:
    """금리 스프레드를 bp(베이시스포인트) 단위로 계산한다. 컬럼이 없으면 None."""
    if rate_col not in df.columns or benchmark_col not in df.columns:
        return None
    return (df[rate_col] - df[benchmark_col]) * 100


def compute_zscore(series: pd.Series, window: int) -> pd.Series:
    """rolling 평균/표준편차 기준 Z-score.

    min_periods=window로 두어 데이터가 윈도우를 못 채우는 구간은 NaN이 된다
    (IORB는 2021-07-29부터 존재하므로 과거 구간에서 2Y 윈도우가 비는 게 정상).
    """
    rolling = series.rolling(window, min_periods=window)
    return (series - rolling.mean()) / rolling.std()


def latest_zscore_table(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    spreads: dict[str, pd.Series],
    windows: dict[str, int] = ZSCORE_WINDOWS,
) -> tuple[dict, dict, list[str]]:
    """각 스프레드 × 각 윈도우의 as_of 시점 Z-score 표, 진단 정보, 경고 목록.

    Z-score가 정의되지 않는 경우가 둘인데 의미가 완전히 다르므로 구분해서 돌려준다:

    - ``insufficient_data``: 윈도우를 채울 관측치가 없음 → 판정 불가(None).
      (IORB가 2021-07-29부터라 과거 구간에서 2Y 윈도우가 비는 경우 등)
    - ``zero_variance``: 윈도우 내내 스프레드가 완전히 일정해 표준편차가 0 →
      0/0이라 NaN이 되지만, 의미는 "움직임이 전혀 없음"이므로 이상치는 아니다.
      단, 스프레드가 넓은 수준에 고정돼 있어도 Z-score는 0 근처라는 한계가 있어
      경고에 현재 절대 수준(bp)을 함께 남긴다.
    """
    table: dict[str, dict] = {}
    diagnostics: dict[str, dict] = {}
    warnings: list[str] = []

    for name, spread in spreads.items():
        table[name] = {}
        diagnostics[name] = {}
        history = spread.loc[:as_of]
        zscores = {
            label: compute_zscore(spread, size) for label, size in windows.items()
        }

        for window_label, window_size in windows.items():
            value = (
                zscores[window_label].loc[as_of]
                if as_of in spread.index
                else float("nan")
            )

            if not pd.isna(value):
                table[name][window_label] = round(float(value), 4)
                diagnostics[name][window_label] = None
                continue

            table[name][window_label] = None
            available = int(history.tail(window_size).notna().sum())

            if available < window_size:
                diagnostics[name][window_label] = "insufficient_data"
                warnings.append(
                    f"{name}: {window_label} 윈도우 Z-score 계산 불가 — 관측치 부족 "
                    f"(필요 {window_size}개, 보유 {available}개)"
                )
            else:
                diagnostics[name][window_label] = "zero_variance"
                current = history.loc[as_of] if as_of in history.index else float("nan")
                level = "" if pd.isna(current) else f"{current:.1f}bp에서 "
                warnings.append(
                    f"{name}: {window_label} 윈도우 동안 스프레드가 {level}완전히 "
                    f"일정해 Z-score 미정의 — 변동 없음(이상치 아님)으로 처리했으나, "
                    f"절대 수준이 높은 채 고정된 경우는 Z-score로 잡히지 않음에 유의"
                )

    return table, diagnostics, warnings


def determine_pressure_signals(
    zscore_table: dict,
    diagnostics: dict,
    srf_result: dict | None,
    threshold: float = ZSCORE_THRESHOLD,
    default_window: str = DEFAULT_ZSCORE_WINDOW,
) -> dict:
    """압력 신호들을 판정한다.

    스프레드 Z-score 초과와 SRF 사용 발생은 OR 관계다 — research.md는 SRF가 0이어도
    (낙인 효과 때문에) 압력이 없다는 뜻은 아니므로 스프레드를 병행하라고 명시한다.
    판정 불가한 신호는 False가 아니라 None으로 둔다 ("압력 없음"과 "확인 불가"는
    다른 의미이고, 이 둘을 뭉개면 경고를 조용히 놓친다).
    """
    signals: dict[str, bool | None] = {}

    for name, windows in zscore_table.items():
        z = windows.get(default_window)
        if z is not None:
            signals[f"{name}_zscore_triggered"] = bool(abs(z) >= threshold)
        elif diagnostics.get(name, {}).get(default_window) == "zero_variance":
            # 윈도우 내내 완전히 일정 = 이상 움직임 없음 (판정 불가가 아님)
            signals[f"{name}_zscore_triggered"] = False
        else:
            signals[f"{name}_zscore_triggered"] = None

    if srf_result is None:
        signals["srf_usage_nonzero"] = None
    else:
        signals["srf_usage_nonzero"] = bool(srf_result["total_accepted_usd"] > 0)

    signals["pressure_signal_active"] = any(v is True for v in signals.values())
    signals["pressure_data_complete"] = all(
        value is not None
        for key, value in signals.items()
        if key not in META_SIGNAL_KEYS
    )
    return signals


def classify_pressure_level(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    srf_usd: float | None,
    zscore_table: dict | None = None,
    default_window: str = DEFAULT_ZSCORE_WINDOW,
) -> dict:
    """압력 신호들을 research.md 4장의 경고 단계에 맞춰 L0~L3으로 분류한다.

    각 단계의 조건은 OR다. Z-score(체제 상대)와 절대 수준(bp)을 병행하는 이유:
    Z-score만 쓰면 "계속 넓은 채로 굳은" 상태를 놓치고, 절대값만 쓰면 체제 변화를
    못 따라간다.

    srf_usd가 None이면 "조회 실패"이므로 SRF 관련 조건은 판정하지 않고 불완전으로
    표시한다 ("사용액 0"과 혼동하면 안 된다).
    """
    reasons: list[str] = []
    level = 0

    sofr = compute_spread_bp(df, "SOFR", "IORB")
    sofr_now = None if sofr is None or pd.isna(sofr.get(as_of)) else float(sofr.loc[as_of])

    z_now = None
    if zscore_table:
        z_now = zscore_table.get("sofr_minus_iorb", {}).get(default_window)

    # ── L1: SOFR−IORB 단발 이탈 (Z-score 또는 절대 수준) ──
    # Z-score는 단측으로 본다. 스프레드가 평소보다 크게 "낮은" 것(-2σ)은 유동성이
    # 오히려 넉넉하다는 뜻이라 압력이 아니다. abs()를 쓰면 그것까지 경보가 된다
    # (백테스트에서 2026-05 -15bp 구간이 L1로 잡히는 버그로 확인됨).
    zscore_hit = z_now is not None and z_now >= ZSCORE_THRESHOLD
    level_hit = sofr_now is not None and sofr_now >= SPREAD_BP_WATCH
    if zscore_hit or level_hit:
        level = max(level, 1)
        if zscore_hit:
            reasons.append(f"sofr_zscore_{z_now:+.1f}")
        if level_hit:
            reasons.append(f"sofr_spread_{sofr_now:+.0f}bp")

    # ── L2: 이탈 지속 / 더 큰 절대 수준 / SRF 유의미 사용 ──
    if sofr is not None:
        window = sofr.loc[:as_of].tail(PERSISTENCE_WINDOW_DAYS)
        breached = int((window >= SPREAD_BP_WATCH).sum())
        if breached >= PERSISTENCE_MIN_DAYS:
            level = max(level, 2)
            reasons.append(
                f"sofr_persistent_{breached}of{PERSISTENCE_WINDOW_DAYS}d"
            )

    if sofr_now is not None and sofr_now >= SPREAD_BP_ELEVATED:
        level = max(level, 2)
        reasons.append(f"sofr_spread_over_{SPREAD_BP_ELEVATED:.0f}bp")

    if srf_usd is not None and srf_usd >= SRF_USD_ELEVATED:
        level = max(level, 2)
        reasons.append(f"srf_{srf_usd/1e9:.1f}B")

    # ── L3: 극단 스프레드 / SRF 대규모 ──
    if sofr_now is not None and sofr_now >= SPREAD_BP_CRITICAL:
        level = max(level, 3)
        reasons.append(f"sofr_spread_over_{SPREAD_BP_CRITICAL:.0f}bp")

    if srf_usd is not None and srf_usd >= SRF_USD_CRITICAL:
        level = max(level, 3)
        reasons.append(f"srf_{srf_usd/1e9:.1f}B_critical")

    complete = sofr_now is not None and srf_usd is not None
    return {
        "level": level,
        "label": ["L0", "L1", "L2", "L3"][level],
        "reasons": reasons,
        "data_complete": complete,
        "sofr_minus_iorb_bp": None if sofr_now is None else round(sofr_now, 2),
    }


def pressure_level_history(
    df: pd.DataFrame,
    dates: pd.DatetimeIndex,
    srf_by_date: dict[str, dict] | None,
) -> tuple[list[int | None], list[float | None]]:
    """날짜마다 압력 사다리를 다시 돌려 (단계, 6M Z-score) 목록을 만든다.

    대시보드의 "압력 단계 타임라인"용. 판정은 오늘 값과 똑같이 classify_pressure_level을
    쓴다 — 별도 로직을 두면 타임라인과 오늘 배지가 서로 다른 말을 할 수 있다.

    srf_by_date가 None(조회 실패)이면 SRF 조건은 판정하지 않는다. 조회는 됐는데
    그날 기록이 없으면 사용액 0으로 본다. 스프레드 자체가 없는 날은 단계를 None으로 둔다.
    """
    window = ZSCORE_WINDOWS[DEFAULT_ZSCORE_WINDOW]
    spread = compute_spread_bp(df, "SOFR", "IORB")
    if spread is None:
        return [None] * len(dates), [None] * len(dates)
    zser = compute_zscore(spread, window)

    levels: list[int | None] = []
    zscores: list[float | None] = []
    for d in dates:
        z = zser.get(d)
        z = None if z is None or pd.isna(z) else float(z)
        zscores.append(None if z is None else round(z, 3))
        if pd.isna(spread.get(d)):
            levels.append(None)
            continue
        if srf_by_date is None:
            srf = None
        else:
            srf = srf_by_date.get(d.strftime("%Y-%m-%d"), {}).get("total", 0.0)
        ztable = {"sofr_minus_iorb": {DEFAULT_ZSCORE_WINDOW: z}}
        levels.append(classify_pressure_level(df, d, srf, ztable)["level"])
    return levels, zscores


def quantity_direction(
    change: float | None,
    reserves_level: float | None,
    deadzone_ratio: float = QUANTITY_DEADZONE_RATIO,
) -> str | None:
    """수량 방향을 up/flat/down으로 판정한다.

    부호만 보면 +0.001조 같은 미세 변동도 "증가"가 되므로, 지준 수준 대비
    일정 비율 안쪽은 "보합"으로 둔다.
    """
    if change is None or pd.isna(change):
        return None
    band = abs(reserves_level) * deadzone_ratio if reserves_level else 0.0
    if change > band:
        return "up"
    if change < -band:
        return "down"
    return "flat"


def determine_status(
    pressure_level: int, direction: str | None
) -> tuple[str, list[str]]:
    """압력 우선 규칙으로 최종 상태를 판정한다.

    압력이 수량을 이긴다 — 유동성이 늘고 있어도 압력 신호가 켜지면 경고다.
    가격(압력)이 수량보다 먼저 반응한다는 게 research.md의 전제이므로 이 순서를
    뒤집으면 경보가 항상 늦는다.
    """
    if pressure_level >= 3:
        return "critical", ["pressure_L3"]
    if pressure_level == 2:
        return "warning", ["pressure_L2"]
    if pressure_level == 1:
        if direction == "down":
            return "warning", ["pressure_L1", "quantity_down"]
        return "watch", ["pressure_L1"]
    if direction is None:
        return "unknown", ["quantity_unavailable"]
    if direction == "up":
        return "healthy", ["no_pressure", "quantity_up"]
    if direction == "flat":
        return "neutral", ["no_pressure", "quantity_flat"]
    return "watch", ["no_pressure", "quantity_down"]


def decompose_liquidity_change(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    window_days: int = DECOMPOSITION_WINDOW_DAYS,
) -> dict:
    """Net Liquidity 변화가 무엇 때문이었는지 분해한다 (research.md 3.4절).

    연준발(QT: TREAST 감소)인지 재무부발(TGA 충전: WTREGEN 증가)인지 구분하는 게
    핵심 — 기존 공식은 TGA·RRP를 똑같이 빼기만 해서 이 차이를 못 잡는다.
    """
    deltas: dict[str, float | None] = {}
    # WALCL/WSHOMCB/WCURCIR는 대시보드의 요인 막대용이다. TREAST만 보면 MBS 상환이
    # 국채 증가를 상쇄해 연준 총자산이 오히려 줄어든 달을 "연준이 돈을 풀었다"로
    # 오해하게 된다(2026-09: TREAST +0.020, MBS −0.020, WALCL −0.012).
    # 대차대조표 항등식 ΔWRESBAL = ΔWALCL − ΔTGA − ΔRRP − ΔWCURCIR − Δ기타 부채로
    # 나머지는 잔차가 된다.
    columns = {
        "delta_treast_trillions": "TREAST",
        "delta_wtregen_trillions": "WTREGEN",
        "delta_rrpontsyd_trillions": "RRPONTSYD",
        "delta_wresbal_trillions": "WRESBAL",
        "delta_walcl_trillions": "WALCL",
        "delta_wshomcb_trillions": "WSHOMCB",
        "delta_wcurcir_trillions": "WCURCIR",
    }

    for key, col in columns.items():
        if col not in df.columns:
            deltas[key] = None
            continue
        change = df[col].diff(window_days).loc[as_of]
        deltas[key] = None if pd.isna(change) else float(change)

    driver_labels = {
        "delta_treast_trillions": ("QE", "QT"),
        "delta_wtregen_trillions": ("TGA_refill", "TGA_drawdown"),
        "delta_rrpontsyd_trillions": ("RRP_inflow", "RRP_outflow"),
    }
    candidates = {
        key: value
        for key, value in deltas.items()
        if key in driver_labels and value is not None
    }

    if candidates:
        top_key = max(candidates, key=lambda k: abs(candidates[k]))
        positive_label, negative_label = driver_labels[top_key]
        primary_driver = (
            positive_label if candidates[top_key] > 0 else negative_label
        )
    else:
        primary_driver = None

    return {
        "window_days": window_days,
        **deltas,
        "primary_driver": primary_driver,
        "interpretation": _interpret_decomposition(deltas),
    }


def _interpret_decomposition(deltas: dict[str, float | None]) -> str:
    """research.md 3.4절의 TGA/RRP 시소 판단 표를 라벨로 옮긴다.

    | TGA ↑, RRP ↓, 지준 유지 | 완충 작동, 충격 작음      |
    | TGA ↑, 지준 ↓           | 실질 유동성 흡수, 경계    |
    | TGA ↓, 지준 ↑           | 정부 지출로 유동성 공급   |
    """
    tga = deltas.get("delta_wtregen_trillions")
    rrp = deltas.get("delta_rrpontsyd_trillions")
    reserves = deltas.get("delta_wresbal_trillions")

    if tga is None or reserves is None:
        return "insufficient_data"

    reserves_flat = abs(reserves) < RESERVES_FLAT_THRESHOLD_TRILLIONS

    if tga > 0 and rrp is not None and rrp < 0 and reserves_flat:
        return "buffer_absorbed"
    if tga > 0 and reserves < 0 and not reserves_flat:
        return "reserve_drain_warning"
    if tga < 0 and reserves > 0 and not reserves_flat:
        return "government_spending_supply"
    return "mixed_or_other"


def build_sections(
    df: pd.DataFrame, as_of: pd.Timestamp, srf_result: dict | None
) -> tuple[dict, dict, list[str]]:
    """latest.json에 넣을 pressure/assessment 섹션과 추가 경고 목록을 만든다."""
    spreads: dict[str, pd.Series] = {}
    spreads_bp: dict[str, float | None] = {}
    warnings: list[str] = []

    for name, (rate_col, benchmark_col) in SPREAD_DEFINITIONS.items():
        spread = compute_spread_bp(df, rate_col, benchmark_col)
        if spread is None:
            spreads_bp[name] = None
            warnings.append(
                f"{name}: {rate_col} 또는 {benchmark_col} 시리즈가 없어 계산 불가"
            )
            continue
        spreads[name] = spread
        value = spread.loc[as_of]
        # 부동소수점 잡음(-2.9999999999999805 같은 값) 제거 — bp 단위에서
        # 소수점 둘째 자리 아래는 의미가 없다.
        spreads_bp[name] = None if pd.isna(value) else round(float(value), 2)

    zscore_table, zscore_diagnostics, zscore_warnings = latest_zscore_table(
        df, as_of, spreads
    )
    warnings.extend(zscore_warnings)

    # 시리즈 자체가 없어 스프레드를 계산조차 못 한 경우에도 신호 자리를 만들어 둔다.
    # 자리를 비워두면 determine_pressure_signals가 그 신호를 아예 모르게 되어
    # "확인 못 했는데 데이터는 완전하다"고 보고해버린다 (확인 불가 ≠ 압력 없음).
    for name in SPREAD_DEFINITIONS:
        if name not in zscore_table:
            zscore_table[name] = {label: None for label in ZSCORE_WINDOWS}
            zscore_diagnostics[name] = {
                label: "missing_series" for label in ZSCORE_WINDOWS
            }

    signals = determine_pressure_signals(zscore_table, zscore_diagnostics, srf_result)

    srf_usd = None if srf_result is None else srf_result["total_accepted_usd"]
    ladder = classify_pressure_level(df, as_of, srf_usd, zscore_table)

    net_liquidity_change = None
    if "net_liquidity_30d_change_trillions" in df.columns:
        value = df.loc[as_of, "net_liquidity_30d_change_trillions"]
        net_liquidity_change = None if pd.isna(value) else float(value)

    reserves_level = None
    if "WRESBAL" in df.columns and not pd.isna(df.loc[as_of, "WRESBAL"]):
        reserves_level = float(df.loc[as_of, "WRESBAL"])

    direction = quantity_direction(net_liquidity_change, reserves_level)
    status, status_reasons = determine_status(ladder["level"], direction)
    if ladder["reasons"]:
        status_reasons = status_reasons + ladder["reasons"]

    if not ladder["data_complete"]:
        warnings.append(
            "압력 지표 일부를 확인하지 못했습니다 — 낮은 단계(L0/L1)를 "
            "'압력 없음'으로 해석하면 안 됩니다"
        )

    as_of_str = as_of.strftime("%Y-%m-%d")
    pressure = {
        "as_of_date": as_of_str,
        "spreads_bp": spreads_bp,
        "zscore": zscore_table,
        # Z-score가 null인 칸이 왜 null인지 (관측치 부족인지, 변동이 아예 없어서인지).
        # 값이 정상 계산된 칸은 여기 나타나지 않는다.
        "zscore_undefined_reason": {
            name: {w: r for w, r in per_window.items() if r is not None}
            for name, per_window in zscore_diagnostics.items()
            if any(r is not None for r in per_window.values())
        },
        "zscore_window_default": DEFAULT_ZSCORE_WINDOW,
        "zscore_threshold": ZSCORE_THRESHOLD,
        "srf_usage": srf_result,
        "signals": signals,
        "level": ladder["level"],
        "level_label": ladder["label"],
        "level_reasons": ladder["reasons"],
        "level_data_complete": ladder["data_complete"],
        "thresholds": {
            "spread_bp": {"watch": SPREAD_BP_WATCH, "elevated": SPREAD_BP_ELEVATED,
                          "critical": SPREAD_BP_CRITICAL},
            "srf_usd": {"elevated": SRF_USD_ELEVATED, "critical": SRF_USD_CRITICAL},
                "persistence": f"{PERSISTENCE_MIN_DAYS}/{PERSISTENCE_WINDOW_DAYS}d",
        },
    }

    assessment = {
        "as_of_date": as_of_str,
        "net_liquidity_30d_change_trillions": net_liquidity_change,
        "quantity_direction": direction,
        "quantity_deadzone_trillions": (
            None if reserves_level is None
            else round(reserves_level * QUANTITY_DEADZONE_RATIO, 4)
        ),
        "pressure_level": ladder["level"],
        "status": status,
        "status_reasons": status_reasons,
        "decomposition": decompose_liquidity_change(df, as_of),
    }

    return pressure, assessment, warnings

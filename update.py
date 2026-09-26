"""
FRED 유동성 지표 수집 스크립트.

FRED 공개 CSV 엔드포인트에서 연준 대차대조표/유동성 관련 시리즈를 받아와
단위를 정규화하고, 영업일 기준으로 정렬(ffill)한 뒤, latest.json 스냅샷으로 기록한다.

latest.json은 이후 단계(판단 로직, 대시보드, MCP 서버)의 유일한 입력 소스가 되도록
설계되었다 — 소비자는 원본 FRED 데이터를 다시 받을 필요 없이 이 파일만 읽으면 된다.

실행:
    python update.py

exit code:
    0 — 성공 (필수 시리즈를 모두 받아옴)
    1 — 실패 (필수 시리즈 중 하나라도 못 받아옴)
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import requests

import assess

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "liquidity-alert/0.1 (+https://github.com/)"

# 시리즈 ID -> 메타데이터.
# unit: "millions" | "billions" | "raw" (raw는 퍼센트/지수 등 정규화 불필요)
# freq: "daily" | "weekly" (참고용 메타. align_daily는 실제 관측치 간격으로 ffill하므로
#       이 값 자체가 로직을 분기하지는 않지만 latest.json에 기록해 소비자에게 알려준다)
# display_unit: latest.json의 series.*.normalized_unit에 그대로 쓰이는 표시용 단위.
#       "raw" 시리즈(퍼센트/지수 등)는 종류가 다 다르므로 시리즈별로 명시한다
#       (예전엔 latest_snapshot()에서 series_id로 하드코딩 분기했으나, 2단계에서
#       압력 지표가 추가되며 그 분기가 계속 늘어나는 걸 막기 위해 메타로 옮김).
#
# 각 지표가 무엇을 의미하는지, 파생값(compute_derived)이 뭘 계산하는지는
# doc/data_dictionary.md에 표로 정리되어 있음.
SERIES = {
    "WALCL": {"unit": "millions", "freq": "weekly"},
    # research.md/CLAUDE.md는 원래 "영업일"로 기술했으나, 1단계 구현 중 실측
    # 결과 실제로는 주간(약 7일 간격) 시리즈로 확인됨.
    "WTREGEN": {"unit": "millions", "freq": "weekly"},
    "RRPONTSYD": {"unit": "billions", "freq": "daily"},
    "WRESBAL": {"unit": "millions", "freq": "weekly"},
    "TREAST": {"unit": "millions", "freq": "weekly"},
    "WSHOMCB": {"unit": "millions", "freq": "weekly"},
    "WSHOSHO": {"unit": "millions", "freq": "weekly"},
    # 문서(data_dictionary.md 초안)와 코드 모두 "백만 달러"로 적혀 있었으나, 실측
    # 결과 FRED 표기는 Billions of U.S. Dollars였다 (최신값 25804.4 = 25.8조).
    # millions로 두면 1000배 작게(0.0258조) 기록돼 지준/은행총자산 비율이
    # 11.7%가 아니라 11679%로 나왔다. DXY/WTREGEN 건과 같은 "문서 != 실측" 사례.
    "TLAACBW027SBOG": {"unit": "billions", "freq": "weekly"},
    "DFII10": {"unit": "raw", "freq": "daily", "display_unit": "percent"},
    # DXY는 유효한 FRED 시리즈가 아니다 (404 확인됨). 가장 가까운 대체는
    # Nominal Broad U.S. Dollar Index (Goods and Services) = DTWEXBGS.
    "DTWEXBGS": {"unit": "raw", "freq": "daily", "display_unit": "index"},
    # 2단계: 압력 지표 (자금시장 스트레스 조기 감지용). SOFR-IORB 스프레드
    # 계산에 쓰인다 (assess.py). FRED에 존재 확인됨(실측).
    "SOFR": {"unit": "raw", "freq": "daily", "display_unit": "percent"},
    # IORB는 2021-07-29부터 시작 (그 이전엔 IOER). 과거 시점 재실행 시
    # 2Y Z-score 윈도우가 못 채워질 수 있음 — assess.py의 min_periods로 처리.
    "IORB": {"unit": "raw", "freq": "daily", "display_unit": "percent"},
    # EFFR은 판정 로직에서 제외해 수집도 중단했다 (사용자 요청). 되살리려면 이 줄의
    # 주석을 풀고 assess.py의 SPREAD_DEFINITIONS·L3 조건도 함께 되돌릴 것.
    # "EFFR": {"unit": "raw", "freq": "daily", "display_unit": "percent"},
    # 유통화폐. 연준 부채를 지준/유통화폐/TGA/RRP/기타로 쪼개 보여주는
    # 구성 차트에 필요하다. 3년 변동폭이 0.16조로 다섯 칸 중 가장 안정적이라,
    # Net Liquidity에서 이걸 빼면 지준+기타에 도달한다(대시보드 해설에 쓰임).
    "WCURCIR": {"unit": "millions", "freq": "weekly"},
    # 대시보드에서 유동성 지표와 오버레이 비교하기 위한 주가지수.
    # FRED의 SP500은 라이선스 문제로 최근 10년치만 제공된다 (실측: 2016-09-26
    # 시작, 2608행). 이 프로젝트 용도로는 충분하지만 장기 백테스트엔 부족하다.
    # 휴장일은 빈 값으로 오며 na_values 처리 후 영업일 ffill된다.
    "SP500": {"unit": "raw", "freq": "daily", "display_unit": "index"},
}

# Net Liquidity 계산에 필요한, 없으면 스크립트를 실패시켜야 하는 시리즈.
REQUIRED_SERIES = {"WALCL", "WTREGEN", "RRPONTSYD"}

UNIT_TO_TRILLIONS = {
    "millions": 1e6,
    "billions": 1e3,
}

SCHEMA_VERSION = 2
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
LATEST_JSON_PATH = os.path.join(REPO_ROOT, "latest.json")
HISTORY_JSON_PATH = os.path.join(REPO_ROOT, "history.json")

# 대시보드 차트용 시계열 길이. 3년이면 RRP가 1.57조에서 0으로 고갈되는 궤적이
# 다 들어간다 — 이 프로젝트가 설명하려는 핵심 변화다.
HISTORY_YEARS = 3

# 일별로 남긴다. 주 단위로 솎으면 분기말 레포 스파이크(2025-10-31 +32bp 같은)가
# 통째로 사라져 압력 차트가 무의미해진다. 3년 일별이어도 100KB 안쪽이다.
HISTORY_COLUMNS = [
    "WALCL", "WTREGEN", "RRPONTSYD", "WRESBAL", "WCURCIR",
    "TREAST", "WSHOMCB", "TLAACBW027SBOG", "SOFR", "IORB", "SP500",
]
HISTORY_DERIVED = [
    "net_liquidity_trillions",
    "net_liquidity_30d_change_trillions",
]


def fetch_series(series_id: str) -> pd.Series:
    """FRED CSV 엔드포인트에서 시리즈 하나를 받아와 pd.Series로 반환한다.

    실패(네트워크 에러, HTTP 에러, 빈/이상 응답)하면 예외를 던진다 — 호출자가
    개별 시리즈 실패를 어떻게 처리할지 결정한다.
    """
    url = FRED_CSV_URL.format(series_id=series_id)
    resp = requests.get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()

    # FRED CSV의 결측값은 과거 "." 표기였으나 현재는 빈 문자열로도 온다.
    # 둘 다 방어적으로 NaN 처리한다.
    df = pd.read_csv(
        io.StringIO(resp.text),
        na_values=[".", ""],
        parse_dates=["observation_date"],
        index_col="observation_date",
    )
    series = df.squeeze("columns")
    if not isinstance(series, pd.Series):
        raise ValueError(f"{series_id}: 예상치 못한 CSV 형식 (컬럼이 1개가 아님)")
    series.name = series_id
    return series.dropna()


def fetch_all(series_map: dict) -> dict[str, pd.Series]:
    """모든 시리즈를 받아온다. 개별 시리즈 실패는 로그만 남기고 결과에서 제외한다.

    cron으로 무인 실행될 것을 감안해, 시리즈 하나가 죽어도 전체가 죽지 않게 한다.
    """
    result: dict[str, pd.Series] = {}
    for series_id in series_map:
        try:
            result[series_id] = fetch_series(series_id)
            log.info("fetched %s (%d rows)", series_id, len(result[series_id]))
        except Exception as exc:  # noqa: BLE001 - 의도적으로 광범위하게 잡아 스킵
            log.warning("failed to fetch %s: %s", series_id, exc)
    return result


def normalize_units(raw: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """단위를 조 달러(trillions)로 통일한다. raw(퍼센트/지수) 시리즈는 그대로 둔다."""
    normalized = {}
    for series_id, series in raw.items():
        unit = SERIES[series_id]["unit"]
        divisor = UNIT_TO_TRILLIONS.get(unit, 1.0)
        normalized[series_id] = series / divisor
    return normalized


def align_daily(normalized: dict[str, pd.Series]) -> pd.DataFrame:
    """모든 시리즈를 영업일 인덱스로 맞추고 forward-fill한다.

    주간 발표 시리즈(WALCL 등)를 다운샘플하지 않고, 영업일 인덱스에 ffill해서
    "마지막으로 발표된 값"이 매일 유지되도록 한다.
    """
    if not normalized:
        return pd.DataFrame()

    start = min(s.index.min() for s in normalized.values())
    end = max(s.index.max() for s in normalized.values())
    business_days = pd.date_range(start=start, end=end, freq="B")

    aligned = {}
    for series_id, series in normalized.items():
        aligned[series_id] = series.reindex(business_days).ffill()

    return pd.DataFrame(aligned)


def _last_valid_observation_date(raw_series: pd.Series, as_of: pd.Timestamp) -> pd.Timestamp:
    """as_of 이전(포함)의 마지막 실제 관측일을 반환한다 (ffill 여부 판단용)."""
    valid = raw_series.index[raw_series.index <= as_of]
    return valid.max()


def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """2단계(판단 로직)가 바로 쓸 수 있는 파생값을 계산한다.

    여기서는 "계산"까지만 하고 "해석"(양호/경계/위험 라벨)은 하지 않는다 —
    그건 압력 지표 우선 규칙을 따르는 2단계의 책임이다.
    """
    out = df.copy()

    if {"WALCL", "WTREGEN", "RRPONTSYD"}.issubset(out.columns):
        out["net_liquidity_trillions"] = (
            out["WALCL"] - out["WTREGEN"] - out["RRPONTSYD"]
        )
        out["net_liquidity_30d_change_trillions"] = out[
            "net_liquidity_trillions"
        ].diff(30)

    if "WALCL" in out.columns:
        out["walcl_wow_change_trillions"] = out["WALCL"].diff(7)

    if "WRESBAL" in out.columns:
        out["reserves_trillions"] = out["WRESBAL"]

    if "TREAST" in out.columns:
        out["fed_ust_holdings_trillions"] = out["TREAST"]

    if "WSHOMCB" in out.columns:
        out["fed_mbs_holdings_trillions"] = out["WSHOMCB"]

    return out


def latest_snapshot(df: pd.DataFrame, raw: dict[str, pd.Series]) -> dict:
    """최신 영업일 기준 스냅샷 dict를 만든다."""
    if df.empty:
        raise ValueError("정렬된 데이터프레임이 비어 있어 스냅샷을 만들 수 없습니다")

    as_of = df.index.max()
    warnings: list[str] = []
    series_out: dict[str, dict] = {}

    for series_id, meta in SERIES.items():
        if series_id not in raw or series_id not in df.columns:
            continue

        raw_series = raw[series_id]
        obs_date = _last_valid_observation_date(raw_series, as_of)
        is_ffilled = obs_date != as_of

        if meta["unit"] in UNIT_TO_TRILLIONS:
            norm_unit = "trillions_usd"
            raw_unit = f"{meta['unit']}_usd"
        else:
            norm_unit = meta.get("display_unit", "raw")
            raw_unit = norm_unit

        series_out[series_id] = {
            "raw_value": float(raw_series.loc[obs_date]),
            "raw_unit": raw_unit,
            "normalized_value": float(df.loc[as_of, series_id]),
            "normalized_unit": norm_unit,
            "observation_date": obs_date.strftime("%Y-%m-%d"),
            "publication_frequency": meta["freq"],
            "is_forward_filled": bool(is_ffilled),
        }

        if is_ffilled:
            warnings.append(
                f"{series_id}: forward-filled from {obs_date.strftime('%Y-%m-%d')}"
            )

    derived_cols = [
        "net_liquidity_trillions",
        "net_liquidity_30d_change_trillions",
        "walcl_wow_change_trillions",
        "reserves_trillions",
        "fed_ust_holdings_trillions",
        "fed_mbs_holdings_trillions",
    ]
    derived_out = {}
    for col in derived_cols:
        if col in df.columns:
            value = df.loc[as_of, col]
            derived_out[col] = None if pd.isna(value) else float(value)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": FRED_CSV_URL,
        "as_of_date": as_of.strftime("%Y-%m-%d"),
        "series": series_out,
        "derived": derived_out,
        "warnings": warnings,
    }


def build_history(df: pd.DataFrame, years: int = HISTORY_YEARS) -> dict:
    """대시보드 차트가 읽을 시계열을 만든다.

    latest.json은 최신 스냅샷 하나뿐이라 선 그래프를 그릴 수 없다. 브라우저가
    FRED를 직접 부르는 건 느리고 CORS도 걸리므로, 여기서 미리 뽑아 파일로 낸다.

    날짜 배열 하나 + 시리즈별 값 배열 구조로 낸다(레코드 배열보다 훨씬 작다).
    """
    as_of = df.index.max()
    start = as_of - pd.DateOffset(years=years)
    window = df.loc[start:as_of]

    def column(name: str) -> list | None:
        if name not in window.columns:
            return None
        return [None if pd.isna(v) else round(float(v), 6) for v in window[name]]

    series = {c: column(c) for c in HISTORY_COLUMNS if column(c) is not None}
    derived = {c: column(c) for c in HISTORY_DERIVED if column(c) is not None}

    # 압력 차트용 스프레드는 여기서 계산해 둔다 (브라우저가 두 시리즈를 빼는 것보다
    # 단위 실수 여지가 없다).
    if {"SOFR", "IORB"}.issubset(window.columns):
        spread = (window["SOFR"] - window["IORB"]) * 100
        derived["sofr_minus_iorb_bp"] = [
            None if pd.isna(v) else round(float(v), 2) for v in spread
        ]

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frequency": "business_daily",
        "start": window.index.min().strftime("%Y-%m-%d"),
        "end": as_of.strftime("%Y-%m-%d"),
        "count": len(window),
        "units": {
            "amounts": "trillions_usd",
            "rates": "percent",
            "spreads": "basis_points",
            "SP500": "index",
        },
        "dates": [d.strftime("%Y-%m-%d") for d in window.index],
        "series": series,
        "derived": derived,
    }


def write_latest_json(snapshot: dict, path: str) -> None:
    """latest.json을 원자적으로 쓴다 (동시 읽기 도중 잘림 방지)."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp_path, path)


def main() -> int:
    raw = fetch_all(SERIES)

    missing_required = REQUIRED_SERIES - raw.keys()
    if missing_required:
        log.error(
            "필수 시리즈를 받아오지 못했습니다: %s", ", ".join(sorted(missing_required))
        )
        return 1

    normalized = normalize_units(raw)
    aligned = align_daily(normalized)
    derived = compute_derived(aligned)
    snapshot = latest_snapshot(derived, raw)

    # 2단계: 압력 지표 + 종합 판단. SRF는 FRED가 아닌 뉴욕 연은 API에서 오므로
    # 여기서 따로 조회한다 (실패해도 None으로 흘려보내고 파이프라인은 계속).
    as_of = derived.index.max()
    srf_result = assess.fetch_srf_usage()
    pressure, assessment, assess_warnings = assess.build_sections(
        derived, as_of, srf_result
    )
    snapshot["pressure"] = pressure
    snapshot["assessment"] = assessment
    snapshot["warnings"].extend(assess_warnings)

    write_latest_json(snapshot, LATEST_JSON_PATH)

    history = build_history(derived)
    write_latest_json(history, HISTORY_JSON_PATH)

    log.info(
        "latest.json 갱신 완료: as_of=%s, status=%s",
        snapshot["as_of_date"],
        assessment["status"],
    )
    log.info(
        "history.json 갱신 완료: %s~%s (%d영업일, %d개 시리즈)",
        history["start"],
        history["end"],
        history["count"],
        len(history["series"]) + len(history["derived"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

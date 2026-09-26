"""
유동성 데이터 MCP 서버.

update.py가 수집한 지표와 assess.py의 판단 로직을 MCP 도구로 노출해, Claude가
대화 중에 직접 조회할 수 있게 한다. latest.json은 최신 스냅샷 하나뿐이지만
여기서는 과거 시계열까지 열어주므로 "그때는 어땠나"를 물어볼 수 있다.

실행:
    python mcp_server.py                 # stdio (Claude Code·데스크톱용, 기본)
    python mcp_server.py --http          # streamable-http (Claude 웹용, 주소 필요)

Claude Code 등록:
    claude mcp add liquidity -- /절대경로/.venv/bin/python /절대경로/mcp_server.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

import pandas as pd
from mcp.server import MCPServer

import assess
import update

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
LATEST_JSON = os.path.join(REPO_ROOT, "data", "latest.json")

# FRED에서 13개 시리즈를 받는 데 10초 안팎이 걸린다. 도구를 부를 때마다 새로
# 받으면 대화가 끊기므로 메모리에 캐시하고 주기적으로만 갱신한다. 원본 데이터가
# 하루 한 번 갱신되는 성격이라 1시간이면 충분히 신선하다.
CACHE_TTL_SECONDS = 3600

mcp = MCPServer(
    "liquidity",
    title="미국 달러 유동성",
    instructions=(
        "연준 대차대조표 기반 달러 유동성 데이터를 조회하는 서버. "
        "수위 지표(Net Liquidity, 지급준비금)와 압력 지표(SOFR-IORB 스프레드, "
        "SRF 사용액), 그리고 둘을 합친 4단계 상태 판정을 제공한다. "
        "이 지표는 자산 가격을 예측하지 못한다 — 방향과 환경을 설명하는 용도다."
    ),
    version="0.1.0",
)


class _DataCache:
    """정렬된 지표 DataFrame을 캐시한다. 스레드 안전."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._df: pd.DataFrame | None = None
        self._fetched_at: float = 0.0

    def get(self) -> pd.DataFrame:
        with self._lock:
            fresh = self._df is not None and (time.time() - self._fetched_at) < self._ttl
            if fresh:
                return self._df

            log.info("FRED에서 시리즈 수집 중...")
            raw = update.fetch_all(update.SERIES)
            missing = update.REQUIRED_SERIES - raw.keys()
            if missing:
                raise RuntimeError(
                    f"필수 시리즈를 받지 못했습니다: {', '.join(sorted(missing))}"
                )
            aligned = update.align_daily(update.normalize_units(raw))
            self._df = update.compute_derived(aligned)
            self._fetched_at = time.time()
            log.info("수집 완료: %d행", len(self._df))
            return self._df

    @property
    def age_seconds(self) -> float | None:
        return None if self._df is None else time.time() - self._fetched_at


_cache = _DataCache()


def _resolve_date(df: pd.DataFrame, date: str | None) -> pd.Timestamp:
    """날짜 문자열을 데이터에 존재하는 영업일로 맞춘다.

    주말·공휴일을 넣어도 직전 영업일로 내려준다 — 사용자가 "2025-10-31"처럼
    자연스럽게 물어보는데 그날이 영업일이 아니라고 에러를 내면 불친절하다.
    """
    if date is None:
        return df.index.max()
    ts = pd.Timestamp(date)
    prior = df.index[df.index <= ts]
    if len(prior) == 0:
        raise ValueError(
            f"{date}는 데이터 시작일({df.index.min().date()})보다 이릅니다"
        )
    return prior.max()


def _round(value, digits: int = 4):
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


@mcp.tool()
def get_current_state() -> dict:
    """지금 유동성 상태를 요약해서 반환한다.

    최종 판정(healthy/neutral/watch/warning/critical), 압력 사다리 단계(L0~L3),
    Net Liquidity와 지급준비금 수준, 그 변화를 무엇이 주도했는지를 담는다.
    가장 먼저 호출하기 좋은 도구.
    """
    if not os.path.exists(LATEST_JSON):
        raise RuntimeError("latest.json이 없습니다. 먼저 python update.py를 실행하세요.")
    snap = json.load(open(LATEST_JSON, encoding="utf-8"))
    return {
        "as_of": snap["as_of_date"],
        "status": snap["assessment"]["status"],
        "status_reasons": snap["assessment"]["status_reasons"],
        "pressure_level": snap["pressure"]["level_label"],
        "pressure_reasons": snap["pressure"]["level_reasons"],
        "net_liquidity_trillions": snap["derived"]["net_liquidity_trillions"],
        "net_liquidity_30d_change_trillions": snap["derived"][
            "net_liquidity_30d_change_trillions"
        ],
        "reserves_trillions": snap["derived"]["reserves_trillions"],
        "sofr_minus_iorb_bp": snap["pressure"]["spreads_bp"].get("sofr_minus_iorb"),
        "srf_usage_usd": (snap["pressure"]["srf_usage"] or {}).get("total_accepted_usd"),
        "decomposition": snap["assessment"]["decomposition"],
        "warnings": snap["warnings"],
    }


@mcp.tool()
def list_series() -> dict:
    """조회 가능한 FRED 시리즈 목록과 각각의 의미·단위를 반환한다.

    get_series를 쓰기 전에 어떤 코드가 있는지 확인할 때 호출한다.
    """
    meanings = {
        "WALCL": "연준 총자산",
        "WTREGEN": "TGA (정부 금고)",
        "RRPONTSYD": "ON RRP (역레포)",
        "WRESBAL": "지급준비금",
        "TREAST": "연준 보유 국채",
        "WSHOMCB": "연준 보유 MBS",
        "WSHOSHO": "연준 보유 증권 총액",
        "TLAACBW027SBOG": "상업은행 총자산",
        "DFII10": "10년 물가연동국채 실질금리",
        "DTWEXBGS": "달러 인덱스 (광의)",
        "SOFR": "담보부 조달금리",
        "IORB": "지준 부리금리 (스프레드 기준선)",
        "SP500": "S&P 500 지수",
    }
    return {
        "series": [
            {
                "id": sid,
                "meaning": meanings.get(sid, ""),
                "frequency": meta["freq"],
                "unit": (
                    "trillions_usd"
                    if meta["unit"] in update.UNIT_TO_TRILLIONS
                    else meta.get("display_unit", "raw")
                ),
            }
            for sid, meta in update.SERIES.items()
        ],
        "note": "달러 금액은 모두 조 달러로 정규화되어 반환된다.",
    }


@mcp.tool()
def get_series(series_id: str, start: str | None = None, end: str | None = None) -> dict:
    """특정 시리즈의 시계열을 조회한다.

    Args:
        series_id: FRED 코드 (list_series로 확인). 예: WALCL, WRESBAL, SOFR
        start: 시작일 YYYY-MM-DD. 생략하면 최근 1년.
        end: 종료일 YYYY-MM-DD. 생략하면 최신일.

    포인트가 400개를 넘으면 주 단위로 솎아서 반환한다 (응답이 너무 길어지지 않게).
    """
    df = _cache.get()
    if series_id not in df.columns:
        raise ValueError(
            f"'{series_id}'는 없는 시리즈입니다. list_series로 목록을 확인하세요."
        )

    end_ts = _resolve_date(df, end)
    start_ts = (
        pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=365)
    )
    window = df.loc[start_ts:end_ts, series_id].dropna()

    step = 1
    if len(window) > 400:
        step = len(window) // 400 + 1
        window = window.iloc[::step]

    return {
        "series_id": series_id,
        "start": window.index.min().strftime("%Y-%m-%d") if len(window) else None,
        "end": window.index.max().strftime("%Y-%m-%d") if len(window) else None,
        "count": len(window),
        "sampled_every_n_business_days": step,
        "unit": (
            "trillions_usd"
            if update.SERIES.get(series_id, {}).get("unit") in update.UNIT_TO_TRILLIONS
            else update.SERIES.get(series_id, {}).get("display_unit", "raw")
        ),
        "points": [
            {"date": d.strftime("%Y-%m-%d"), "value": _round(v, 6)}
            for d, v in window.items()
        ],
    }


@mcp.tool()
def assess_date(date: str | None = None) -> dict:
    """특정 날짜 기준으로 압력 사다리와 상태 판정을 다시 계산한다.

    과거 어느 시점이든 그날의 데이터만 가지고 판정하므로 "2025년 10월에는 어땠나"
    같은 질문에 답할 수 있다.

    Args:
        date: YYYY-MM-DD. 생략하면 최신일. 영업일이 아니면 직전 영업일로 맞춘다.

    주의: SRF 사용액은 뉴욕 연은 API에서 최근치만 가져오므로, 과거 날짜를 물으면
    SRF 조건은 판정에서 빠지고 pressure_data_complete가 false가 된다.
    """
    df = _cache.get()
    as_of = _resolve_date(df, date)
    is_latest = as_of == df.index.max()

    srf = assess.fetch_srf_usage() if is_latest else None
    srf_usd = None if srf is None else srf["total_accepted_usd"]

    spread = assess.compute_spread_bp(df, "SOFR", "IORB")
    ztable = {}
    if spread is not None:
        z = assess.compute_zscore(
            spread, assess.ZSCORE_WINDOWS[assess.DEFAULT_ZSCORE_WINDOW]
        ).loc[as_of]
        ztable = {
            "sofr_minus_iorb": {
                assess.DEFAULT_ZSCORE_WINDOW: None if pd.isna(z) else _round(z)
            }
        }

    ladder = assess.classify_pressure_level(df, as_of, srf_usd, ztable)
    change = (
        _round(df.loc[as_of, "net_liquidity_30d_change_trillions"])
        if "net_liquidity_30d_change_trillions" in df.columns
        else None
    )
    reserves = _round(df.loc[as_of, "WRESBAL"]) if "WRESBAL" in df.columns else None
    direction = assess.quantity_direction(change, reserves)
    status, reasons = assess.determine_status(ladder["level"], direction)

    return {
        "as_of": as_of.strftime("%Y-%m-%d"),
        "requested_date": date,
        "is_latest": is_latest,
        "status": status,
        "status_reasons": reasons + ladder["reasons"],
        "pressure_level": ladder["label"],
        "sofr_minus_iorb_bp": ladder["sofr_minus_iorb_bp"],
        "zscore_6m": ztable.get("sofr_minus_iorb", {}).get("6M"),
        "srf_usage_usd": srf_usd,
        "net_liquidity_trillions": _round(df.loc[as_of, "net_liquidity_trillions"]),
        "net_liquidity_30d_change_trillions": change,
        "quantity_direction": direction,
        "pressure_data_complete": ladder["data_complete"],
    }


@mcp.tool()
def decompose_change(date: str | None = None, window_days: int = 30) -> dict:
    """유동성 변화를 연준발·재무부발·완충으로 분해한다.

    Net Liquidity가 움직였을 때 그게 연준이 자산을 줄여서인지(QT), 정부가 금고를
    채우거나 비워서인지(TGA), RRP가 빠져서인지 구분한다. 기존 공식은 TGA와 RRP를
    똑같이 빼기만 해서 이 차이를 못 잡는다.

    Args:
        date: YYYY-MM-DD. 생략하면 최신일.
        window_days: 며칠 전과 비교할지. 기본 30영업일.
    """
    df = _cache.get()
    as_of = _resolve_date(df, date)
    result = assess.decompose_liquidity_change(df, as_of, window_days)
    result["as_of"] = as_of.strftime("%Y-%m-%d")
    result["net_liquidity_change_trillions"] = _round(
        df["net_liquidity_trillions"].diff(window_days).loc[as_of]
    )
    return result


@mcp.tool()
def find_stress_periods(
    min_level: int = 2, start: str | None = None, end: str | None = None
) -> dict:
    """압력 사다리가 특정 단계 이상이었던 날들을 찾는다.

    Args:
        min_level: 최소 단계 (1=주의, 2=경계, 3=심각). 기본 2.
        start: 검색 시작일 YYYY-MM-DD. 생략하면 3년 전.
        end: 검색 종료일. 생략하면 최신일.

    주의: SRF 이력은 반영하지 않고 스프레드 조건만으로 판정하므로, SRF 대규모
    사용으로 올라갔던 날은 여기서 누락될 수 있다.
    """
    if min_level not in (1, 2, 3):
        raise ValueError("min_level은 1, 2, 3 중 하나여야 합니다")

    df = _cache.get()
    end_ts = _resolve_date(df, end)
    start_ts = pd.Timestamp(start) if start else end_ts - pd.Timedelta(days=365 * 3)

    spread = assess.compute_spread_bp(df, "SOFR", "IORB")
    if spread is None:
        raise RuntimeError("SOFR 또는 IORB 시리즈가 없어 판정할 수 없습니다")
    zser = assess.compute_zscore(
        spread, assess.ZSCORE_WINDOWS[assess.DEFAULT_ZSCORE_WINDOW]
    )

    hits = []
    for day in df.loc[start_ts:end_ts].index:
        z = zser.loc[day]
        ztable = {
            "sofr_minus_iorb": {
                assess.DEFAULT_ZSCORE_WINDOW: None if pd.isna(z) else float(z)
            }
        }
        res = assess.classify_pressure_level(df, day, None, ztable)
        if res["level"] >= min_level:
            hits.append(
                {
                    "date": day.strftime("%Y-%m-%d"),
                    "level": res["label"],
                    "sofr_minus_iorb_bp": res["sofr_minus_iorb_bp"],
                    "reasons": res["reasons"],
                }
            )

    return {
        "min_level": f"L{min_level}",
        "searched": {
            "start": start_ts.strftime("%Y-%m-%d"),
            "end": end_ts.strftime("%Y-%m-%d"),
        },
        "count": len(hits),
        "days": hits[-100:],
        "truncated": len(hits) > 100,
        "note": "SRF 이력은 미반영 — 스프레드 조건만으로 판정했다.",
    }


@mcp.tool()
def explain_indicator(name: str) -> dict:
    """지표나 판정 규칙이 무슨 뜻인지 설명한다.

    Args:
        name: 설명할 대상. 예: net_liquidity, reserves, sofr_spread, srf,
              pressure_ladder, tga, rrp
    """
    docs = {
        "net_liquidity": {
            "formula": "WALCL(연준 총자산) − TGA(정부 금고) − RRP(역레포)",
            "meaning": "연준 자산에서 시장 밖에 묶인 두 칸을 뺀, 실제로 도는 유동성",
            "caveat": "유통화폐가 섞여 있어 은행이 굴릴 수 있는 돈보다 항상 크게 나온다",
        },
        "reserves": {
            "formula": "WRESBAL",
            "meaning": "은행이 연준 계좌에 둔 잔액. 실제로 굴릴 수 있는 실탄",
            "caveat": "절대액만으로는 충분한지 알 수 없어 은행 총자산 대비 비율을 함께 본다",
        },
        "sofr_spread": {
            "formula": "(SOFR − IORB) × 100, 단위 bp",
            "meaning": "담보시장 조달금리가 연준 부리금리보다 얼마나 비싼지",
            "caveat": "평상시 중앙값이 −6bp로 음수가 정상이다. 양수 자체가 이상 신호",
        },
        "srf": {
            "formula": "뉴욕 연은 레포 오퍼레이션(=SRF, 점검용 소액 테스트 제외)의 일별 낙찰액 합계",
            "meaning": "민간에서 돈을 못 구해 연준 창구를 쓴 금액 = 조달 실패",
            "caveat": "0이라고 압력이 없다는 뜻은 아니다(낙인 효과). 스프레드와 병행 필수",
        },
        "pressure_ladder": {
            "formula": (
                f"L1: Z≥{assess.ZSCORE_THRESHOLD} 또는 ≥+{assess.SPREAD_BP_WATCH:.0f}bp / "
                f"L2: {assess.PERSISTENCE_MIN_DAYS}/{assess.PERSISTENCE_WINDOW_DAYS}일 지속 또는 "
                f"≥+{assess.SPREAD_BP_ELEVATED:.0f}bp 또는 SRF≥${assess.SRF_USD_ELEVATED/1e9:.0f}B / "
                f"L3: ≥+{assess.SPREAD_BP_CRITICAL:.0f}bp 또는 SRF≥${assess.SRF_USD_CRITICAL/1e9:.0f}B"
            ),
            "meaning": "자금시장 압력의 4단계. 각 단계 조건은 OR",
            "caveat": "압력이 수량을 이긴다 — 유동성이 늘어도 압력이 켜지면 경고다",
        },
        "tga": {
            "formula": "WTREGEN",
            "meaning": "정부가 연준에 둔 금고. 차면 은행 시스템 밖으로 돈이 빠진 것",
            "caveat": "세금 납부기에 급등하는 톱니 모양이라 단기 출렁임의 주범",
        },
        "rrp": {
            "formula": "RRPONTSYD",
            "meaning": "MMF 등이 연준에 하루씩 맡긴 돈. 국채 발행의 완충 역할을 했다",
            "caveat": "2023년 1.57조에서 현재 거의 0으로 고갈 — 이제 발행이 지준을 직접 깎는다",
        },
    }
    key = name.lower().strip()
    if key not in docs:
        return {
            "error": f"'{name}'에 대한 설명이 없습니다",
            "available": sorted(docs.keys()),
        }
    return {"name": key, **docs[key]}


if __name__ == "__main__":
    transport = "streamable-http" if "--http" in sys.argv else "stdio"
    log.info("MCP 서버 시작 (transport=%s)", transport)
    mcp.run(transport=transport)

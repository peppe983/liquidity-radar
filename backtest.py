# -*- coding: utf-8 -*-
"""압력 사다리 백테스트 — 임계값이 실제 위기에서 제대로 켜지는지 검증한다.

임계값(assess.py의 SPREAD_BP_*, SRF_USD_*, EFFR_BP_CRITICAL 등)을 바꿀 때마다 이걸
돌려서 (1) 2019-09 레포 발작과 2020-03에서 최고 단계에 도달하는지, (2) 평시에
오경보가 나지 않는지를 확인한다.

실행:
    python backtest.py

⚠️ IOER 시절(~2021-07)과 IORB 시절은 연준의 금리 운영 체제가 달라, 과거 구간의
발동 일수를 현재 기준으로 그대로 비교하면 안 된다.
"""
import requests

import pandas as pd

import assess
import update

# IOER(2008~2021) + IORB(2021~) 접합으로 기준선 장기 시계열 확보
raw = {i: update.fetch_series(i) for i in ["SOFR", "IORB", "IOER"]}
bench = pd.concat([raw["IOER"], raw["IORB"]])
bench = bench[~bench.index.duplicated(keep="last")].sort_index()

idx = pd.date_range("2018-04-03", raw["SOFR"].index.max(), freq="B")
df = pd.DataFrame({
    "SOFR": raw["SOFR"].reindex(idx).ffill(),
    "IORB": bench.reindex(idx).ffill(),
}).dropna()

# SRF는 2021-07 도입. 그 이전 구간은 None(판정 불가)으로 둔다.
r = requests.get("https://markets.newyorkfed.org/api/rp/results/search.json",
                 params={"startDate": "2021-07-01", "endDate": pd.Timestamp.today().strftime("%Y-%m-%d"),
                         "operationTypes": "Repo"},
                 timeout=30, headers={"User-Agent": "liquidity-alert/0.1"})
srf_by_date = {}
for o in r.json()["repo"]["operations"]:
    if assess.is_srf_operation(o):
        srf_by_date[o["operationDate"]] = srf_by_date.get(o["operationDate"], 0) + float(o.get("totalAmtAccepted") or 0)
srf_start = pd.Timestamp("2021-07-01")

# Z-score 시계열 미리 계산
sofr_sp = assess.compute_spread_bp(df, "SOFR", "IORB")
zser = assess.compute_zscore(sofr_sp, assess.ZSCORE_WINDOWS[assess.DEFAULT_ZSCORE_WINDOW])

rows = []
for d in df.index:
    z = zser.loc[d]
    ztable = {"sofr_minus_iorb": {assess.DEFAULT_ZSCORE_WINDOW: None if pd.isna(z) else float(z)}}
    srf = srf_by_date.get(d.strftime("%Y-%m-%d"), 0.0) if d >= srf_start else None
    res = assess.classify_pressure_level(df, d, srf, ztable)
    rows.append({"date": d, "level": res["level"], "reasons": ";".join(res["reasons"]),
                 "sofr_sp": sofr_sp.loc[d], "complete": res["data_complete"]})
bt = pd.DataFrame(rows).set_index("date")

print("=" * 66)
print("전체 기간 단계 분포:", df.index.min().date(), "~", df.index.max().date(), f"({len(bt)}영업일)")
for lv in range(4):
    n = int((bt["level"] == lv).sum())
    print(f"  L{lv}: {n:5d}일 ({n/len(bt)*100:5.1f}%)")

print()
print("=" * 66)
for tag, a, b in [("2019년 9월 레포 발작", "2019-09-01", "2019-10-15"),
                  ("2020년 3월 코로나", "2020-03-01", "2020-04-15")]:
    w = bt.loc[a:b]
    print(f"[{tag}] 최고 {['L0','L1','L2','L3'][w['level'].max()]}")
    for lv in range(4):
        n = int((w["level"] == lv).sum())
        if n: print(f"    L{lv} {n}일", end="")
    print()
    esc = w[w["level"] > 0]
    if len(esc):
        print(f"    최초 발동: {esc.index[0].date()} → L{esc['level'].iloc[0]} ({esc['reasons'].iloc[0]})")
        peak = w[w["level"] == w["level"].max()]
        print(f"    최고 단계 도달: {peak.index[0].date()} ({peak['reasons'].iloc[0]})")
    print()

print("=" * 66)
print("연도별 L2 이상 발생 일수 (오경보 확인):")
for y, g in bt.groupby(bt.index.year):
    n2 = int((g["level"] >= 2).sum()); n3 = int((g["level"] >= 3).sum())
    print(f"  {y}: L2+ {n2:3d}일 / L3 {n3:3d}일  (총 {len(g)}일)")

print()
print("최근 3년 L1 이상 발생일:")
recent = bt.loc["2023-09-01":]
for d, row in recent[recent["level"] > 0].iterrows():
    print(f"  {d.date()} L{row['level']} · {row['sofr_sp']:+.0f}bp · {row['reasons']}")

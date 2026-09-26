선 차트. y축 하나, 2px 선, 옅은 가로 격자, 범례 + 선 끝 직접 라벨, 세로 크로스헤어 + 툴팁.

- 호출: `LiquidityRadar.chart(el, {dates, series:[{label, short?, color, values, dash?}], fmt, thresholds?, includeZero?, index100?, mini?, height?})`.
- `color`는 토큰 이름(`series-netliq`). 같은 지표는 모든 차트에서 같은 색.
- 단위가 다른 두 값은 `index100: true`로 시작일=100 지수화한다. 두 번째 y축은 없다.
- `thresholds`는 임계 가로선(`{value, label, color}`), 오른쪽 끝에 라벨.
- `dash: true`는 "틀린 계산"처럼 참고용 선에만. 격자는 점선 금지.
- 기간은 `LiquidityRadar.setPeriod("6m"|"1y"|"3y")`로 등록된 모든 차트에 적용된다.
- S&P 500 비교: `LiquidityRadar.setOverlay(true)`(또는 `overlayToggle(button)`)를 켜면 차트 아래에 S&P 500 띠가 붙는다. 띠는 자기 y축(기간 시작=100)을 따로 갖고 x축·크로스헤어·툴팁을 공유한다. 한 축에 겹치지 않는다. 차트별로 끄려면 `overlay: false`.

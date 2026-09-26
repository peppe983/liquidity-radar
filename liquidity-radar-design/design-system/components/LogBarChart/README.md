SRF 사용액 막대, 로그 눈금($10M ~ $100B).

- 호출: `chart(el, {kind: "bars", dates, values})`. 값 단위는 $B.
- 색 구간: $1B 미만 `series-other`(노이즈) · $1B~10B `pressure-2`(주의) · $10B 이상 `pressure-3`(심각). 임계 가로선 $1B / $10B.
- 막대는 모서리 0. 0인 날은 그리지 않는다.
- 툴팁에 금액과 구간 이름을 함께 보여 색에만 의존하지 않는다.

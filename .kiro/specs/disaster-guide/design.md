# 설계 — 호우 위험 구역을 피해 가는 안전 경로 안내 서비스 (광주)

기준 문서: #[[file:requirements.md]]

'초안' 표시가 붙은 값은 사용자가 준 기본값이거나 내가 정한 값이며 바꿀 수 있다. 이번 범위는 **로컬 완성**이다. 팀 서버 배포는 나중에 멘토와 따로 정한다(16절).

## 1. 확정된 결정

| 항목 | 결정 |
| --- | --- |
| 데모 구간 | 광주송정역 → 광주역 (사용자 확정) |
| 강수 단계 | 30 / 50 / 70mm (요구사항 4.5) |
| 배포 | 로컬에서만 완성 |
| 경로 엔진 | pyvalhalla 3.9.1 `valhalla.Actor`, 백엔드 프로세스 안에서 계산, Docker 없음 |
| 지도 | maplibre-gl 6.16.0 + OpenFreeMap `positron`(낮)·`fiord`(밤) 스타일, 출처 표기 유지 |
| 지오메트리 | shapely 2.2.0, 미터 계산은 pyproj 3.8.0으로 EPSG:5179 변환 |
| AI | 경로 설명과 경로 변경 이유만(18, 19절). 공통 AI 코드(ai_service.py, routers/ai.py)와 Record CRUD는 그대로 둠 |
| 기록 저장 | 사용하지 않음. 좌표·검색어·경로를 DB·파일·로그에 남기지 않음 |

## 2. 전체 구조

```
브라우저(React + maplibre)
  └─ 상대 경로 /api/ ─ Vite 프록시 ─ FastAPI (127.0.0.1:8000)
       ├─ api/route.py ─ strategies/(registry) ─ engines/valhalla.py ─ Valhalla Actor(.local-data/valhalla/tiles.tar)
       │                     └─ risk/layer.py, risk/scoring.py ─ data/risk_zones.geojson
       ├─ api/reroute.py ─ reroute.py (운행 중 판단, 19절)
       ├─ api/explain.py ─ route_explainer.py ─ Bedrock (18절)
       ├─ api/tts.py ─ tts.py ─ 서버의 Supertonic (19절)
       ├─ api/weather.py ─ context/weather_kma.py, weather_aws.py, weather_regions.py (키 있음) | weather_mock.py (키 없음·실패)
       ├─ api/search.py ─ 카카오 로컬 (키 있음) | data/demo_points.json (키 없음·실패)
       ├─ api/risk.py, api/strategies.py ─ 정적 데이터·설정
       └─ 기존 /api/health, /api/records, /api/ai/* (유지)
```

```
backend/app/
  api/          route.py, reroute.py, explain.py, tts.py, risk.py, search.py, weather.py, strategies.py
  strategies/   base.py, registry.py, baseline.py, hard_exclude.py, tiered_rain.py, rerank.py
  engines/      base.py, valhalla.py, fake.py
  risk/         layer.py, scoring.py
  context/      weather_kma.py, weather_aws.py, weather_regions.py, weather_mock.py, kakao.py
  config/       strategies.yaml
  data/         risk_zones.geojson, demo_points.json
  reroute.py, route_explainer.py, tts.py
data_pipeline/  build_valhalla_tiles.ps1, pipeline.yaml, zones.py, build_risk_zones.py,
                check_demo_scenario.py, sources/
```

import 시점에는 파일 읽기, Actor 생성, 외부 호출을 하지 않는다. 설정·위험 구역·Actor·좌표 변환기는 처음 필요할 때 만들고 재사용한다. `import valhalla`도 엔진을 처음 만들 때 한다.

## 3. 기상 컨텍스트와 강수 단계 (요구사항 2)

### 3.1 단계 계산

- 강수 단계: 요구사항 4.5 표를 따른다(30mm 미만 0, 30mm 이상 1, 50mm 이상 2, 70mm 이상 3).
- 특보 반영(초안, 요구사항 2.6): 호우주의보는 최소 1단계, 호우경보는 최소 2단계로 올린다. 최종 단계는 `max(강수 단계, 특보 최소 단계)`다.
- 기상청의 '중대경보'(warnStress 2)는 화면에서 '호우경보(중대)'로 표시하고 경보와 같게 반영한다(초안).
- 기준값과 반영 규칙은 `config/strategies.yaml`에 둔다.

### 3.2 기상청 초단기실황 (1시간 강수량)

지금은 AWS 관측소 값(23절)을 먼저 쓰고, 쓸 수 없을 때 이 값을 쓴다. 지점별 조회는 20절에 있다.

- `GET https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst`. 요청 변수는 `serviceKey, pageNo, numOfRows, dataType=JSON, base_date, base_time, nx, ny`다.
- 응답 `response.body.items.item[]`에서 `category == "RN1"`인 `obsrValue`(mm)를 읽는다(공공데이터포털 문서로 확인). 숫자가 아니면 오류로 본다.
- base_time: 한국시간 기준으로 분이 40 미만이면 한 시간 전 정시를, 40 이상이면 이번 정시를 쓴다(초안). 실제 키를 받으면 제공 시각을 확인한다.
- 광주 격자 nx=58, ny=74(초안): 기상청 격자 변환식(LCC, 5km)으로 광주광역시청(35.1600, 126.8514)을 계산한 값이다. 같은 식으로 서울 종로를 계산하면 알려진 값 (60, 127)이 나온다. 사용자 좌표는 기상청에 보내지 않는다(요구사항 2.1).

### 3.3 기상청 특보 (특보코드조회)

공공데이터포털의 '기상특보 조회서비스 오픈API 활용가이드(2026-06-01)'와 별첨 특보구역 코드표로 확인했다.

- `GET https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnCd`
- 요청: `serviceKey, numOfRows=1000, pageNo, dataType=JSON, fromTmFc=YYYYMMDD, toTmFc=YYYYMMDD, warningType=2`(2는 호우).
- 응답 item: `areaCode, areaName, warnVar(2=호우), warnStress(0 주의보, 1 경보, 2 중대경보), command(1 발표, 2 해제, 3 연장, 6 정정, 7 변경발표, 8 변경해제), cancel(1이면 취소된 특보), tmFc, tmSeq, startTime, endTime`.
- 광주 특보구역 코드: `L1130000`(광주광역시), `L1130100`(광주광역시, 2026-05-31부터), `L1130110`(광주서부), `L1130120`(광주동부).
  - 코드표의 `L1013400 광주`는 경기도 광주시(상위 `L1010000`)다. 이름으로 거르면 섞이므로 **코드로만** 거른다.
- 현재 상태 판정(초안):
  1. 최근 3일(오늘 포함)을 조회한다.
  2. `cancel == 1`인 항목은 버린다.
  3. 구역 코드마다 `(tmFc, tmSeq)`가 가장 늦은 항목을 고른다. 그 `command`가 1·3·6·7이면 `warnStress` 단계가 발효 중이고, 2·8이면 해제다.
  4. 광주 코드 중 가장 높은 단계를 쓴다.
- 이 판정은 실제 응답으로 아직 검증하지 못했다. 키를 받으면 확인한다.

### 3.4 캐시와 실패

- 실황과 특보를 함께 조회해 프로세스 메모리에 **10분** 캐시한다(요구사항 2.2). 사용자 정보가 없는 광주 단일 값이라 기록 저장에 해당하지 않는다.
- 실패한 결과는 1분만 캐시한다(초안).
- 실황 실패(키 없음, 오류, 5초 시간 초과, JSON이 아님): `available: false`와 "기상 정보를 가져오지 못했습니다"를 돌려준다. 화면은 데모 모드로 바꾼다(요구사항 2.5).
- 특보만 실패하면 강수량은 쓰고, 특보는 "특보 확인 실패"로 표시하며 단계에 반영하지 않는다(초안).
- 키 처리:
  - `KMA_SERVICE_KEY`는 환경변수로만 읽는다. 공공데이터포털 Encoding 키(`%` 포함)를 넣으면 한 번 디코딩한 뒤 파라미터로 넘긴다.
  - 응답·오류 문구·로그에 키를 넣지 않는다. `httpx`와 `httpcore` 로거는 WARNING 이상만 남겨 키가 든 요청 URL이 찍히지 않게 한다.
  - 공공데이터포털은 키 오류 때 JSON 요청에도 XML을 돌려줄 수 있으므로, JSON이 아니면 오류로 처리한다.

## 4. 위험 구역 데이터 (요구사항 3)

### 4.1 `risk_zones.geojson`

FeatureCollection이다. geometry는 Polygon 또는 MultiPolygon이며, 버퍼를 넣기 전의 원래 구역이다. 회피 버퍼는 실행 중에 붙인다. 정렬은 `id` 순이다.

| 속성 | 설명 |
| --- | --- |
| `id` | 고유 ID (예: `FLD-BUK-0001`) |
| `name` | 표시 이름 |
| `type` | `underpass` / `flood_history` / `riverside` |
| `active` | 사용 여부. false면 경로 계산·지도에서 뺀다 |
| `source_name` | 원본 자료 이름 |
| `source_url` | 출처 URL |
| `checked_at` | 확인일 `YYYY-MM-DD` |
| `is_dummy` | 더미 여부. 지금 자료는 모두 false다. 참이면 화면에 "더미 데이터" 배지를 붙인다 |
| `note` | 위치를 정한 근거 |
| `flood_count`, `elev_m`, `low_pct`, `above_local_min_m`, `elev_status` | 침수 이력만. 원본의 침수 횟수와 DEM 고도 속성(가이드 3-3). 고도가 없으면 `null` |
| `risk_tier`, `tier_reason` | 침수 이력만. 지형 등급(`high`/`normal`/`raised`)과 그 이유(5.8) |
| `centerline`, `block_points` | 지하차도만. 터널 구간 선(MultiLineString)과 구간마다 1개인 엔진 제외 지점(4.5). 화면 API로는 보내지 않는다 |

### 4.2 data_pipeline (요구사항 3.2)

- `pipeline.yaml`(초안)에 원본 형태별 기본 반경을 둔다.
  - 지하차도: 점 50m, 선 12m
  - 침수 이력: 점 30m, 선 12m
  - 하천변: 선 40m
- `zones.py`
  - 점·선을 EPSG:5179에서 반경만큼 버퍼해 다각형으로 바꾼다.
  - 좌표는 소수 6자리로 반올림하고 `id` 순으로 정렬한다. 결과 파일에는 생성 시각을 넣지 않는다. 그래서 같은 입력이면 같은 파일이 나온다.
  - 검증 항목: ID 중복, 유효한 다각형, 광주 범위 안, 허용된 유형, 출처·확인일 존재. 실패하면 파일을 쓰지 않고 멈춘다.
- `build_risk_zones.py`: `sources/*.json` → 버퍼 → 검증 → `backend/app/data/risk_zones.geojson`
- 원본 형식(공공데이터 CSV·SHP 등)별 읽기 함수는 자리만 둔다(`NotImplementedError`).
- `check_demo_scenario.py`: 실제 타일로 시나리오 A의 네 단계 경로를 계산해 표로 출력한다. 더미 배치 확인용 수동 스크립트이며 pytest에 넣지 않는다(요구사항 5.7).

### 4.3 더미 구역 배치 (제거됨)

> 침수 이력은 광주 5개 구의 실제 구청 자료 935곳(`risk_zones_guide.md`)이다. 남아 있던 지하차도·하천변 더미 4곳도 2026-10-30에 지웠다(`sources/dummy_seed.json` 삭제). 지금은 실제 자료만 있다. 지하차도는 4.5절의 22곳이고 하천변은 0곳이다. 아래 표와 시험 결과는 기록으로만 남긴다. 실제 자료에서의 시나리오 A 결과는 5.7절 표를 본다.

baseline 경로(광주송정역 → 광주역)는 광산로 → 상무대로 → 농성지하차도 → 죽봉대로(광주천 건넘) → 서암대로 → 광주역이다. 위치는 OpenStreetMap 도로와 하천을 참고했다(© OpenStreetMap 기여자, ODbL). 위험 여부 자체는 지어낸 값이다.

| ID | 유형 | 위치 | 원본 |
| --- | --- | --- | --- |
| dummy-underpass-1 | 지하차도 | 농성지하차도 | OSM 터널 선, 12m |
| dummy-underpass-2 | 지하차도 | 사암로 지하 구간 | OSM 터널 선, 12m |
| dummy-flood-1 | 침수 이력 | 상무대로 약 400m (baseline 위) | 선, 12m |
| dummy-flood-2 | 침수 이력 | 무진대로 약 450m (1단계 우회로 위) | 선, 12m |
| dummy-riverside-1 | 하천변 | 광주천, 죽봉대로 교차 부근 약 700m | OSM 하천 선, 40m |
| dummy-riverside-2 | 하천변 | 광주천, 양동 부근 약 300m | OSM 하천 선, 40m |

baseline은 세 유형을 모두 지난다(요구사항 3.4, 시연 데모 구간 조건). 이 배치로 Valhalla 실제 계산을 한 시험 결과는 아래와 같다. 노출 길이는 구역 안을 지난 길이이며 구현 후 값이 조금 달라질 수 있다.

| 강수량 | 단계 | 소요 | 거리 | 지나는 구역 | 위험 노출 점수 |
| --- | --- | --- | --- | --- | --- |
| 0mm | 0 | 931초 | 13.65km | 지하차도 65m, 침수 424m, 하천변 94m | 1137 |
| 35mm | 1 | 946초 | 15.16km | 침수(무진대로) 474m, 하천변 94m | 1042 |
| 55mm | 2 | 1003초 | 13.97km | 하천변 94m | 94 |
| 75mm | 3 | 1074초 | 15.84km | 없음 | 0 |

네 단계 모두 경로가 다르다. 35mm에서는 지하차도를 피하는 대신 무진대로의 침수 이력 구역을 지나게 되고, 55mm에서는 그것도 피한다.

### 4.4 `demo_points.json` (요구사항 1.7)

다음 7곳을 둔다. 형식은 `{id, name, address, lon, lat, note}`이고 좌표는 대략값이다.

- 광주송정역, 광주역, 광주종합버스터미널(유스퀘어), 광주광역시청, 전남대학교, 국립아시아문화전당
- 상무역(시나리오 D용): 실제 침수 이력 구역 `FLD-SEO-0087`(서구 마륵동) 안이다. 70mm 이상(침수 이력이 '반드시 피함'인 3단계)에서 목적지로 고르면 회피 불가 경고가 나온다. 50~69mm에서는 침수 이력이 '되도록 피함'이라 `partially_avoided`가 나온다. 더미를 지우기 전에는 농성사거리(더미 지하차도 안)였다.

### 4.5 지하차도 (목록 + OSM 터널)

지하차도는 다각형만으로 다룰 수 없다. 터널 선을 12m 넓힌 다각형은 옆 지상 차로와 위를 지나는 교차로까지 덮어서, 시험에서 통과로 판정된 8개 경로 중 7개가 도로 터널을 지나지 않았다. 지하차도는 침수 이력과 달리 '반드시 피함'이라 이 오판정이 곧 멀쩡한 경로의 탈락이다. 그래서 지도 표시, 통과 판정, 엔진 제외를 서로 다른 도형으로 나눈다.

| 용도 | 도형 |
| --- | --- |
| 지도 표시 | 터널 선을 12m 넓힌 다각형(`geometry`) |
| 통과 판정 | 터널 선(`centerline`). 경로가 구간을 따라간 길이로 잰다 |
| 엔진 제외 | 터널 구간마다 지상 도로에서 가장 먼 지점(`block_points`)의 반경 2m 원 |

- **원본**
  - `sources/gwangju_underpasses.csv`: 지하차도 위치 목록(시설물명, 위도, 경도) 23곳. 파일에 출처가 없어 `pipeline.yaml`의 `source_name`을 "출처 확인 중"으로 둔다. 출처를 받으면 고친다.
  - `sources/osm_tunnels.geojson`: `extract_osm_tunnels.py`로 만든 OSM 차도 터널 298구간(ODbL). 수동 실행이며 pbf와 osmium이 필요하다.
- **매칭** (`zones.match_underpasses`): 좌표마다 60m 안의 가장 가까운 터널을 찾는다. 20m 안의 구간은 같은 터널로 묶어 양방향 차로를 함께 가져온다. 22곳이 매칭됐고 21곳은 7m 이내, 운수지하차도는 18.6m다.
- **제외한 곳**: 운암지하차도는 OSM에 터널 태그가 없어 매칭되지 않는다(가장 가까운 터널 668m). 사용자 결정으로 없는 것으로 본다. 그래서 이곳은 피하지 못한다. 효천2지하차도는 OSM에는 있지만 목록에 없어 넣지 않았다.
- **통과 판정** (`scoring.tunnel_length`): 경로에서 1m 안의 터널 구간 길이가 15m 이상이거나 구간 길이의 절반 이상이면 그 구간을 지난 것이다. 경로와 터널 선은 같은 OSM 꼭짓점을 쓰므로 터널에 들어간 경로는 구간 전체가 잡히고, 위를 가로지르는 도로는 약 2m만 겹친다. 임계값 없이 판정할 수 없는 이유가 이것이다.
- **제외 지점**: 터널 가운데는 쓰지 않는다. 지하차도는 도로 아래를 지나므로 가운데는 위쪽 지상 도로와 겹치고, 실제로 매칭된 터널 중 9구간의 가운데가 지상 도로 3m 안이었다. 구간을 20등분한 지점 중 지상 도로에서 가장 먼 곳을 고르며, 매칭된 37구간의 여유는 최소 5.7m다. 엔진은 다각형에 닿는 도로를 모두 빼므로 반경 2m는 터널 구간만 뺀다.
- **버퍼**: `avoid_buffer_m.underpass`는 제외 지점이 있는 구역에 적용되지 않는다.
- **비용**: 제외 지점은 작아서 공통 후보(5.7)의 모든 탐색이 첫 회차부터 지하차도 전부를 뺀다.
- **실제 엔진 확인**: 37구간 모두 양 끝을 잇는 경로가 터널을 지나고, 제외하면 빠졌다. 지하차도를 지나지 않는 시연 경로 40쌍은 제외 지점을 보내도 소요시간이 같았다. 공통 후보 386개 경로에서 통과로 판정했는데 Valhalla `edge.tunnel`에 터널이 없는 경우는 0건이다. 138개 경로는 목록에 없는 터널(주로 2순환로, 빛고을대로)을 지나며 피하지 않는다.

## 5. 경로 알고리즘 (요구사항 4)

### 5.1 인터페이스

```python
class Strategy(Protocol):
    name: str            # @register("이름")으로 지정
    label: str           # 화면 표시 이름
    description: str
    params_model: type[BaseModel]   # 덮어쓸 수 있는 파라미터 (extra="forbid")
    def plan(self, request: RouteRequest, ctx: StrategyContext) -> RoutePlan: ...

@dataclass(frozen=True)
class StrategyContext:
    weather: WeatherContext       # 강수량, 특보, 단계, 출처, 기준 시각
    layer: RiskLayer              # 사용 중 구역, 회피 다각형, 노출 점수 계산
    engine: RoutingEngine
    params: ResolvedParams        # yaml 기본값 + 요청 덮어쓰기
    deadline: float               # 요청 전체 시간 제한 (time.monotonic 기준)
```

- `registry.py`: `@register("이름")` 데코레이터가 클래스를 등록한다.
  - 처음 쓸 때 `pkgutil`로 `app/strategies/` 안의 모든 모듈을 import한다. 그래서 파일 하나만 추가하면 등록된다(요구사항 4.3).
  - 같은 이름을 두 번 등록하면 오류다.
- `RoutePlan`은 `route`, `alternatives`, `baseline`, `explanation`, `metrics`를 가진다. route·alternatives·baseline은 OSRM 경로 객체다(요구사항 4.2).

### 5.2 기본 알고리즘

네 알고리즘 모두 공통 후보(5.7)에서 고른다. 강수 단계와 알고리즘이 달라도 엔진에 묻는 내용은 같다.

| 이름 | 동작 |
| --- | --- |
| `baseline` | 회피 없음. 공통 후보 중 가장 빠른 경로를 고르고, 다음으로 빠른 3개를 alternatives에 담는다 |
| `hard_exclude` | 세 유형 모두 '반드시 피함'. 세 유형을 지나지 않는 가장 빠른 후보를 고른다 |
| `tiered_rain` (화면 기본값) | 단계별 '반드시 피함'·'되도록 피함'(요구사항 4.5 표)으로 5.7 비용 선택을 한다 |
| `rerank` | `소요시간(초) + λ × 위험 노출 점수`가 가장 작은 후보를 고른다. 동점이면 후보 순서가 앞선 것을 고르고, 나머지는 alternatives에 담는다 |

같은 입력이면 같은 결과다(요구사항 4.10). 구역은 `id` 순으로 처리하고 무작위 요소를 쓰지 않는다. 남은 시간이 모자라 탐색이 멈추는 경우는 예외다.

### 5.3 위험 노출 점수 (초안 가중치)

- 점수 = Σ(경로가 구역 원래 다각형 안을 지나는 길이 m × 유형 가중치)
- 가중치: 지하차도 3, 침수 이력 2, 하천변 1
- 회피 버퍼는 점수에 쓰지 않는다. 경로와 구역을 EPSG:5179로 바꿔 교차 길이를 잰다.
- 지하차도는 다각형이 아니라 터널 구간을 따라간 길이를 쓴다(4.5).

### 5.4 회피 실패 (요구사항 4.9, 5.5)

'반드시 피함' 구역을 지나지 않는 후보가 하나도 없을 때 후보 중 '반드시 피함' 구역을 가장 적게 지나는 경로를 route로 돌려준다. 수가 같으면 소요시간 + 되도록 피함 벌점이 작은 쪽이다. explanation에는 `status: "avoid_failed"`, 경고 "위험 구역을 피하는 경로를 찾지 못했습니다", 이유, 경로가 지나는 위험 구역 목록을 담는다. 제외를 단계적으로 풀어 다시 찾는 방식은 쓰지 않는다. 이유는 5.7 탐색이 멈춘 원인으로 정한다. '되도록 피함' 구역만 남으면 실패가 아니라 `partially_avoided`다(5.5).

| 원인 | 판정 방법 | 이유 문구 (초안) |
| --- | --- | --- |
| 출발지·목적지가 회피 다각형(버퍼 포함) 안 | 공통 후보를 모은 뒤 검사(돌려줄 경로가 필요함) | "목적지가 '○○' 구역 안에 있습니다" |
| 제외 후 도착 불가 | Valhalla 오류 코드 442, 170 | "위험 구역을 제외하면 도착할 수 있는 경로가 없습니다" |
| 제외 다각형이 엔진 제한 초과 | 엔진 호출 전 둘레·꼭짓점 검사, Valhalla 오류 코드 167, 176 | "피할 구역이 너무 많거나 커서 경로 엔진이 처리하지 못했습니다" |
| 제외 후 출발·목적지 근처 도로가 없음 | Valhalla 오류 코드 171 (회피 요청에서) | "출발지나 목적지 근처 도로가 모두 피해야 할 구역에 걸립니다" |
| 엔진이 구역을 일부 지나는 경로를 줌 | 회피 경로의 노출 검사 | "경로 엔진이 일부 위험 구역을 피하지 못했습니다" |

baseline 자체를 찾지 못하면 422 "두 지점 사이 자동차 경로를 찾지 못했습니다"다. Valhalla 오류 코드 171 "도로를 찾지 못함"도 여기에 해당한다.

### 5.5 explanation 상태 (요구사항 4.1, 6.4, 6.5)

| status | 조건 | 화면 문구 |
| --- | --- | --- |
| `baseline` | baseline 알고리즘 | "회피 없이 최단 시간으로 찾은 경로입니다" |
| `no_avoid_level` | tiered_rain 0단계 | "현재 강수 단계에서는 피하는 구역이 없습니다" |
| `nothing_on_route` | baseline이 피할 유형의 구역을 지나지 않음 | "이 경로에는 지금 피해야 할 구역이 없습니다" |
| `avoided` | 고른 경로가 피할 유형(반드시+되도록)의 구역을 하나도 지나지 않음 | 피한 구역 목록과 추가 시간 |
| `partially_avoided` | '반드시 피함'은 모두 피했지만 '되도록 피함' 구역 일부를 지남 | "지하차도 구역은 모두 피했고, 침수 이력 구역 2곳(75m)은 지납니다." + 모두 피하는 후보와의 시간 차이("모두 피하면 +5분 40초" / "모두 피하는 경로를 찾지 못했습니다"). 주의 표시(노란 상자) |
| `avoid_failed` | 5.4 | 경고, 이유, 지나는 구역 |
| `ranked` | rerank | "소요시간과 위험 노출 점수의 합이 가장 작은 경로입니다" |

- 피한 구역 = baseline이 지나지만 선택 경로는 지나지 않는 구역
- 지나는 구역 = 선택 경로가 지나는 구역과 그 길이
- explanation에 `hard_groups`, `soft_groups`(단계별 반드시·되도록 피함 그룹, 5.8), `avoid_groups`(두 목록의 합), `clear_option`(모두 피하는 가장 빠른 후보의 `{added_duration_s, added_distance_m}` 또는 `null`)을 더한다. `avoid_types`는 그룹이 하나라도 걸린 유형이다(기존 호환).

### 5.6 파라미터 (요구사항 4.7)

`strategies.yaml`이 기본값이다. 경로 요청의 `params`로 덮어쓸 수 있다. 알고리즘마다 허용 키가 다르며, 허용되지 않은 키나 범위를 벗어난 값은 422다.

| 키 | 허용 알고리즘 | 범위 (초안) |
| --- | --- | --- |
| `avoid_buffer_m.{유형}` | 전체 | 0~200 |
| `weights.{유형}` | 전체 | 0~10 |
| `rain_thresholds_mm` | tiered_rain | 값 3개, 0 초과 300 이하, 증가 순 |
| `alert_min_level.{advisory, warning}` | tiered_rain | 0~3 정수, advisory ≤ warning |
| `entry_penalty_s.{유형}` | tiered_rain | 0~3600 |
| `per_m_penalty_s.{유형}` | tiered_rain | 0~60 |
| `lambda` | rerank | 0~10 |

```yaml
version: 1
zone_types:
  underpass:     {label: 지하차도,  weight: 3, avoid_buffer_m: 30, color: "#dc2626", entry_penalty_s: 600, per_m_penalty_s: 2}
  flood_history:
    {label: 침수 이력, weight: 2, avoid_buffer_m: 20, color: "#f59e0b", entry_penalty_s: 120, per_m_penalty_s: 1,
     tiers: {high: {label: 우선 회피, penalty_scale: 1.5}, normal: {label: 일반, penalty_scale: 1.0}, raised: {label: 주변보다 높은 편, penalty_scale: 0.5}}}
  riverside:     {label: 하천변,    weight: 1, avoid_buffer_m: 50, color: "#2563eb", entry_penalty_s: 60,  per_m_penalty_s: 0.5}
rain_levels:
  thresholds_mm: [30, 50, 70]
  avoid_by_level:          # hard: 반드시 피함, soft: 되도록 피함 (요구사항 4.5)
    0: {hard: [], soft: []}
    1: {hard: [underpass], soft: [flood_history.high]}
    2: {hard: [underpass, flood_history.high], soft: [flood_history.normal, flood_history.raised]}
    3: {hard: [underpass, flood_history, riverside], soft: []}
alert_min_level: {advisory: 1, warning: 2}
default_strategy: tiered_rain
strategies:
  rerank: {lambda: 1.0}
```

- 벌점(초안)은 "이 구역 하나를 피하려고 감수할 우회 시간(초)"이다. 침수 이력 120초 + 1m당 1초면, 75m를 지나는 경로가 모두 피하는 경로보다 270초 넘게 빠를 때 그 경로를 고른다. 벌점은 그 유형이 '되도록 피함'인 단계에서만 쓴다.
- 설정 검사: hard와 soft는 겹치지 않는다, 단계가 오를수록 hard 목록과 hard+soft 목록이 줄지 않는다. 예전 목록 형식(`2: [underpass, flood_history]`)도 읽으며, 이때는 모두 hard다.

설정은 첫 요청에서 읽고 바로 검사한다. 모르는 유형, 증가 순이 아닌 기준값, 음수 가중치가 있으면 원인을 적은 설정 오류(500)를 낸다. 같은 검사를 자동 테스트로도 돌린다.

### 5.7 후보 탐색과 비용 선택 (B안, `strategies/base.py`)

실제 침수 자료(935곳)는 한꺼번에 제외하면 엔진 한도를 넘는다. 그래서 '경로가 지나는 구역만 제외하고 다시 계산'을 반복한다. 반복은 병합된 `route_excluding`에서 시작했다. 예전에는 마지막 회차 결과만 써서, 중간 회차의 더 좋은 경로를 버렸다. 시나리오 A의 55mm에서 3회차 대안 928초, 5회차 대안 1268초(모두 회피)가 나왔는데 8회차의 1298초가 남았다.

**공통 후보 (`common_candidates`)**: 모든 알고리즘과 강수 단계가 같은 후보에서 고른다. Valhalla의 첫 경로는 엔진 비용 기준이라 소요시간이 가장 짧지 않을 수 있고, 단계별로 후보가 다르면 0mm(931초)보다 35mm(833초)가 빠른 역전이 생기기 때문이다.

- 일반 요청(대안 2개) 뒤에, `strategies.yaml`의 단계별 회피 그룹(hard+soft) 조합과 전체 그룹마다 1번의 탐색을 돌린다. 지금 단계가 몇이든 같은 탐색을 전부 돌린다. 실제 구역 구성이 같은 조합은 한 번만 탐색한다(지금은 하천변이 0곳이라 2단계와 3단계가 같다).
- 조합마다 탐색을 두 번 돌린다. 첫 경로가 지나는 구역에서 한 번, 일반 요청 3개 경로가 지나는 구역 전체에서 한 번이다(두 시작점이 같으면 한 번). 어느 쪽도 다른 쪽을 포함하지 않는다. 시나리오 A의 75mm는 앞쪽만 쓰면 1298초, 둘 다 쓰면 1268초이고, E의 0mm는 뒤쪽만 쓰면 232초, 둘 다 쓰면 203초다. 지하차도 제외 지점은 작아서 모든 탐색의 첫 회차부터 전부 넣는다(4.5).
- baseline은 공통 후보 중 소요시간이 가장 짧은 경로다. 동점이면 먼저 찾은 경로를 고른다. 이 경로의 라벨이 "기본 경로"이고, 다른 경로일 때 일반 요청의 첫 경로는 "엔진 첫 경로"가 된다.
- 소요시간은 단계가 오를수록 줄지 않는다. 다음 단계가 고른 경로는 이전 단계에서 벌점이 0이기 때문이다. 벌점이 0 이상인 한 지형 등급 규칙(5.8)이 바뀌어도 성립한다. `added_duration_s`도 0 이상이다.
- 한계: 후보 중 최단이지 전역 최단이 아니다. 후보는 위험 구역 자료에 따라 달라지므로 0단계 경로도 자료가 바뀌면 달라질 수 있다.
- 비용: 0단계도 다른 단계와 같다. 시연 지점 42쌍과 챔피언스필드→광주역의 네 단계에서 요청당 평균 1.26초, 중앙값 0.94초, 최대 4.94초다. 시나리오 A는 1~2초(엔진 호출 19회, 구역 다각형 계산 약 0.5초)다. 같은 PC의 다른 작업에 따라 크게 달라진다. 요청 전체 제한은 10초다.
- 부작용: rerank는 남은 후보를 모두 alternatives에 담으므로(요구사항 4.6) 대안이 크게 늘었다.

1. **후보 모음 (`collect_candidates`)**: 공통 후보의 탐색 1번에 해당한다.
   - 조합에 속한 구역 중 경로가 지나는 구역을 제외 목록에 넣고 다시 계산한다(대안 2개 포함). 새 경로가 지나는 구역을 목록에 더하며 최대 8회 반복한다.
   - 모든 회차의 경로와 대안을 형상 기준으로 중복 없이 모은다.
   - 다음 경우에 멈춘다: 새 구역이 없음, 남은 시간 1초 미만(`MIN_ROUND_TIME_S`), 엔진 한도 초과, 엔진 오류(도착 불가·근처 도로 없음). 탐색이 여러 번이므로 첫 회차에도 남은 시간을 본다. 멈춘 이유는 실패 문구(5.4)에 쓴다. 시간 때문에 멈췄는데 유효한 후보가 없으면 "제한 시간 안에 우회 경로 계산을 끝내지 못했습니다"다.
   - 대안 경로는 회차마다 요청한다. 시나리오 A에서 가장 좋은 경로가 중간 회차의 대안에서 나왔기 때문이다. 로컬 측정에서 8회차 전체가 0.31초에서 0.38초로 늘었다. 남은 시간이 3초(`ALTERNATES_MIN_TIME_S`)보다 적으면 대안 없이 요청한다. 병합된 원격 코드는 "마지막 회차에만 대안 요청"이었는데, B안에 맞춰 이렇게 바꿨다.
   - 출발지·목적지를 덮는 구역은 제외 목록에 넣지 않는다(엔진이 경로를 못 찾게 되므로). '되도록 피함'이면 벌점으로만 다루고, '반드시 피함'이면 `avoid_failed`(5.4)다.
2. **거르기**: '반드시 피함' 구역을 지나는 후보는 버린다. 남은 것이 없으면 `avoid_failed`(5.4)다.
3. **비용**: `소요시간(초) + Σ(되도록 피함 구역마다 entry_penalty_s + per_m_penalty_s × 통과 길이)`. 가장 작은 후보를 고른다. 동점이면 먼저 찾은 후보를 고른다.
4. **결과**
   - 고른 경로가 '되도록 피함' 구역을 지나지 않으면 `avoided`, 지나면 `partially_avoided`다.
   - `clear_option`은 피할 유형을 하나도 지나지 않는 가장 빠른 후보다.
   - alternatives는 남은 유효 후보를 비용 순으로 최대 3개 담는다.

시뮬레이션(실제 Valhalla, 병합된 침수 자료, 광주송정역 → 광주역):

| 강수량 | 지금 | B안 |
| --- | --- | --- |
| 0mm | 931초 | 931초 |
| 35mm | 946초, 지하차도 회피 | 946초 |
| 55mm | 1298초, 22.8km | 928초, 14.4km, 침수 구역 2곳(75m) 지남 → 일부 회피 |
| 75mm | 1298초, 22.8km | 1268초, 20.9km, 모두 회피 |

공통 후보와 지하차도 22곳 적용 결과(실제 Valhalla, 지형 등급 15/50):

| 구간 | 강수량 | 적용 전 | 적용 후 |
| --- | --- | --- | --- |
| A 광주송정역 → 광주역 | 0mm | 931초 | 833초 |
| | 35mm | 833초, 회피 | 833초, 지날 구역 없음 |
| | 55mm | 880초, 일부 회피 | 879초, 일부 회피 |
| | 75mm | 1268초 | 1268초 |
| E 챔피언스필드 → 광주역 | 0mm | 232초 | 203초 |
| | 35mm | 332초 | 332초 |
| | 55mm | 433초, 일부 회피 | 406초, 모두 회피 |
| | 75mm | 회피 실패 | 406초, 모두 회피 |
| 국립아시아문화전당 → 상무역 | 0mm | | 636초, 농성지하차도 통과 |
| | 35mm | | 664초, 농성지하차도 피함 |
| | 55mm | | 837초, 일부 회피 |
| | 75mm | | 회피 실패 |

시연 지점 42쌍과 E 구간에서 0단계 경로가 지하차도를 지나는 쌍은 3쌍이고, 소요시간이 단계와 함께 줄어드는 쌍은 없다. 75mm 회피 실패는 23쌍이다.

시나리오 A의 기본 경로는 지하차도 터널을 지나지 않는다. 0mm와 35mm가 같은 경로라서 `check_demo_scenario.py`가 `SCENARIO_A_SOME_STEPS_EQUAL`을 내고 종료 코드 1로 끝난다. 0mm와 35mm가 같은 경로인 것은 문제로 보지 않고 시연 구간을 유지한다(사용자 결정).

### 5.8 침수 이력 지형 등급 (고도 반영)

침수 이력 구역에 국토지리정보원 DEM(90m 격자) 고도 속성을 붙인 자료(`risk_zones_guide(DEM).md`)를 쓴다. 해발고도(`elev_m`)는 피해를 구분하지 못해(가이드 검증 AUC 0.48) 쓰지 않는다. 침수 횟수(`flood_count`)를 주 기준, 주변보다 낮은 정도(`low_pct`, AUC 0.62)를 보조 기준으로 쓴다. 지하차도·하천변은 등급을 두지 않는다.

**등급**: `data_pipeline/pipeline.yaml`의 `flood_tiers` 기준으로 파이프라인이 계산해 `risk_tier`, `tier_reason`으로 쓴다. 서버는 읽기만 한다.

| 등급 (키) | 조건 | 구역 수 |
| --- | --- | --- |
| 우선 회피 (`high`) | `flood_count` ≥ 2, 또는 `low_pct` < 15, 또는 `elev_status`가 `정상`이 아님(고도 없음 16, 일부 범위 밖 11) | 170 |
| 일반 (`normal`) | 나머지 중 `low_pct` < 50 | 574 |
| 주변보다 높은 편 (`raised`) | 1회 침수이고 `low_pct` ≥ 50 | 163 |

표는 경로 계산에 쓰는 활성 907곳 기준이다. 위치 정확도가 `본번만`인 28곳은 파일에는 보존하되 비활성으로 둔다.

기준값은 처음에 가이드의 20으로 했다가 15(값 있는 구역의 하위 약 10%)로 바꿨다. 20에서는 시나리오 A의 55mm·75mm가 같은 경로였다(아래 표).

- 등급이 없거나 모르는 값인 침수 이력 구역(예전 자료, 손으로 넣은 구역)은 우선 회피로 본다.
- 회피 규칙의 단위는 **그룹**이다. 지하차도·하천변은 유형 이름 그대로(`underpass`, `riverside`), 침수 이력은 등급별(`flood_history.high`, `flood_history.normal`, `flood_history.raised`)이다. `strategies.yaml`에 유형 이름(`flood_history`)을 쓰면 그 유형의 모든 등급이다. 등급 목록은 `config.ZONE_TIERS`에 고정하고, yaml의 `zone_types.flood_history.tiers`가 같은 키를 가져야 한다.

**단계별 규칙** (`strategies.yaml`, 지하차도·하천변은 5.6 그대로):

| 침수 이력 등급 | 1단계 (30mm) | 2단계 (50mm) | 3단계 (70mm) |
| --- | --- | --- | --- |
| 우선 회피 | 되도록 피함 | 반드시 피함 | 반드시 피함 |
| 일반 | 피하지 않음 | 되도록 피함 | 반드시 피함 |
| 주변보다 높은 편 | 피하지 않음 | 되도록 피함 | 반드시 피함 |

- 벌점 = 유형 벌점(5.6) × 등급 배율. 배율(초안)은 우선 회피 1.5, 일반 1.0, 주변보다 높은 편 0.5다.
- 위험 노출 점수(5.3)는 바꾸지 않는다.
- 표현: 등급이 낮아도 "통과 가능", "안전"으로 쓰지 않는다. 팝업에 "고도(90m 격자)는 참고용이며, 침수 기록이 있는 곳입니다"를 붙인다.
- API
  - `GET /api/risk-zones` 속성에 `group`, `risk_tier`, `tier_reason`, `flood_count`, `elev_m`, `low_pct`, `above_local_min_m`, `elev_status`를 더한다(침수 이력만 값이 있다).
  - `GET /api/app-config`에 `zone_groups`(그룹별 `type`, `tier`, `label`)를 더하고, `level_rules`의 `avoid_by_level`·`hard_by_level`·`soft_by_level`은 그룹 키 목록으로 바꾼다.
  - explanation의 `hard_types`·`soft_types`는 `hard_groups`·`soft_groups`로 바꾸고 `avoid_groups`를 더한다. `avoid_types`는 그룹이 하나라도 걸린 유형이다(기존 호환).
- 화면: 지도는 가까이 볼 때 현재 단계에서 피하는 그룹과 이 경로가 지나는 구역을 진하게 그린다(22절). 범례는 유형 일부만 피하면 "일부 회피 대상"이라고 쓴다. 강수 단계 문구와 팝업에 등급을 보여준다.
- 경로 설명(18절): 사실 JSON의 침수 이력 구역에 `회피_등급`을 더한다. 등급이 낮다고 지나도 된다고 쓰지 않도록 규칙을 한 줄 더한다.
- 한계: DEM 격자(90m)가 구역(중앙값 지름 약 60m)보다 거칠다. 기준값 15·50과 배율은 검증된 값이 아니다(가이드 6-7). 시나리오 A의 55mm 경로가 지나는 FLD-BUK-0453은 `low_pct` 19.6이라 기준 20이면 우선 회피, 15면 일반이다.

시뮬레이션(실제 Valhalla, tiered_rain, `.local-data/sim_routes.py`·`sim_threshold.py`). "등급 전"은 더미 구역이 있던 때의 값이고, 등급 열은 더미 구역 제거(`8acd948`) 후의 값이다.

| 구간 | 강수량 | 등급 전 | 등급 20/50 (이전) | 등급 15/50 (현재) |
| --- | --- | --- | --- | --- |
| A 광주송정역 → 광주역 | 0mm | 931초 | 931초 | 931초 |
| | 35mm | 946초, 지하차도만 회피 | 863초, 회피 | 833초, 회피 |
| | 55mm | 928초, 일부 회피(0453·0479) | 1268초, 모두 회피 | 880초, 일부 회피(0453·0479) |
| | 75mm | 1268초 | 1268초 | 1268초 |
| E 챔피언스필드 → 광주역 | 0mm | 232초 | 232초 | 232초 |
| | 35mm | 232초, 지날 구역 없음 | 387초, 우선 회피 구역 피함 | 332초 |
| | 55mm | 433초, 일부 회피 | 433초, 일부 회피(주변보다 높은 편 1곳) | 433초 |
| | 75mm | 회피 실패 | 회피 실패 | 회피 실패 |

20/50에서는 시나리오 A의 55mm와 75mm가 같은 경로였다(`check_demo_scenario.py`가 `SCENARIO_A_SOME_STEPS_EQUAL`을 냈다).

## 6. 경로 엔진 어댑터 (요구사항 5)

### 6.1 인터페이스 (`engines/base.py`)

```python
class RoutingEngine(Protocol):
    name: str
    def route(self, origin: LonLat, destination: LonLat, *,
              exclude_polygons: Sequence[Ring] = (), alternates: int = 0,
              timeout_s: float) -> list[OsrmRoute]: ...
# OsrmRoute = {"geometry": GeoJSON LineString, "distance": m, "duration": s,
#              "weight": ..., "weight_name": ..., "legs": [...]}

class EngineUnavailable(Exception): ...  # 타일 없음, 시간 초과 → 503
class NoRouteFound(Exception): ...       # 442
class ExcludeLimitExceeded(Exception): ...
class LocationNotRoutable(Exception): ...  # 171
```

경로 API는 FastAPI 의존성 `get_engine()`으로 엔진을 받는다. 테스트는 이 의존성을 가짜 어댑터로 바꾼다.

### 6.2 Valhalla (`engines/valhalla.py`)

- **요청 형식**: `costing: "auto"`(요구사항 5.3), `format: "osrm"`, `shape_format: "geojson"`, `directions_type: "none"`, `alternates`, `exclude_polygons`. 각 다각형은 `[[lon, lat], ...]` 닫힌 고리다.
- **안내문을 끄는 이유**: 안내문을 만들면(en-US, ko-KR 모두) 응답에 잘못된 UTF-8이 섞여 `UnicodeDecodeError`가 난다. Windows에서 시험으로 확인했다. 내비 안내는 선택 사항이다.
- **깨진 도로명 복구**: 안내문을 꺼도 OSRM 응답의 `waypoints[].name`(도착 지점 도로명)에 한글 바이트 일부가 `\uFFFFFF80`처럼 깨져 같은 오류가 난다(농성지하차도 지점에서 확인). 이때는 오류 객체의 원본 바이트를 대체 문자로 디코딩해 JSON을 읽는다. 도로명은 버리고 거리·시간·형상만 쓰므로 결과에는 영향이 없다.
- **동시 호출 직렬화와 시간 제한**:
  - pyvalhalla는 `route` 동안 GIL을 풀고, C++ `actor_t`는 내부 작업자를 하나만 가진다. 그래서 동시 호출에 안전하지 않다.
  - Actor 생성과 모든 호출을 작업자 1개짜리 `ThreadPoolExecutor`에서 실행해 직렬화한다.
  - 요청마다 남은 시간(기본 10초, 요구사항 5.4)만큼 `future.result(timeout)`으로 기다린다. 넘으면 `EngineUnavailable`이다.
  - 실행 중인 C++ 계산은 Python에서 중단할 수 없어 끝날 때까지 뒤에서 돈다. 시험에서 1회 계산은 56ms, Actor 생성은 10ms였다.
- **한글 경로**: 프로젝트 경로의 '해커톤' 때문에 Valhalla가 절대 경로 파일을 열지 못한다("Illegal byte sequence"). 다음 순서로 처리한다.
  1. 설정 `VALHALLA_CONFIG`(기본 `.local-data/valhalla/valhalla.json`)를 읽는다.
  2. 타일 경로를 현재 작업 폴더 기준 상대 경로로 바꿔 ASCII면 쓴다. 아니면 절대 경로가 ASCII일 때만 쓴다. 둘 다 아니면 `EngineUnavailable`이다.
  3. 설정은 dict로 넘긴다. pyvalhalla가 ASCII 경로인 임시 파일(`%TEMP%`)로 만든다.
- Valhalla 로그는 끈다(`logging.type = ""`). 위치가 로그에 섞이지 않게 하기 위해서다.
- 오류는 `ValhallaError.code`로 나누고(442, 171, 167~176) 고정 문구로 바꾼다.
- 제외 다각형은 미터 좌표에서 2m 단순화한 뒤 보낸다. 한도는 설정의 `service_limits`(둘레 합 300km, 꼭짓점 5,000개. 기본값 10km, 100개에서 늘림)로 미리 검사한다.
- 설정 경로, 시간 제한(`ROUTING_TIMEOUT_S`)은 환경변수로 바꾼다(요구사항 5.6).

### 6.3 타일 (`data_pipeline/build_valhalla_tiles.ps1`, 실행 완료)

1. Geofabrik `south-korea-latest.osm.pbf`(276.9MB)를 받고 md5로 검증한다.
2. osmium-tool 1.19.1로 광주와 약 5km 여유 범위(`126.58,35.00,127.08,35.31`)로 자른다. 결과는 9.4MB다. osmium은 conda-forge 채널 패키지라 런타임 환경과 섞지 않으려고 별도 conda 환경 `disaster-action-guide-osm`에 설치했다.
3. `valhalla_build_config`로 설정을 만든다(상대 경로, 제외 다각형 한도, `max_alternates 2`).
4. `valhalla_build_tiles`로 빌드한다. 14개 타일, 22.5MB, 7초가 걸렸다.
5. `valhalla_build_extract`로 `tiles.tar`를 만든다.

pyvalhalla 3.9.1 CLI는 Windows에서 실행 파일을 PATH에서 먼저 찾는다. 그래서 스크립트가 그 프로세스에서만 bin 폴더를 PATH에 붙인다. 모든 결과는 Git에서 제외되는 `.local-data/valhalla/`에 있다.

### 6.4 가짜 어댑터 (`engines/fake.py`, 테스트 전용)

`FakeEngine(candidates)`는 미리 준 OSRM 경로 후보 중 제외 다각형과 겹치지 않는 것을 순서대로 돌려준다. 하나도 없으면 `NoRouteFound`다. 호출 기록을 남겨 테스트에서 호출 횟수와 인자를 확인한다. 자동 테스트는 실제 엔진 없이 이 어댑터로 돌아간다(요구사항 5.7).

## 7. API (초안)

좌표와 검색어는 POST 본문으로만 받는다(요구사항 7.3).

| 메서드·경로 | 내용 |
| --- | --- |
| `GET /api/app-config` | `{search_mode, service_area_bbox, zone_types(label·color), zone_groups(type·tier·label), level_rules(thresholds_mm, avoid_by_level·hard_by_level·soft_by_level(그룹 키), alert_min_level), default_strategy}` |
| `GET /api/strategies` | `[{name, label, description, default, params}]` |
| `GET /api/risk-zones` | GeoJSON FeatureCollection + `metadata: {has_dummy, data_checked_at}` |
| `GET /api/demo-points` | 데모 지점 목록 |
| `GET /api/weather` | 3절 기상 컨텍스트 |
| `POST /api/search` | `{query}` → 장소 목록 |
| `POST /api/route` | 경로 계획 |
| `POST /api/route/explain` | 경로 설명 문장(18절) |
| `POST /api/route/guidance` | 회전 안내(12.1절) |
| `POST /api/route/reroute` | 운행 중 판단(19절) |
| `POST /api/route/reroute/explain` | 경로 변경 이유 문장(19절) |
| `POST /api/weather` | 지점의 날씨(20절) |
| `GET /api/weather/regions` | 광주·전남 지역 목록(20절) |
| `POST /api/tts` | 안내 음성(19절) |

### `GET /api/weather`
```json
{"available": true, "source": "kma", "rn1_mm": 12.5, "alert": "none" | "advisory" | "warning",
 "alert_status": "ok" | "failed", "alert_label": "없음", "level": 0,
 "observed_at": "2026-10-30T18:00:00+09:00", "grid": {"nx": 58, "ny": 74},
 "region": "광주광역시", "routable": true, "station": "광주", "message": null}
```
키가 없거나 실패하면 `available: false`, `message: "기상 정보를 가져오지 못했습니다"`다. `station`은 값을 읽은 관측소이며 화면에 표시하지 않는다.

### `POST /api/search` `{query}` (2~50자, 앞뒤 공백 제거)
```json
{"mode": "kakao" | "demo", "notice": null,
 "items": [{"id": "...", "name": "광주역", "address": "광주 북구 ...", "lon": 126.909, "lat": 35.165,
            "selectable": true, "reason": null}]}
```
광주광역시 밖이면 `selectable: false`, `reason: "데모 지역 밖"`이다.

### `POST /api/route`
요청:
```json
{"origin": {"lon": 126.793, "lat": 35.1379},
 "destination": {"lon": 126.909, "lat": 35.1652},
 "strategy": "tiered_rain",
 "weather_override": {"rn1_mm": 55, "alert": "none"},
 "params": {"lambda": 1.0}}
```
- 좌표는 광주광역시 범위 상자(경도 126.63~127.03, 위도 35.04~35.27, `risk/geo.py`의 `SERVICE_BBOX`) 안이어야 한다(초안). 밖이면 422다. 상자라서 경계 근처의 나주·담양 일부도 들어간다.
- 422 응답에는 요청 값(`input`)을 넣지 않는다. `main.py`의 검증 오류 처리기가 위치·이름·유형만 남긴다.
- `weather_override`가 있으면 `source: "demo"`다(요구사항 2.4).
- 없으면 기상청 값을 쓴다. 기상청 값이 없으면 0mm로 계산하고 `real_weather_applied: false`를 붙인다(요구사항 2.5).

응답:
```json
{"strategy": {"name": "tiered_rain", "label": "강수 단계 회피"},
 "route": {"geometry": {"type": "LineString", "coordinates": [[126.79, 35.13]]},
           "distance": 13966, "duration": 1003, "weight": 0, "weight_name": "auto", "legs": []},
 "alternatives": [],
 "baseline": {"...": "OSRM 경로"},
 "explanation": {"status": "avoided", "level": 2, "avoid_types": ["underpass", "flood_history"],
                 "avoided_zones": [{"id": "dummy-underpass-1", "name": "농성지하차도", "type": "underpass"}],
                 "passed_zones": [{"id": "dummy-riverside-1", "name": "...", "type": "riverside", "length_m": 94}],
                 "added_duration_s": 72, "added_distance_m": 315,
                 "warning": null, "failure_reason": null, "message": "..."},
 "metrics": {"route": {"duration_s": 1003, "distance_m": 13966, "exposure_score": 94,
                       "exposure_by_type_m": {"underpass": 0, "flood_history": 0, "riverside": 94}},
             "baseline": {"...": "같은 형태"}, "alternatives": []},
 "weather": {"source": "demo", "rn1_mm": 55, "alert": "none", "level": 2,
             "observed_at": null, "real_weather_applied": false}}
```

| 상황 | 응답 |
| --- | --- |
| 입력 형식 오류, 광주 범위 밖, 등록되지 않은 알고리즘, 잘못된 params | 422 |
| 엔진 불러오기 실패(타일 없음), 시간 초과 | 503 "경로 엔진에 연결할 수 없습니다". 자동 재시도 없음 |
| baseline도 없음 | 422 "두 지점 사이 자동차 경로를 찾지 못했습니다" |
| 회피 실패 | 200, `status: "avoid_failed"` |

## 8. 장소 검색 (요구사항 1)

- 키워드 검색 `GET https://dapi.kakao.com/v2/local/search/keyword.json`을 먼저 쓴다. 파라미터는 `query, rect=126.63,35.04,127.03,35.27, size=10`이다. 결과가 없으면 주소 검색 `/v2/local/search/address.json`(`query, size=10`)을 쓴다. 헤더는 `Authorization: KakaoAK {KAKAO_REST_API_KEY}`다.
- 카카오에는 검색어와 범위만 보낸다. 현재 위치(`x, y`)는 보내지 않는다(요구사항 1.8).
- 광주광역시 판정(초안):
  - 키워드 결과: `address_name`의 첫 마디가 `광주`이고 좌표가 범위 안
  - 주소 결과: `address.region_1depth_name == "광주"`
  - 카카오 표기는 광주광역시 "광주 북구 …", 경기 광주시 "경기 광주시 …"다. 실제 키로 확인한다.
- 키가 없거나 카카오가 오류(401, 403, 429, 5xx), 5초 시간 초과를 내면 `mode: "demo"`로 바꾼다. 이때 이름이 맞는 데모 지점을 앞에 두고 전체 데모 지점을 돌려주며, 안내 문구를 붙인다(요구사항 1.7).
- 검색어는 로그·파일에 남기지 않는다.

## 9. 화면 (요구사항 1·2·3·6·7)

- **배치**: 데스크톱(1024px 이상)은 왼쪽 패널 400px + 오른쪽 지도, 모바일은 위 지도(45vh) + 아래 패널이다.
- **컴포넌트** (`frontend/src/components/`):
  - `SearchBar.tsx`
    - 출발지·목적지 입력과 검색 버튼(Enter 가능). 2글자 미만이면 요청하지 않는다.
    - 결과 목록에서 광주 밖 결과는 비활성으로 "데모 지역 밖"을 표시한다.
    - '현재 위치' 버튼(출발지 전용): 누를 때만 위치 권한을 요청한다. 광주 밖이거나 거부되면 안내 문구를 보여준다.
    - 데모 지점 목록과 출발·목적지 바꾸기 버튼
  - `WeatherPanel.tsx`
    - 기상청 값(강수량, 단계, 특보, 기준 시각, 출처 "기상청")
    - 데모 모드 스위치. 켜면 슬라이더(0~100mm, 5mm 단위)와 특보 선택이 나오고 "데모 값 · 실제 기상 아님" 배지를 붙인다.
  - `RoutePanel.tsx`
    - 경로 찾기 버튼(처리 중 비활성)과 오류 문구. 알고리즘은 화면에서 고르지 않는다.
  - `RouteResultCard.tsx`
    - 요약(거리, 소요, 단계·출처), `RouteExplanation`(18절), 회피 근거(피한 구역, 추가 시간·거리, 노출 점수 baseline → 선택), 경고, 대안 목록, 안내 시작
  - `DriveMode.tsx`(12.1절), `RerouteCard.tsx`(19절)
  - `MapView.tsx`: 선택 경로, baseline 점선(켜고 끄기), 대안, 출발·도착 표시, 경로 범위 맞춤, 지도 출처 표기 유지. maplibre 번들이 커서 `React.lazy`로 따로 불러온다.
    - maplibre 6은 자기 모듈 옆에서 워커 파일을 찾는데, Vite 개발 서버의 의존성 사전 번들링이 모듈 위치를 바꿔 "Worker failed to load"가 난다. `maplibre-gl-worker.mjs?url`로 받은 주소를 `setWorkerUrl()`로 넘긴다.
  - `RiskLayer.tsx`
    - 유형별 색과 범례(지도 왼쪽 위. 아래쪽은 모바일에서 출처 표기와 겹친다). 넓게 볼 때와 가까이 볼 때의 표시는 22절이다. 가까이 보면 피하는 그룹(5.8)과 이 경로가 지나는 구역은 진하게, 나머지는 흐리게 그린다. 결과가 있으면 그 결과의 `avoid_groups`를 쓰고, 없으면 현재 단계로 정한다. 유형의 일부 등급만 피하면 범례에 "일부 회피 대상"이라고 쓴다.
    - 구역 클릭 팝업(이름, 유형, 회피 등급과 이유, 침수 연도 수, 고도, 출처, 확인일, 고도 참고 문구)
  - `lib/api.ts`, `lib/types.ts`, `lib/level.ts`(`app-config`의 규칙으로 화면에서 단계 계산)
- **UI 컴포넌트**: 기존 shadcn/ui(button, card, badge, input, label)와 lucide를 재사용한다. 슬라이더와 스위치는 이미 의존성에 있는 `radix-ui`로 shadcn 형식의 `components/ui/slider.tsx`, `switch.tsx`를 추가한다. 새 npm 패키지는 없다.
- **다시 계산**(요구사항 6.6): 결과가 있을 때 슬라이더를 놓거나(`onValueCommit`) 특보를 바꿔 단계가 결과의 단계와 달라지면 1회 다시 계산한다. 단계가 같으면 다시 계산하지 않는다. 새 결과가 오면 이전 결과를 지운다(요구사항 6.8).
- **안전 고지**(항상 표시, 요구사항 7.1·7.2)
  - "이 서비스는 실제 도로 통제와 침수 여부를 확인하지 않습니다. 지하차도 통제, 재난문자, 경찰·지자체 안내를 먼저 따르세요."
  - "실시간 교통을 반영하지 않습니다. 위험 구역 데이터 기준일 ○○"
- 템플릿 대시보드(App.tsx)는 대체한다. 기록 CRUD 화면은 사라지지만 백엔드 API는 남는다.
- 좌표·검색어를 URL, localStorage에 넣지 않는다.

## 10. 위치 정보와 로그 (요구사항 7)

- 좌표·검색어·경로는 요청 처리 중 메모리에만 있다. DB·파일·로그에 쓰지 않는다.
- uvicorn 접근 로그에는 메서드와 경로만 찍힌다. 본문은 찍히지 않는다.
- 예외 처리기와 오류 문구에 요청 본문, 카카오·기상청 원문 오류, 키를 넣지 않는다.
- Record DB는 건드리지 않는다. AI 호출량 DB는 경로 설명이 실제 Bedrock을 부를 때만 1회 센다(캐시 적중·모의 모드는 세지 않음).
- 밖으로 나가는 정보는 카카오에 검색어·범위, 기상청에 5km 격자 번호·특보 조회 조건, Bedrock에 경로 설명과 변경 이유용 사실(좌표 없음, 18·19절)뿐이다. 브라우저는 OpenFreeMap에 지도 타일을 요청한다(요구사항 7.5).

## 11. 환경변수

| 이름 | 용도 | 없을 때 |
| --- | --- | --- |
| `KAKAO_REST_API_KEY` | 장소 검색 | 데모 지점 |
| `KMA_SERVICE_KEY` | 초단기실황·특보 | 데모 모드 |
| `KMA_AWS_KEY` | AWS 분 단위 강수(23절) | 초단기실황 |
| `VALHALLA_CONFIG` | Valhalla 설정 경로 | `.local-data/valhalla/valhalla.json` |
| `ROUTING_TIMEOUT_S` | 경로 요청 시간 제한 | 10 |
| `KIROTHON_AI_MODE` | `mock` / `bedrock` | `bedrock` (로컬 스크립트는 `mock`) |
| `KIROTHON_BEDROCK_REGION` | Bedrock 호출 리전 | `ap-northeast-1` |
| `KIROTHON_EXPLAIN_MODEL` | 경로 설명 모델(ai_service.py 허용 목록 안) | Claude Haiku 4.5 |
| `KIROTHON_EXPLAIN_TIMEOUT_S` | 경로 설명 응답 대기(1~30초) | 8 |
| `KIROTHON_BEDROCK_GUARDRAIL_ID`, `_VERSION` | Bedrock Guardrails | 없음: 서버 자체 검사만 |
| `KIROTHON_TTS_URL`, `_VOICE`, `_SPEED`, `_TIMEOUT_S` | 서버 음성(Supertonic) | 브라우저 음성 |
| `KIROTHON_ENV_FILE` | 읽을 .env 경로. 빈 값이면 읽지 않음(테스트) | `backend/.env` |

- 키와 설정을 넣는 곳은 세 곳이고, 위에 있는 것이 우선한다.
  1. 프로세스 환경: PowerShell `$env:`, systemd
  2. 프로젝트 루트의 `.env`: `.env.example` 참고. `scripts/dev-backend-conda.ps1`이 uvicorn `--env-file`로 넘긴다.
  3. `backend/.env`: `backend/.env.example` 참고. `app/__init__.py`가 앱을 불러올 때 python-dotenv(잠금 파일에 이미 있음)로 읽는다. 서버에서는 이 파일을 쓴다.
- 이미 프로세스 환경에 있는 값은 .env로 바뀌지 않는다. 그래서 로컬 스크립트의 `KIROTHON_AI_MODE=mock`은 그대로 유지된다.
- 두 `.env`는 Git(.gitignore)과 배포물(scripts/deploy.ps1, ops/deploy.py)에서 빠진다. 서버에서는 `/home/ubuntu/kirothon/backend/.env`에 한 번 만들고 권한을 600으로 둔다. 배포는 이 파일을 건드리지 않는다.
- AWS 액세스 키는 어느 .env에도 넣지 않는다. 서버는 EC2 IAM 역할을 쓴다. 키를 저장소·배포물·프론트에 넣지 않는다.

`KMA_SERVICE_KEY`는 공공데이터포털 키와 기상청 API허브 키를 모두 받는다. API허브 키(22자)면 `apihub.kma.go.kr`의 `authKey`로, 그 외에는 `apis.data.go.kr`의 `serviceKey`로 호출한다. 특보는 API허브에서 `wrn_now_data.php`(발효 중인 특보 목록)를 쓴다. 등급은 `주의`·`경보`만 인정하고 `예비`는 뺀다. 광주는 `REG_ID`나 `REG_UP`의 광주 코드로 찾고, 경기 광주시(`L1013400`)는 제외한다. 실황은 매시 정각 자료를 먼저 요청하고, 아직 없으면 이전 시각 자료를 쓴다.

## 12. 로컬 실행

- 백엔드: `scripts/dev-backend-conda.ps1`
  - conda 환경 `disaster-action-guide`의 python을 찾는다.
  - `backend` 폴더에서 `KIROTHON_AI_MODE=mock`, `KIROTHON_DB_PATH=<프로젝트>/.local-data/records.sqlite3`로 `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`을 실행한다.
  - 끝나면 환경변수를 원래대로 돌린다.
- 프론트: 기존 `scripts/dev-frontend.ps1`
- 새 Python 패키지는 `backend/requirements.team.txt`에 적었다. 두 잠금 파일은 바꾸지 않는다.

### 12.1 운행 화면 (시연 주행, 요구사항 10)

- `안내 시작`을 누르면 선택된 경로로 `POST /api/route/guidance`를 호출해 회전 안내를 받고 전체 화면 운행 모드로 들어간다. 좌표는 본문으로만 보내고 저장하거나 로그에 남기지 않는다.
- 회전 안내는 Valhalla `trace_route`에 `format: json`, `directions_type: maneuvers`로 받는다. Windows에서 OSRM 형식은 도로명 인코딩 오류가 나기 때문이다. `POST /api/route`는 그대로 `directions_type: none`을 쓴다.
- 안내를 받지 못해도 경로선만으로 주행을 계속한다.
- 차량 위치는 **실제 GPS가 아니라 시연 주행**이다. 경로를 따라 구간별 예상 속도로 움직이고 화면에 시연임을 표시한다. 없는 것: 실제 위치 추적, 경로 이탈 재탐색, 차선·카메라 안내, 회전 음성 안내.

## 13. 오류 처리 요약

| 상황 | 백엔드 | 화면 |
| --- | --- | --- |
| 타일 없음·엔진 시간 초과 | 503 | "경로 엔진에 연결할 수 없습니다" |
| 회피 실패 | 200 `avoid_failed` + 가장 적게 지나는 경로 | 경고, 이유, 지나는 구역 |
| 카카오 키 없음·실패 | `mode: demo` | 안내 문구 + 데모 지점 |
| 기상청 키 없음·실패 | `available: false` | "기상 정보를 가져오지 못했습니다" + 데모 모드 |
| 특보만 실패 | `alert_status: failed` | "특보 확인 실패" |
| 위치 권한 거부·광주 밖 | (서버 호출 없음) | 안내 문구, 검색으로 지정 |
| 입력 오류 | 422 | 입력 옆 문구 |

## 14. 테스트

백엔드는 pytest(기존 23개 포함), 프론트는 `npm run build`, `npm run lint`를 돌린다. 모든 백엔드 테스트는 실제 엔진·카카오·기상청 없이 돈다.

| 요구사항 | 테스트 파일 | 내용 |
| --- | --- | --- |
| 3.8 | `test_risk_data.py` | ID 중복 없음, 유효한 다각형, 광주 범위 안, 허용된 유형, 출처·확인일 존재 |
| 4.11 | `test_strategies.py` | 가짜 어댑터로 4개 알고리즘이 같은 형식, 경계값 29/30·49/50·69/70mm, 특보 반영, 잘못된 params·등록 안 된 알고리즘 422, 회피 불가 시 경고 + 가장 적게 지나는 경로 |
| 5.7 | 전체 + `test_route_api.py` | 엔진 의존성을 가짜 어댑터로 바꿈. 테스트 중 Valhalla Actor를 만들지 않음을 확인 |
| 3.2 | `test_data_pipeline.py` | 점·선 버퍼, 같은 입력이면 같은 출력, 검증 실패 시 쓰지 않음 |
| 4.3 | `test_strategies.py` | 임시 모듈에 `@register`를 붙이면 목록·경로 API에 나옴 |
| 4.6, 4.10, 5.3 | `test_risk_scoring.py`, `test_strategies.py` | 노출 점수 계산, rerank 최소 점수 선택, 같은 입력이면 같은 결과 |
| 5.4~5.6 | `test_valhalla_engine.py` | 요청 본문, ASCII 경로 처리, 직렬화, 시간 초과 503, 오류 코드 매핑 (가짜 Actor) |
| 2.1~2.7 | `test_weather.py` | 실황·특보 파싱(httpx.MockTransport), 경기 광주 코드 제외, 10분 캐시, 키 없음·실패, 오류에 키 없음 |
| 1.1~1.8 | `test_search.py` | 광주 밖 `selectable: false`, 2글자 미만 422, 키 없음·오류 → demo, 현재 위치 미전송 |
| 7.3, 7.4 | `test_route_api.py` | 로그(caplog)에 좌표·검색어 없음, Record 수 변화 없음, `.local-data`에 새 파일 없음 |
| 2.1(AWS) | `test_weather_aws.py` | 관측소 표 읽기, 가까운 관측소 선택, 결측 건너뛰기, 대체 |
| 2.8~2.10 | `test_weather_location.py` | 지역 찾기, 특보 코드, 격자, 조회 제한 |
| 8 | `test_route_explain.py` | 사실 구성, 금지 표현, 사실에 없는 숫자, 템플릿 대체, 캐시 |
| 9 | `test_reroute.py`, `test_tts.py` | 판단 세 가지, 변경 이유, 음성 합성 |
| 10 | `test_guidance.py` | 회전 안내 |

- 실제 엔진 확인: `data_pipeline/check_demo_scenario.py`로 시나리오 A 네 단계를 확인한다(수동, pytest 아님).
- 브라우저 확인: 백엔드·프론트를 띄우고 설치된 Chrome을 원격 디버깅 모드로 연다. Node 22 내장 WebSocket으로 조작하고 화면을 캡처한다. 새 라이브러리는 쓰지 않는다.

## 15. 시연 시나리오 확인 방법

- **A**: 데모 모드, 광주송정역 → 광주역, tiered_rain, 0 → 35 → 55 → 75mm. 단계마다 1회 다시 계산되고 5.7절 표처럼 바뀌는지 본다(55mm는 일부 회피).
- **B**: 카카오 키가 없으므로 대체 흐름으로 확인한다. 안내 문구 → 데모 지점에서 광주역 선택 → 경로 표시. 키가 있을 때의 흐름은 MockTransport 테스트로 확인한다.
- **C**: 기상청 키가 없으므로 대체 흐름으로 확인한다. "기상 정보를 가져오지 못했습니다" → 데모 모드로 전환 → 결과에 "실제 강수 미반영"
- **D**: 70mm 이상에서 목적지를 '상무역(시나리오 D 시연용)'으로 정한다. 경고, 이유, 지나는 구역과 함께 가장 적게 지나는 경로가 나오는지 본다.
- **알고리즘 교체**: API의 strategy를 hard_exclude, rerank로 바꿔 같은 형식이 오는지 본다. 화면에는 고르는 곳이 없다.
- **운행 중 변경**: 안내를 시작하고 출발 직후 시연 강수 75를 누른다. 기다려도 바뀌지 않는지, 변경, 유지, 강수 완화를 각각 본다.
- **네트워크 기록**: 요청 URL에 좌표·검색어가 없고, 키가 응답에 없는지 본다.

## 16. 서버 배포 제약 (이번 범위 아님)

현재 `ops/deploy.py` 기준으로는 이대로 배포되지 않는다. 멘토 검토 대상이다.

- `frontend/package-lock.json`이 바뀌면(maplibre-gl 추가) 배포를 거부한다.
- 서버 가상환경에는 pyvalhalla, shapely, pyproj와 타일이 없다.
- `backend/app` 아래에서는 `.py`와 목록에 적힌 세 파일(`strategies.yaml`, `demo_points.json`, `risk_zones.geojson`)만 올린다.

## 17. 요구사항을 해석한 점

1. 회피 실패 시 제외를 단계적으로 풀지 않고, 후보 중 '반드시 피함' 구역을 가장 적게 지나는 경로와 경고를 돌려준다(요구사항 4.9).
2. 엔진 시간 제한 10초는 경로 요청 전체에 적용한다. 실행 중인 Valhalla 계산은 중단하지 못하고, 응답만 503으로 먼저 보낸다.
3. 실제 엔진으로 시나리오 A를 확인하는 일은 pytest가 아니라 수동 스크립트로 한다(요구사항 5.7).
4. 특보 현재 상태는 특보코드조회의 마지막 명령으로 판정한다(3.3절). 광주서부·광주동부 중 하나라도 발효면 광주 발효로 본다. 기상청 조회는 출발지와 차 위치 기준이다(20절).
5. 중대경보는 경보와 같게 반영한다.
6. 침수 이력 지형 등급(5.8)을 요구사항 4.5 표와 시연 확인 기준에 반영했다.
7. 요구사항의 'baseline: 최단 시간'과 '0단계: baseline과 같은 경로'는 공통 후보 중 가장 빠른 경로로 해석한다(5.7). 전역 최단은 보장하지 않는다.
8. 요구사항 3.1의 지하차도 다각형은 지도 표시용으로 유지하고, 통과 판정과 엔진 제외는 터널 선과 제외 지점을 쓴다(4.5).

## 18. AI 회피 경로 설명 (요구사항 8)

- 흐름: 화면이 `POST /api/route` 결과를 먼저 그린 뒤 `POST /api/route/explain`을 따로 부른다(`frontend/src/components/RouteExplanation.tsx`). 설명은 경로 결과 카드 안, 결과 문구와 경고 바로 아래에 붙는다. 설명 요청이 실패하면 설명 칸만 숨긴다.
- 요청 본문: `{status, level, alert, route: {duration_s, zones: [{id, length_m}]}, baseline: {...}, fallback_engine}`. 좌표는 없다. `explanation.baseline_passed_zones`(baseline이 지나는 구역)를 추가해 일반 경로 쪽 구간을 채운다.
- `app/route_explainer.py`:
  - `build_facts()`: 구역 ID를 서버 위험 구역 데이터로 풀어 이름·유형·근거를 붙인다. 모르는 ID는 422다. 목록은 길이 순 5개까지, 수는 전체를 센다. 소요시간은 분으로 반올림하고 추가 소요시간은 두 값의 차다.
  - 근거: 실제 침수 이력 구역은 이름의 연도로 "2023·2025년 침수피해 기록", 나머지는 원본 자료 이름.
  - 고정 문구 상태(baseline, no_avoid_level, nothing_on_route)와 baseline과 같은 rerank 결과는 LLM을 부르지 않는다.
  - Bedrock Converse: system에 규칙, user에 사실 JSON과 질문. `maxTokens 300`, `temperature 0.2`, 연결 3초, 응답 `KIROTHON_EXPLAIN_TIMEOUT_S`, 재시도 없음.
  - 가드레일 ID가 있으면 `guardrailConfig`를 넣고, 사실 JSON은 `grounding_source`, 질문은 `query` 한정자를 붙인 `guardContent`로 보낸다(근거 확인). 단어 필터는 Bedrock 콘솔의 가드레일에서 설정한다. `stopReason: guardrail_intervened`면 템플릿이다.
  - 서버 검사(`check_output`): 400자 또는 4문장 초과, '안전'·'보장'·'침수되지 않'·'위험이 없'·'지금 침수'·운전/출발 권유·다른 경로 이용 권유·링크, 사실 JSON에 없는 숫자가 있으면 템플릿이다.
  - 템플릿 대체 사유: `not_needed`, `mock`, `config`, `quota`, `timeout`, `throttled`, `error`, `guardrail`, `filtered`, `number_mismatch`, `too_long`, `empty`. 로그에는 사유만 남기고 사실은 남기지 않는다.
  - 캐시: 프로세스 메모리 256개, 6시간. 키는 모델·가드레일·사실 JSON의 SHA-256이다. 같은 출발·도착과 같은 위험 구간 조합이면 사실이 같으므로 좌표 없이 재사용된다. AI 성공 문장만 캐시한다.
  - 호출량: 실제 Bedrock 호출 전에만 공통 한도(분당 20회, 하루 600회)를 센다.
- 응답: `{text, source: "ai" | "template", reason, cached}`. 화면은 `source`에 따라 "AI 설명" / "경로 설명"을 표시한다.
- 대체 계산: OpenRouteService 같은 대체 엔진은 아직 없다. `fallback_engine`은 항상 false이고, 나중에 대체 엔진을 붙이면 이 값을 채운다.
- 테스트: `backend/tests/test_route_explain.py`. boto3를 가짜로 바꿔 실제 AWS 없이 돈다.

## 19. 운행 중 경로 변경 요청 (요구사항 9)

- 흐름: 강수 단계 상승 → `POST /api/route/reroute` → (`recommend`이면) 회전 안내 받기, 카드 표시 → `POST /api/route/reroute/explain` → 운전자 선택.
- 판단: `backend/app/reroute.py`. 경로를 그린 알고리즘과 관계없이 `tiered_rain`으로 후보를 찾는다. `baseline`과 `rerank`는 피할 구역 목록이 없어 그대로 쓰면 "피할 구간 없음"으로 잘못 읽히기 때문이다. `decide()`는 그 경로와 남은 경로를 새 단계의 hard/soft 그룹으로 비교한다. soft만 줄어드는 경우는 알고리즘과 같은 기준(소요시간 + soft 벌점)으로 고른다.
- 회피 실패: 메인 화면과 같다. `avoid_plan`이 공통 후보(5.7)에서 hard 구간이 가장 적은 경로를 고르고, 같으면 소요시간 + soft 벌점이 작은 쪽을 고른다. 도로망으로 직접 확인하면 75mm 무작위 구간 150개 중 137개는 전부 피하는 길을 찾았고, 13개가 실패했다(길이 없음 8, 출발·도착이 구역 안 4, 탐색이 놓침 1).
- 출발 방향: `RouteRequest.origin_heading` → 엔진 `heading` → Valhalla 출발 지점의 `heading`. 달리는 방향을 무시하고 경로가 시작되는 것을 줄인다.
- 남은 시간: 화면의 남은 시간과 같은 값(전체 소요시간 × 남은 거리 비율)을 클라이언트가 보낸다. 구간 수는 서버가 남은 경로 좌표로 직접 계산한다. 좌표는 저장하거나 기록하지 않는다.
- 설명: `route_explainer.reroute_facts`, `reroute_template`, `explain_reroute`. 요구사항 8과 같은 호출·검사·캐시 경로(`_write`)를 쓰고, 프롬프트만 따로 둔다. 추가 소요시간은 반올림한 분끼리 빼지 않고 초 차이에서 구해 화면의 값과 어긋나지 않게 한다.
- 화면: `DriveMode`는 경로를 `Nav` 묶음 하나로 들고 `navRef`로 지도 루프에 넘긴다. 경로가 바뀌어도 지도를 다시 만들지 않고 선 데이터만 바꾼다. 지나온 길은 `travelledRef`로 이어 그린다. 요청 중에는 카메라를 위에서 본 전체 화면으로 옮기고 현재 경로는 호박색, 변경 경로는 청록색으로 그린다.
- 음성: `frontend/src/lib/speech.ts`. `POST /api/tts`(서버의 Supertonic, 새 패키지 없이 httpx로 호출)를 먼저 쓰고, 실패하면 `speechSynthesis`로 읽는다. 변경 요청은 `spokenRerouteSummary`의 짧은 문장만 읽고 AI 문장은 카드에만 둔다. 재탐색 알림과 요약만 읽으며 회전 안내는 읽지 않는다.
- 테스트: `backend/tests/test_reroute.py`. 실제 엔진 확인은 광주송정역 → 광주역의 13개 지점 × 35·55·75mm(39건, 공통 후보와 지하차도 22곳 적용 후): `recommend` 20, `no_better` 6, `keep` 13. 기본 경로가 35mm 회피 경로와 같아져 35mm는 모두 `keep`이고, 75mm는 전체 경로의 32%·40% 지점에서만 `no_better`다.

## 20. 날씨 기준 위치 (요구사항 2.8~2.10)

- 지역 목록: `backend/app/context/weather_regions.py`. 광주 6곳(시 전체와 5개 구), 전남 22개 시군, 섬 특보구역 2곳(흑산도·홍도, 거문도·초도)이다. 좌표는 시청·군청 기준의 대표값이다.
- 특보구역 코드: 공공데이터포털 '기상청_기상특보구역정보_20260601'(15043573)로 확인했다. API허브의 구역 목록 API(`wrn_reg.php`)는 지금 키로 403이다. 2026년 6월 개편으로 나주·곡성·구례·고흥·해남·완도·무안·영광이 세분되었고, 상위 코드와 세분 코드를 모두 그 시군에 넣는다. 전남 전체 코드 `L1050000`은 넣지 않는다.
- 격자: `grid_of()`가 기상청 LCC 식으로 계산한다. 시험에서 서울 종로 (60, 127), 광주시청 (58, 74)을 확인한다.
- 지역 찾기: `region_for()`는 가장 가까운 대표 지점을 고른다. 경계 도형이 없어 경계 근처는 이웃 시군의 특보를 볼 수 있다. 범위 검사(`WEATHER_BBOX`)도 사각형이라 전북·경남의 인접 지역도 통과한다.
- API: `POST /api/weather {lon, lat}`, `GET /api/weather/regions`. `GET /api/weather`는 광주광역시 기본값이다. 범위 밖은 422다. 좌표는 본문으로만 받고 저장·기록하지 않는다.
- 캐시: 강수는 (격자, 지역)별 10분이다. 최대 4096개로, 날씨 범위의 격자 수보다 많아 지점을 훑어도 쓰던 값이 밀려나지 않는다. 특보 목록은 한 번 받아 지역마다 거른다.
- 동시 요청: 기상청을 부르는 동안 전체 잠금을 잡지 않는다. 같은 지점만 한 번 읽도록 지점별로 기다리고, 다른 지점은 기다리지 않는다.
- 조회 제한: 클라이언트가 지점을 정할 수 있어 새 지점 조회를 프로세스당 분당 60회, 하루 5,000회로 제한한다. 넘으면 마지막 값, 없으면 '요청이 많다'는 실패를 돌려준다. 기본 지역은 제외한다. IP별 제한은 아니어서, 한 사용자가 한도를 다 쓰면 다른 사용자의 새 지점 조회도 막힌다.
- 경로: `POST /api/route`는 출발지, `POST /api/route/reroute`는 차 위치의 날씨를 쓴다. 응답의 `weather.region`이 기준 지역이다.
- 화면: 패널의 지역 선택(`.location-select`). 권한 상태는 Permissions API로만 읽고, 허용된 경우에만 위치를 묻는다. 위치 추적(`watchPosition`)은 쓰지 않는다.
- 위치 얻기: `frontend/src/lib/location.ts`. 날씨 패널과 출발지 버튼이 함께 쓴다. `enableHighAccuracy`(15초)를 먼저 요청하고, 권한 거부가 아닌 실패는 일반 위치(8초)로 다시 시도한다. 오차가 날씨 5km, 출발지 500m를 넘으면 안내 문구를 보여준다. GPS를 실제로 쓸지는 기기가 정하며, GPS가 없는 PC는 Wi-Fi·IP 위치가 된다.
- 패널이 전남이면 `routable: false`다. 경로 규칙과 광주 지도 강조에 쓰지 않는다.
- 테스트: `backend/tests/test_weather_location.py`.

## 21. 경로 문구의 기준 (요구사항 8)

한 문장 안에서 서로 다른 기준의 수를 섞지 않는다.

- 수의 기준: 이번 단계의 '반드시'·'되도록' 구간과, 그 밖의 위험 구간을 나눠서 말한다. 결과 카드도 두 줄로 나눈다.
- 피한 구역: 메시지는 기본 경로가 실제로 지나는 그룹만 말한다. 규칙에 있어도 만나지 않은 구역을 "피했다"고 하지 않는다.
- 등급 교환: 수가 같아도 벌점이 더 낮은 등급으로 바꾸려고 돌아갈 수 있다. 광주송정역 → 광주역 55mm는 일반 2곳(833초, 벌점 304)보다 일반 1곳·높은 편 1곳(880초, 벌점 238)이 총비용이 낮다. 이때 "수는 같지만 회피 우선순위가 더 낮은 구간으로 지나요"라고 쓴다. 등급 순서는 `ZONE_GROUPS`다.
- 위험 노출 점수는 길이 × 유형 가중치라 등급을 모른다. 위 경우 129 → 150으로 오르므로 화면에 그 이유를 표시한다. 선택 로직은 바꾸지 않았다.

## 22. 지도 표시

- 낮 지도는 OpenFreeMap `positron`, 밤 지도는 `fiord`다. `applyKoreanLabels`가 지명을 `name:ko` → `name:nonlatin` → `name` 순으로 바꾼다. 도로 번호는 그대로 둔다.
- 침수 이력: 12.5배율 아래에서는 개별 구역을 숨기고 히트맵으로 그린다. 히트맵은 기록이 많은 곳을 보여줄 뿐이고 기록은 구별로 쏠려 있으므로, 범례에 위험도가 아니라고 적는다. 빨강이 아닌 호박색만 쓴다.
- 점: 지하차도와 이 경로가 지나거나 피한 구역만 표시한다. 일반 지하차도 점은 경로선 아래에 그린다. 위쪽 도로로 지나가는 곳이 터널을 지나는 것처럼 보이면 안 되기 때문이다. 12.5배율 아래의 숨은 구역은 눌러도 팝업이 뜨지 않는다.

## 23. 분 단위 강수량 (AWS 관측소)

- 왜: 초단기실황은 정시 값이라, 갑자기 강해진 비를 최대 1시간 늦게 안다. 핵심 시나리오의 약점이다.
- 자료: API허브 `nph-aws2_min`의 `RN-60m`(최근 60분 누적, mm). 실측으로 1분마다 바뀌고 약 3분 늦다. 강수 단계 기준이 시간당 값이라 그대로 쓴다.
- 시각을 지정하지 않고 부른다. 현재 시각을 지정하면 아직 도착하지 않은 값이라 전 지점이 결측이다.
- 관측소 선택(`weather_aws.nearest_rain`): 20km 안에서 가장 가까운, 값이 있는 곳. 결측(-50 이하)은 비 없음으로 읽지 않고 건너뛴다. 해발 300m 이상(무등산)과 30분 넘은 값은 쓰지 않는다.
- 호출: 표 하나가 전 지점을 담으므로 지점 수와 무관하게 2분에 한 번(하루 약 720건, 일반회원 한도 20,000건). 지점정보는 하루 한 번.
- 대체: `KMA_AWS_KEY`가 없거나, 응답이 실패·형식 오류이거나, 근처에 쓸 관측소가 없으면 초단기실황을 쓴다. 실패는 1분 동안 다시 시도하지 않는다.
- 키: 지금은 AWS(`KMA_AWS_KEY`)와 초단기실황·특보(`KMA_SERVICE_KEY`)가 서로 다른 키다. 한 키에 모두 신청되면 두 항목에 같은 값을 넣으면 된다.
- 표기: 화면은 관측 시각만 보여주고 관측소 이름은 표시하지 않는다. 관측소 값이므로 이 지점의 값은 아니다.

# 호우 안전 경로 · 광주

비가 많이 올수록 지하차도, 침수 이력 도로, 하천변을 단계적으로 피해 가는 자동차 경로를 찾아 주는 광주 지역 웹 앱입니다. 어떤 구역을 왜 피했는지, 그만큼 시간이 얼마나 더 걸리는지 지도에 함께 보여줍니다.

> 전남대학교 Kirothon TOPIC 10 (의료·복지·안전) 프로젝트입니다.
>
> **이 서비스는 실제 도로 통제와 침수 여부를 확인하지 않습니다.** 지하차도 통제, 재난문자, 경찰·지자체 안내를 먼저 따르세요.

## 해결하려는 문제

집중호우 때 지하차도와 저지대 도로는 짧은 시간에 물에 잠깁니다. 일반 내비는 교통 흐름으로 경로를 고르고 침수 위험은 반영하지 않습니다. 운전자가 비가 얼마나 와야 어느 길이 위험한지 스스로 판단하기도 어렵습니다.

## 주요 기능

- **강수 단계별 회피 경로:** 시간당 강수량과 호우 특보에 따라 피할 구역을 늘립니다.
- **회피 근거 표시:** 피한 구역, 아직 지나는 구역, 가장 빠른 길 대비 늘어난 시간과 거리를 보여줍니다.
- **기상청 연동:** 초단기실황(1시간 강수량)과 호우 특보를 반영합니다.
- **장소 검색:** 카카오 로컬 API로 광주 안의 장소를 찾습니다.
- **운행 화면:** 3D 지도, 회전 안내, 도착 예정 시각, 위험 구역 경고를 보여줍니다. 지금은 **시연 주행**이며 실제 GPS를 쓰지 않습니다.
- **날씨 배경:** 강수량과 시간대에 따라 하늘, 구름, 비, 번개가 바뀝니다. 경로 계산과는 무관한 장식입니다.

키가 없어도 시연할 수 있습니다. 기상청 키가 없으면 강수량을 직접 고르고, 카카오 키가 없으면 데모 지점 목록을 씁니다.

### 강수 단계

| 시간당 강수량 | 단계 | 피하는 구역 |
| --- | --- | --- |
| 30mm 미만 | 0 | 없음 |
| 30mm 이상 | 1 | 지하차도 |
| 50mm 이상 | 2 | 지하차도, 침수 이력 |
| 70mm 이상 | 3 | 지하차도, 침수 이력, 하천변 |

호우주의보는 최소 1단계, 호우경보는 최소 2단계로 올립니다. 기준값은 [strategies.yaml](backend/app/config/strategies.yaml)에서 바꿉니다.

### 경로 알고리즘

| 이름 | 방식 |
| --- | --- |
| `tiered_rain` | 강수 단계에 따라 피할 유형을 늘립니다. 기본값입니다. |
| `hard_exclude` | 강수량과 관계없이 모든 위험 구역을 피합니다. |
| `rerank` | 후보 경로 중 소요시간과 위험 노출 점수의 합이 가장 작은 경로를 고릅니다. |
| `baseline` | 회피 없이 가장 빠른 길입니다. 비교 기준입니다. |

새 알고리즘은 [strategies/](backend/app/strategies/)에 파일을 추가하고 `@register`를 붙이면 API와 화면에 나타납니다.

## 구조

```
브라우저 (React + MapLibre)
   │  /api/ (좌표와 검색어는 POST 본문으로만 전송)
   ▼
FastAPI
   ├─ 경로 알고리즘 ─ Valhalla (서버 프로세스 안에서 실행, OSM 광주 타일)
   ├─ 위험 구역 레이어 (risk_zones.geojson)
   ├─ 기상청 API허브 또는 공공데이터포털
   └─ 카카오 로컬 API
```

좌표, 검색어, 경로는 DB나 로그에 저장하지 않습니다. 카카오에는 검색어와 검색 범위만, 기상청에는 광주 기준 격자만 보냅니다. 지도 타일은 브라우저가 OpenFreeMap에서 받습니다.

| 경로 | 설명 |
| --- | --- |
| `POST /api/route` | 경로 계산과 회피 근거 |
| `POST /api/route/guidance` | 선택한 경로의 회전 안내 |
| `POST /api/search` | 장소 검색 |
| `GET /api/weather` | 현재 강수량과 특보 |
| `GET /api/risk-zones` | 위험 구역 지도 레이어 |
| `GET /api/strategies` | 알고리즘 목록 |
| `GET /api/app-config` | 화면 설정 |
| `GET /api/demo-points` | 데모 지점 |

## 로컬 실행

Windows 기준입니다. Python 3.12(conda), Node.js 24가 필요합니다. 명령은 프로젝트 루트에서 실행합니다.

### 1. 설치

```powershell
# 백엔드
conda create -n disaster-action-guide python=3.12 -y
conda run -n disaster-action-guide python -m pip install --require-hashes -r backend/requirements.local.lock
conda run -n disaster-action-guide python -m pip install -r backend/requirements.team.txt

# 프론트엔드
cd frontend; npm ci; cd ..
```

### 2. 경로 엔진 타일 만들기

한국 OSM 데이터(약 290MB)를 받아 광주 범위로 잘라 `.local-data/valhalla/`에 만듭니다. 처음 한 번만 하면 됩니다.

```powershell
conda create -n disaster-action-guide-osm -c conda-forge --override-channels osmium-tool=1.19.1 -y
.\data_pipeline\build_valhalla_tiles.ps1
```

`VALHALLA_TILES_OK`가 출력되면 성공입니다.

### 3. API 키 넣기 (선택)

```powershell
Copy-Item .env.example .env
```

`.env`를 열어 키를 넣습니다. **이 파일은 Git과 배포에서 제외됩니다.** 키를 저장소나 프론트엔드 코드에 넣지 마세요.

| 변수 | 발급처 | 필요한 활용 신청 |
| --- | --- | --- |
| `KAKAO_REST_API_KEY` | Kakao Developers | 로컬 API |
| `KMA_SERVICE_KEY` | 기상청 API허브 또는 공공데이터포털 | 초단기실황, 호우 특보 |

기상청 키 종류는 자동으로 구분합니다. API허브에서는 특보 현황(`wrn_now_data.php`)을 신청해야 합니다.

### 4. 서버 켜기

PowerShell 창 두 개에서 각각 실행합니다.

```powershell
.\scripts\dev-backend-conda.ps1
```

```powershell
.\scripts\dev-frontend.ps1
```

http://127.0.0.1:5173 으로 접속합니다.

### 5. 시연하기

1. `시연 경로 보기`를 누릅니다. 광주송정역 → 광주역 경로가 계산되고 데모 모드가 켜집니다.
2. `0mm` → `35mm` → `55mm` → `75mm`를 차례로 눌러 경로와 지나는 구역이 바뀌는 것을 봅니다.
3. `안내 시작`을 눌러 운행 화면을 봅니다. 오른쪽 위에서 배속을 바꿀 수 있습니다.

### 테스트

```powershell
cd backend; conda run -n disaster-action-guide python -m pytest tests -q; cd ..
cd frontend; npm run build; npm run lint; cd ..
```

백엔드 테스트는 실제 엔진, 카카오, 기상청 없이 돌아갑니다.

## 데이터

| 유형 | 구역 수 | 상태 | 출처 |
| --- | --- | --- | --- |
| 침수 이력 | 657 | 실제 자료 | 광주 북구·서구·광산구 공개 침수 피해 기록 2021~2025 ([안내](risk_zones_guide.md)) |
| 지하차도 | 2 | **더미** | 실제 자료 확보 전 임시 구역 |
| 하천변 | 2 | **더미** | 실제 자료 확보 전 임시 구역 |

도로망은 OpenStreetMap, 지도 타일은 OpenFreeMap입니다. 지도 데이터 © OpenStreetMap 기여자.

## 현재 한계

- 지하차도와 하천변 구역은 더미 데이터입니다.
- 침수 이력에 동구와 남구 자료가 없습니다. 그 지역이 안전하다는 뜻이 아닙니다.
- 강수량은 1시간 단위 관측값이라 빠르게 변하는 집중호우를 바로 반영하지 못합니다.
- 운행 화면은 시연 주행입니다. 실제 위치 추적, 경로 이탈 재탐색, 음성·차선·카메라 안내가 없습니다.
- 위험 구역을 모두 피하는 경로를 찾지 못하면 회피 없는 경로를 경고와 함께 보여줍니다.
- 실시간 교통을 반영하지 않습니다.

## 문서

- [요구사항](.kiro/specs/disaster-guide/requirements.md), [설계](.kiro/specs/disaster-guide/design.md), [작업](.kiro/specs/disaster-guide/tasks.md)
- [침수 데이터 안내](risk_zones_guide.md)
- [스타터 안내와 서버 배포](docs/starter-r2.md), [운영자용 도구](ops/README.md)

# 구현 작업 — 호우 위험 구역을 피해 가는 안전 경로 안내 서비스

요구사항: #[[file:requirements.md]]
설계: #[[file:design.md]]

작업마다 관련 테스트를 돌린다. 백엔드는 `backend` 폴더에서 `conda run -n disaster-action-guide python -m pytest`, 프론트는 `frontend` 폴더에서 `npm run build`, `npm run lint`를 쓴다. Git 커밋은 사용자가 요청할 때만 한다.

- [x] 1. 환경 준비
  - [x] 1.1 conda 환경 `disaster-action-guide`(Python 3.12.16) 생성, `requirements.local.lock` 설치, 기존 테스트 23개 통과
  - [x] 1.2 pyvalhalla 3.9.1, shapely 2.2.0, pyproj 3.8.0 설치, `backend/requirements.team.txt` 기록
  - [x] 1.3 `npm ci`, maplibre-gl 6.16.0 추가, 기존 build·lint 통과
  - [x] 1.4 `data_pipeline/build_valhalla_tiles.ps1` 작성·실행(광주 자르기, 타일 14개, tiles.tar)
- [x] 2. `scripts/dev-backend-conda.ps1` 작성 (설계 12절)
- [x] 3. 설정·위험 레이어·점수 (요구사항 3.3, 4.7)
  - [x] 3.1 `config/strategies.yaml`, 설정 읽기·검사(지연 로딩)
  - [x] 3.2 `risk/layer.py`: 구역 읽기, 사용 중 구역, EPSG:5179 변환, 회피 다각형(버퍼·단순화), 출발·도착 포함 검사
  - [x] 3.3 `risk/scoring.py`: 위험 노출 점수, 지나는 구역 목록
  - [x] 3.4 테스트: `test_risk_scoring.py`, 설정 검사
- [x] 4. 데이터와 파이프라인 (요구사항 3.1, 3.2, 3.4, 3.8, 1.7)
  - [x] 4.1 `data_pipeline/pipeline.yaml`, `zones.py`, `build_risk_zones.py`, `sources/dummy_seed.json`, `readers.py`(원본별 읽기 자리)
  - [x] 4.2 `app/data/risk_zones.geojson` 생성(설계 4.3), `app/data/demo_points.json`(설계 4.4)
  - [x] 4.3 테스트: `test_data_pipeline.py`, `test_risk_data.py`(3.8)
- [x] 5. 경로 엔진 어댑터 (요구사항 5)
  - [x] 5.1 `engines/base.py`
  - [x] 5.2 `engines/fake.py`
  - [x] 5.3 `engines/valhalla.py`(단일 작업자 실행기, 시간 제한, ASCII 경로, 요청 구성, 오류 코드 매핑, 로그 끔, 깨진 도로명 응답 복구)
  - [x] 5.4 테스트: `test_valhalla_engine.py`(가짜 Actor)
  - [x] 5.5 `data_pipeline/check_demo_scenario.py`로 실제 타일에서 시나리오 A·D 확인
- [x] 6. 알고리즘 (요구사항 4)
  - [x] 6.1 `strategies/base.py`, `params.py`, `registry.py`(`@register`, 자동 탐색, 파라미터 검사)
  - [x] 6.2 `baseline.py`, `hard_exclude.py`, `tiered_rain.py`, `rerank.py`, 회피 실패 처리
  - [x] 6.3 테스트: `test_strategies.py`(4.11 전체, 4.3, 4.10)
- [x] 7. 기상 컨텍스트 (요구사항 2)
  - [x] 7.1 `context/weather_mock.py`, `context/weather_kma.py`(실황, 특보코드조회, 광주 코드, 10분 캐시, 키 보호)
  - [x] 7.2 `api/weather.py`
  - [x] 7.3 테스트: `test_weather.py`
- [x] 8. 장소 검색 (요구사항 1)
  - [x] 8.1 `context/kakao.py`(키워드·주소, 광주 판정, 데모 대체)
  - [x] 8.2 `api/search.py`
  - [x] 8.3 테스트: `test_search.py`
- [x] 9. 경로·구역·설정 API와 등록 (요구사항 3.5, 4.2, 5.4, 7.3, 7.4)
  - [x] 9.1 `api/route.py`, `api/risk.py`, `api/strategies.py`(app-config, demo-points 포함), `api/deps.py`
  - [x] 9.2 `main.py`에 라우터 등록(`/api/health` 유지), 422 응답에서 요청 값 제거
  - [x] 9.3 테스트: `test_route_api.py`(5.7, 7.3, 7.4), 전체 pytest
- [x] 10. 프론트엔드 (요구사항 1, 2, 3.5~3.7, 6, 7)
  - [x] 10.1 `lib/types.ts`, `lib/api.ts`, `lib/level.ts`, `lib/format.ts`, `components/ui/slider.tsx`, `switch.tsx`
  - [x] 10.2 `MapView.tsx`(워커 주소 지정), `RiskLayer.tsx`
  - [x] 10.3 `SearchBar.tsx`, `WeatherPanel.tsx`, `RoutePanel.tsx`
  - [x] 10.4 `App.tsx` 교체(배치, 다시 계산 규칙, 안전 고지)
  - [x] 10.5 `npm run build`, `npm run lint`
- [x] 11. 통합 확인
  - [x] 11.1 백엔드·프론트 실행, 헤드리스 Chrome으로 시나리오 A, D 확인(화면 캡처 `.local-data/screens/`)
  - [x] 11.2 키 없이 B, C 대체 흐름, 알고리즘 교체, 현재 위치(위치 재정의), 네트워크 기록 확인
  - [x] 11.3 전체 pytest(176개), build, lint 최종 실행
- [x] 12. 결과 보고
- [x] 13. 비용 기반 단계 회피 (B안, 설계 5.7, 요구사항 4.5·4.9 변경분)
  - [x] 13.1 `strategies.yaml`: 단계별 hard/soft, 유형별 진입·m당 벌점. 설정 검사(겹침, 누적, 예전 목록 형식)
  - [x] 13.2 `strategies/params.py`: 벌점 덮어쓰기(tiered_rain), `ResolvedParams`에 hard/soft·벌점
  - [x] 13.3 `strategies/base.py`: `collect_candidates`(모든 회차·대안 보존, 멈춘 이유), 비용 선택, `partially_avoided`, `clear_option`
  - [x] 13.4 `tiered_rain`, `hard_exclude`, `rerank`를 후보 모음으로 전환
  - [x] 13.5 API·app-config(`hard_by_level`, `soft_by_level`), 프론트(일부 회피 주의 상자, 단계 문구)
  - [x] 13.6 테스트: hard 거르기, soft 비용 비교와 일부 회피, 벌점 덮어쓰기, 중간 회차 후보 보존, 출발·목적지를 덮는 soft 구역, 설정 검사, 기존 테스트 갱신
  - [x] 13.7 실제 타일로 시나리오 A·D 확인, 브라우저 확인, 전체 pytest(192개)·build·lint

# r2 검증 기록 — 2026-10-28

## 이번에 확인한 범위

운영 서버가 아닌 Linux/Python 3.12 격리 환경에서 수행했다.
Node.js는 24.22.1이며 프론트 의존성은 r1과 동일한 잠금 파일의 설치본을 사용했다.
실제 Bedrock 호출·IAM·버킷·Nginx·systemd·운영 DB는 이번 검사로 변경하지 않았다.

| 검사 | 결과 |
|---|---|
| 백엔드 API·모의/제공자 응답 계약·스키마·팀 확장·호출 한도·Windows 의존성 고정 | pytest 23개 통과 |
| 배포·자동 코드 복구·파일 보존·SQLite 백업·복구 리허설 | unittest 20개 통과 |
| TypeScript 및 Vite 프로덕션 빌드 | 성공, 기존 __dirname 경고 해소 |
| Vite↔FastAPI 실제 HTTP 프록시 | JSON 응답 확인 |
| 저장 없는 모의 AI 호출 | mode=mock, 기록 DB 레코드 추가 없음 |
| API 프로세스 종료·재시작 후 기존 기록 | 유지 |
| 팀 전용 테이블/API 신규 추가·저장 | 성공 |
| r1 복사본에서 r2 코드 패키징·추출·실제 백엔드 검사·프론트 빌드 | 성공, 기존 임시 기록 DB 해시 유지 |
| 기존 테이블에 컬럼을 나중에 추가 | 검토 필요로 중단, DB 자동 변경 없음 |

호출량은 실제 임시 SQLite로 분당 20회, 하루 600회, 한국시간 자정 경계도 검사했다.
제공자 응답 검사는 boto3 모의 객체를 사용했으며 실제 AI 모델을 호출하지 않았다.

## 남은 경고

- Starlette TestClient/httpx 조합의 향후 지원 변경 경고 1건. 테스트는 통과했다.
- lint는 성공했으나 shadcn Button/Badge의 Fast Refresh 경고 2건과 기존 App 효과 패턴 경고 1건이 남는다.
- 이를 이유로 검증된 런타임/의존성을 임의 업그레이드하지 않았다.

## Windows 설치에서 발견한 문제와 수정

사용자의 Python 3.12.10/Node 24.13.0 Windows PC에서 최초 로컬 설치를 수행했을 때,
pytest가 Windows에서만 요구하는 colorama가 잠금 파일에 빠져 --require-hashes 설치가 중단됐다.
pip의 새 버전 알림이 원인은 아니며 해시 검증을 끄거나 패키지를 임의 선행 설치하지 않는다.
windows-lock-1 패치는 requirements.local.lock에 colorama==0.4.6과 공식 wheel/sdist SHA256을 추가했다.
서버용 requirements.lock, 설치 스크립트, 앱 코드, DB, 운영 서버는 수정하지 않았다.
Windows 환경 마커를 적용한 설치된 패키지 메타데이터의 의존성 고정 검사도 추가했다.
추가로 Windows CPython 3.12/x64용 wheel 39개를 --require-hashes로 교차 다운로드하고,
다운로드한 wheel의 메타데이터에서 Windows 의존성과 활성 extra의 버전 고정·누락 여부를 검사했다.
이는 Linux에서 수행한 대상 플랫폼 검사이며 Windows 바이너리를 실행한 것은 아니다.
이 검사는 네이티브 Windows 설치 성공을 대신하지 않으므로 수정 후 사용자 PC 재실행이 필요하다.

## 완료로 표시하면 안 되는 항목

- 사용자 Windows에서 새 setup-local/dev 스크립트를 실제 실행하는 시험.
- r2 서버 도구 교체와 r2 앱을 1조에 배포한 후 실제 Haiku 호출·롤백.
- 2조에서 빈 서버부터 설치하는 시험 및 3~6조 확대 적용.
- 학생 5명의 Git 통합 작업, 실제 Kiro 세션에서의 기능 개발, 다른 승인 모델의 실제 호출.
- 외부 공개·HTTPS와 S3 자동 백업.

이 파일은 격리 검증 결과이지 모든 팀의 최종 설치 완료 확인서가 아니다.

# 전남대학교 Kirothon 공통 스타터 r2

운영진 검증용 후보 버전이다. 학생 공지문이나 완성된 주제 서비스가 아니다.
원본 r1과 1조 운영 서버는 이 패키지를 만들면서 변경하지 않았다.

## 개발 방식

각자 Kiro에서 로컬 소스를 편집하고 로컬 화면·API로 확인한다.
로컬 AI는 표시가 있는 모의 응답이다. 실제 AI 품질 검증은 팀 서버에 배포한 뒤 수행한다.
통합 담당자 한 명이 Git으로 합친 소스를 Check → Deploy하며, 서버의 EC2 IAM 역할로 Bedrock을 호출한다.
PEM은 배포 담당자의 프로젝트 밖에만 둔다. 다른 팀원이 로컬 개발하려고 PEM·AWS 키를 받을 필요는 없다.
Git 저장소·브랜치·권한 연결은 아직 운영진이 별도로 준비해야 한다.

## 유지하는 기술

- Python 3.12 + FastAPI + SQLModel/SQLite + boto3.
- React + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui Nova + Lucide.
- 서버용 backend/requirements.lock, 프론트 package.json 및 package-lock.json은 검증된 r1 그대로다.
- Docker, RDS, Redis, 벡터DB, CI/CD를 추가하지 않았다.

## r2의 변경점

- Vite /api → 로컬 FastAPI 8000 프록시. __dirname 경고를 import.meta.dirname으로 수정.
- POST /api/ai/generate: 기록 생성·저장 없이 AI 호출. 기존 기록 CRUD/AI 경로 유지.
- KIROTHON_AI_MODE=mock: 실제 AWS 호출이 없는 로컬 개발 모드. 기본 서버 모드는 bedrock.
- 공통 API 두 경로 모두 기존 분당 20회/한국시간 하루 600회, 출력 256토큰 제한 유지.
- app/team/models.py와 team/routes.py를 팀별 신규 테이블·API 확장 지점으로 등록.
- 이미 배포된 테이블의 컬럼 변경은 사전 검사/앱 시작 시 중단. 데이터를 지우거나 자동 변환하지 않음.
- ops/deploy.py r2: 배포 전 백엔드 import·기존 DB 컬럼 호환성 검사 추가.
- Windows용 로컬 설치·API 실행·프론트 실행 스크립트 추가.

## Windows 로컬 준비

사전 설치: Python 3.12와 Node.js 24.x. 설치되어 있는지는 먼저 조회한다.
이 스크립트는 Python/Node나 관리자 권한을 자동 설치·요청하지 않는다.

```powershell
py -3.12 --version
node --version
```

압축은 r1과 다른 새 폴더에 푼다. scripts/verify-template.ps1은 받은 원본의 해시를 확인하는 용도다.
코드를 수정한 뒤 이 검사를 실행하면 달라졌다고 나오는 것이 정상이다.
서명/실행 정책 오류가 나면 정책을 끄지 말고 운영진이 해시와 적용 정책부터 확인한다.

최초 설치:

```powershell
.\scripts\setup-local.ps1
```

프로젝트 backend/.venv에만 Python 패키지를 설치하고, 프론트는 npm ci를 사용한다.
requirements.local.lock은 서버 잠금 파일에 uvloop의 Windows 제외 조건과 Windows 전용 colorama의 버전·해시를 반영한 파일이다.
Windows에서는 uvloop를 설치하지 않으며 uvicorn은 기본 asyncio로 동작한다.
서버용 requirements.lock은 바꾸지 않는다.

PowerShell 창 두 개에서 각각 실행:

```powershell
.\scripts\dev-backend.ps1
```

```powershell
.\scripts\dev-frontend.ps1
```

접속: http://127.0.0.1:5173. 로컬 DB는 프로젝트 .local-data/에만 저장한다.
창을 닫거나 Ctrl+C를 누르면 로컬 개발 프로세스만 종료된다. 서버 서비스는 영향을 받지 않는다.
setup-local.ps1은 버전 확인 후 기존 로컬 의존성 환경을 설치/동기화하므로 본인 작업 복사본에서만 실행한다.

## 주제별 확장

- 화면: frontend/src. 기존 shadcn/ui 컴포넌트를 재사용한다.
- 신규 테이블: backend/app/team/models.py. 신규 API: team/routes.py. 둘 다 main.py에 등록돼 있다.
- 별도의 team 모델 파일을 만들면 team/models.py에서 import해 create_all 전에 등록해야 한다.
- 선택형 Record 예제를 쓰지 않아도 독립 AI API를 활용할 수 있다. 기존 운영 데이터는 자동 삭제하지 않는다.
- models.py의 기본 Record와 database.py의 운영 경로는 보호한다. 팀 주제 모델을 이 파일에 억지로 넣지 않는다.
- 최초의 신규 테이블 생성은 지원하지만, 이미 생성된 컬럼·타입·NULL/PK를 바꾸면 멈춘다.
- 컬럼 검사는 완전한 마이그레이션/제약조건 변경 검증기가 아니다. 인덱스·고유/FK/기본값 변경도 멘토 검토가 필요하다.
- 필요하면 멘토가 백업 후 명시적인 데이터 보존 마이그레이션을 검토한다. DB 삭제로 우회하지 않는다.
- 새 라이브러리와 잠금 파일 변경은 멘토가 별도로 준비한다.

독립 AI 예시 요청 형식:

```json
{"text":"사용자 입력", "instruction":"한국어로 간결하게 정리해줘."}
```

model_id 생략 시 Haiku 4.5가 기본값이다. 모의 응답에는 mode=mock이 명시된다.
API는 입력·결과를 Record에 저장하지 않지만 별도 DB에 호출 횟수는 기록한다.
서버의 AWS 제공자 처리·보관까지 무저장을 보장하는 의미는 아니다.

## 서버 배포

Windows SSH/SCP 배포·롤백 방식은 r1과 같다. PEM은 소스 폴더 밖에 둔다.

```powershell
.\scripts\deploy.ps1 -ServerHost TEAM_IP -KeyPath PEM_PATH -Mode Check
.\scripts\deploy.ps1 -ServerHost TEAM_IP -KeyPath PEM_PATH -Mode Deploy
```

위의 TEAM_IP/PEM_PATH는 실제 값으로 바꿔야 한다. 인증을 끄거나 호스트키 검증을 건너뛰지 않는다.
DB·.env·키·로컬 데이터·설치 폴더는 업로드하지 않는다. 서버 빌드 후 API를 잠깐 재시작한다.
코드 롤백은 DB 복원이 아니다. 새로 생성된 테이블이나 이미 저장한 레코드는 자동 삭제하지 않는다.

서버의 ops/deploy.py r2 적용은 운영자용 별도 단계다. 기존 서버 도구를 이 ZIP만으로 자동 갱신하지 않는다.
운영자 지침은 ops/README.md를 참고한다. 지금은 1조 서버가 자동으로 r2로 바뀐 상태가 아니다.

## 검증과 남은 단계

Linux 격리 환경에서 자동 테스트, 실제 프론트 빌드, Vite↔FastAPI HTTP 통합,
모의 AI·기록 저장·프로세스 재시작 후 유지, 팀 전용 모델/API 추가를 검사한다.
실제 AWS 호출을 이 패키지 검사에서 재실행하지 않는다.

- r1 Windows Check/Deploy/Rollback와 1조 웹·데이터 유지는 운영자 실행으로 확인됨.
- r2 Windows 로컬 설치·실행, r2 1조 실제 배포·Bedrock 호출, 2조 신규 설치는 아직 별도 검증 필요.
- 2~6조는 서로 다른 리전이다. EC2 리전, Bedrock 호출 리전, S3 버킷 리전을 구분한다.
- KIROTHON_BEDROCK_REGION 기본값은 기존 검증값 ap-northeast-1. 다른 리전으로 임의 치환하지 않는다.
- 다른 허용 모델 5개는 실제 호출 검증 완료로 간주하지 않는다.
- 외부 공개/HTTPS와 S3 자동 백업은 이 버전에서 추가하지 않는다.

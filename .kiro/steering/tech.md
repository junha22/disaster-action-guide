---
inclusion: always
---

# 공통 기술 기준

- Python 3.12 + FastAPI + SQLModel/SQLite + boto3를 사용한다.
- 프론트엔드는 React + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui Nova + Lucide를 사용한다.
- backend/requirements.lock과 frontend/package-lock.json의 검증된 의존성을 유지한다.
- 프로젝트를 새로 생성하거나 Next.js, Docker, RDS, Redis, 벡터DB, Kubernetes로 임의 교체하지 않는다.
- 팀 주제의 새 테이블은 backend/app/team/models.py에, API는 team/routes.py에 추가한다. 신규 테이블 생성에는 기본 Record 모델 변경이 필요 없다.
- 새 라이브러리 또는 이미 배포된 테이블의 구조 변경은 이유·변경 범위·데이터 보존 계획을 정리해 멘토 검토를 요청한다.
- 기본 템플릿은 기록 CRUD와 AI 처리 예제다. 팀별 주제에 필요한 핵심 기능에 집중한다.
- 주최 측의 사전 데이터 또는 새 AWS 서비스 제공을 가정하지 않는다.
- 기본 models.py·database.py 및 의존성 잠금 파일 변경은 보호한다. 팀 전용 모델은 확장할 수 있지만 기존 테이블 컬럼 변경은 호환성 검사에서 멈춘다. 검사를 우회하거나 DB를 지우지 않는다.


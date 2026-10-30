---
inclusion: always
---

# 코드 구조

- backend/app/main.py: API 진입점 및 lifespan.
- backend/app/routers/records.py: 기록 CRUD.
- backend/app/routers/ai.py: 독립 /api/ai/generate 및 기존 기록 AI API.
- backend/app/ai_service.py: 공통 모델 목록·모의/Bedrock 분기·호출량 제한·최대 256토큰.
- backend/app/team/models.py, team/routes.py: 팀 주제의 신규 테이블·API 확장 지점. main.py에서 이미 등록한다.
- backend/app/schema_check.py: 기존 SQLite 컬럼 호환성 검사. 자동 마이그레이션 도구가 아니다.
- backend/app/models.py: SQLModel 모델. 변경은 별도 검토 대상.
- backend/app/database.py: 서버 SQLite 경로와 요청별 세션. 운영 DB 경로를 보존한다.
- backend/app/ai_quota.py: 별도 호출량 DB를 이용한 제한.
- frontend/src/App.tsx: 기본 대시보드. 팀 주제에 맞춰 수정 가능.
- 로컬 개발은 dev-backend.ps1과 dev-frontend.ps1을 별도 창에서 실행한다. Vite /api 프록시는 127.0.0.1:8000으로 연결한다.
- 로컬 AI는 명확히 표시된 mock 응답이며 AWS를 호출하지 않는다. 모의 응답을 실제 AI 결과처럼 표현하지 않는다.
- frontend/src/components/ui/: 이미 제공한 shadcn/ui 컴포넌트를 재사용한다.
- 프론트의 API 호출은 상대 경로 /api/를 사용한다. 브라우저에서 AWS 키나 Bedrock을 직접 사용하지 않는다.
- /api/health는 배포 검증 계약이므로 유지한다.
- 대화만으로 구현하지 말고, 선택한 주제의 요구사항·설계·작업을 .kiro/specs/에 정리한 뒤 작은 단위로 구현한다.


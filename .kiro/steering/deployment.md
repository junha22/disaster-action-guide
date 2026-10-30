---
inclusion: always
---

# 개발·배포 기준

- 로컬 폴더의 코드를 원본으로 관리하고 Git에 변경 이력을 남긴다. 기존 Git 설정이나 원격 저장소는 임의 변경하지 않는다.
- 각자 로컬 PC에서 화면·API를 실행하고 Kiro로 개발한다. 로컬 DB는 .local-data/, AI는 mock이다. 서버는 실제 Bedrock·팀 통합·공식 배포 환경이다. 로컬에 AWS 액세스 키를 설정하거나 서버의 자격 증명을 가져오지 않는다.
- PEM은 프로젝트 밖에 둔다. Kiro는 키 파일 경로를 SSH/SCP 인자로 사용하되 키 내용은 읽거나 대화에 출력하지 않는다.
- Windows에서는 scripts/deploy.ps1의 Check를 먼저 사용한다. Check 성공 후 통합 담당자가 Deploy를 수행한다.
- 호스트키 검증 실패 시 StrictHostKeyChecking을 끄지 않는다. 운영진이 확인한 서버 지문과 비교한다.
- 서버 프로젝트는 /home/ubuntu/kirothon, 배포 도구는 /home/ubuntu/kirothon-tools/deploy.py다.
- 모든 팀원이 같은 서버 소스를 직접 덮어쓰지 않는다. 개인 브랜치로 개발하고 통합 담당자 한 명이 공식 배포한다.
- .env, DB, PEM, 운영 인증 파일, node_modules, .venv를 코드 배포물에 포함하지 않는다.
- 팀 전용 신규 테이블·API는 team/에서 추가한다. 기본 DB 연결·Record 모델·의존성 변경 또는 기존 테이블 컬럼 변경은 멘토 검토가 필요하다.
- ops/deploy.py r2는 운영자용 서버 도구다. 학생 코드 배포로 자동 갱신하지 않는다. 서버 도구 버전은 운영진이 백업 후 별도로 확인·적용한다.
- 로컬 .local-data DB를 서버에 올리지 않는다. 코드 롤백은 DB 스키마 롤백이 아니며 신규 생성된 테이블을 자동 삭제하지 않는다.
- 실패하면 배포 이력의 release ID를 확인해 코드만 롤백한다. 호출량 DB나 기록 DB를 과거로 되돌리지 않는다.
- 현재 공식 접근은 SSH 터널과 Nginx Basic Auth다. 인증 해제·외부 공개·새 포트 개방은 자동으로 수행하지 않는다.
- Check나 Deploy 오류가 나면 오류 유형과 배포 ID를 보고한다. 비밀번호·환경변수 전체·AWS 자격 증명을 출력하지 않는다.

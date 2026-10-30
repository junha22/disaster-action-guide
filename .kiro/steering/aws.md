---
inclusion: always
---

# AWS 사용 기준

- AWS 인증은 서버에 이미 연결된 EC2 IAM 역할을 이용한다. 새 액세스 키나 API 키를 생성하지 않는다.
- Bedrock 호출은 서버의 boto3 코드로 수행한다. 현재 기준 서버는 도쿄(ap-northeast-1)이며 검증된 설정을 유지한다.
- Kiro 로그인 리전과 Bedrock/EC2 리전을 혼동하지 않는다.
- 기본 UI의 Claude Haiku 4.5는 실제 호출 검증됐다. 다른 허용 모델은 각 팀에서 사용하기 전에 실제 호출 확인이 필요하다.
- 모델 허용 목록은 backend/app/ai_service.py와 운영진의 IAM 범위를 따른다. 목록에 없는 모델을 임의 추가하지 않는다.
- 로컬은 dev-backend.ps1이 KIROTHON_AI_MODE=mock으로 실행한다. AWS 자격 증명·PEM이 없어도 개발할 수 있으며, 서버의 자격 증명을 로컬로 가져오지 않는다.
- 서버의 기본 모드는 bedrock이며 기존 EC2 역할을 사용한다. KIROTHON_BEDROCK_REGION은 Bedrock 호출 리전으로 EC2 리전과 별개다. 현재 기본값 ap-northeast-1을 다른 팀의 EC2 리전으로 임의 치환하지 않는다.
- import 시점에 AWS 호출·리소스 생성·운영 DB 쓰기를 실행하지 않는다. 서버 Check는 모의 AI와 임시 데이터 경로로 import/스키마 검사를 수행한다.
- 임베딩은 운영진이 허용한 Titan Embeddings v2가 필요한 경우만 검토한다. 별도 벡터DB를 기본 설치하지 않는다.
- 기존 팀별 S3 버킷만 사용한다. 새 버킷 생성·버킷 정책·IAM·보안그룹 수정은 운영진에게 요청한다.
- S3 파일 저장 기능과 S3 자동 백업은 별개다. 자동 백업은 기본 미적용 상태를 유지한다.
- 요청 크기·출력 토큰·호출량 제한을 임의 해제하지 않는다. 실제 AWS 비용을 고려하고 불필요한 재시도·반복 호출을 피한다.


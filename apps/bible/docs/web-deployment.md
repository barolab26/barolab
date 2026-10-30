# 독립 앱 안내 웹 배포

기존16개CF콘텐츠 도메인·도메인루트·Worker·DNS를 수정하지 않고 별도Cloudflare Pages 프로젝트 `haru-malsseum`을 사용한다. 정적HTML/CSS만 있으며 백엔드·회원가입·분석SDK·광고스크립트는 없다. Cloudflare의 전달·보안 로그 처리는 개인정보 안내에 명시한다.

원본은 `apps/bible/web/`. 배포기록은 `apps/bible/docs/web-deployment-receipt.json`에 공개URL·배포ID·파일해시·실제HTTP검증 결과를 남긴다. 2026-10-14 사용자 표시명을 ‘오늘의 성경말씀’으로 변경했다. v4(0.4.0-internal-preview) 내부 제공을 2026-10-14 19:13 KST에 확인했다. 등록된 내부 테스터용 참여 링크만 표시하며 정식 공개 출시는 미완료다. 기존 package·Pages 프로젝트·도메인·광고 식별자는 유지한다.

인증은 기존 `.env`의 공식Cloudflare설정에서 메모리로 읽어사용한다. 비밀값을원고·명령인자·배포파일·기록에저장하지않는다. 키값출력금지. 배포는 검토된정적폴더만 Wrangler Pages directupload로진행한다.

## 공식 근거

- Google app-ads 설정: https://support.google.com/admob/answer/9363762?hl=en
- Google 판매자정보4필드 형식: https://support.google.com/admanager/answer/9422161?hl=en
- Google SDK 데이터 공개: https://developers.google.com/admob/android/privacy/play-data-disclosure
- Cloudflare 직접 업로드: https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/

`app-ads.txt`는 `google.com, pub-7642010403138987, DIRECT, f08c47fec0942fa0` 한줄이다. 실제앱·스토어개발자웹사이트연결·AdMob크롤러검증은 별도로확인해야한다.

## 초안 검토 기록

인증된로컬FreeLLMAPI auto 실제호출은 `openai/gpt-oss-20b`, 1,748토큰, 1,982ms였다. 후보가 이름입력·Crashlytics·24시간이내삭제를 잘못추가하여 이내용은사용하지않았다. 실제앱코드와앱담당확인으로수동작성했다. 공유캐시정리는24시간후정시삭제가아니라 다음공유때24시간지난파일삭제이고, TTS는기설치된오프라인한국어음성만선택한다.

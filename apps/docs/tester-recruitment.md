# Android 실제 테스터 모집 채널 조사

확인일 2026-10-14 KST. 읽기전용 공개 페이지 조사. 가입·로그인·외부 게시·결제·상대 앱 설치는 실행하지 않았다. 이 파일만 본 작업자가 소유하며 실제 게시·Play 트랙 확인은 총괄이 담당한다. 가입자·방문자·설치·opt-in·14일 완료는 조사 결과가 아니다.

## 먼저 사용할 경로

초기 조사상 안드로이드펍·Reddit 3개·Twelve Testers가 우선 후보였으나, 후속 사용자 답변으로 Reddit/안드로이드펍 계정이 없음이 확인됐다. 이들을 현재 계정으로 즉시 게시 가능한 채널로 취급하지 않는다. SNS 기존 계정에서의 실제 게시 여부는 총괄이 별도 검증한다. 국내 당근 테스트 게시판과 네이버 devsharing은 가입/게시 권한을 실제 화면에서 확인해 이어간다. 서비스 앱 기반 후보는 무료 등록 범위와 실제로 수행 가능한 맞테스트 수를 확인한 뒤 등록한다. 각 채널에 같은 문장을 기계적으로 반복하지 않고 앱의 검증 과제와 해당 규칙에 맞춘다. 익명 대량 요청이나 단순 별점·설치 수 교환을 제안하지 않는다.

아래 ‘확인’은 공개 페이지에 해당 설명/모집 사례가 보였다는 뜻이며, 현재 운영자 계정으로 글을 쓸 권한까지 확인한 것이 아니다. 정확한 글쓰기 URL이 공개되지 않은 곳은 가입 진입점만 적었으며 비공개 게시판 ID를 추측하지 않았다. Karma·가입일·등업 요건이 공개 규칙에 없으면 ‘미공개/미확인’으로 남겼다.

## 후보 13개 — 활성 확인과 조건 미확인을 분리

| 번호·채널 | 정확한 등록/진입 URL과 현재 확인 | 회원·등급·규칙 | closed 링크 필요 / 판단 |
|---|---|---|---|
| 1 국내 안드로이드펍 개발자 게시판 | [글쓰기](https://www.androidpub.com/index.php?act=dispBoardWrite&mid=devfree), [목록](https://www.androidpub.com/devfree). 10/13 비공개 모집글 다수 확인. 쓰기는 비로그인에서 ‘권한이 없습니다’. | 회원 로그인 필요. 별도 등급/대기기간 미확인. 공지에 개발 질문 게시판 구분/계정 거래 금지. | 공개 사례에 그룹+실제 Play 참여 링크. 링크 필수라는 전체 규칙은 확인 못함. **우선 후보**, 총괄 로그인 권한 확인. |
| 2 국내 네이버 개발자 상부상조 품앗이 카페 | [카페](https://cafe.naver.com/devsharing). 기존 portfolio-plan 및 외부 소개에서 위치 확인; 공식 카페는 이번 도구 robots/접속 차단. | 카페 가입/등업/게시판 양식/홍보 제한 **전부 미확인**. 2024 소개를 현재 규칙으로 사용하지 않음. | 정확한 글쓰기·게시판 ID 미확인. **총괄 브라우저에서 현행 공지 확인 후보**, 이미 가입됐다고 가정하지 않음. |
| 3 국내 당근 카페 ‘앱 어플 개발자 테스터/리뷰 품앗이’의 앱 테스트 게시판 | [실제 앱 테스트 품앗이 게시판](https://cafe.daangn.com/aeb-eopeul-gaeb/boards/%E2%9C%A8-%EC%95%B1-%ED%85%8C%EC%8A%A4%ED%8A%B8-%ED%92%88%EC%95%97%EC%9D%B4-xjKOylQj). 운영 페이지에 실제 모집글/로그인 버튼 확인. | 기존 SNS9291의 새 당근탭 실제DOM에서 `로그인`·`카페 가입하기` 버튼 노출, 공개 글쓰기버튼 없음. 공지목록은 `등록된 공지사항이 없습니다.` 확인. 인증 방식/가입 후 작성 경로/등급은 미확인. 별도 **리뷰 품앗이 게시판은 사용하지 않음**. | 공개 글쓰기 폼 미노출, closed 필수 여부 미확인. 테스트/비공개 의견 교환만 허용되는지 공지 확인 후 **조건부 후보**. |
| 4 r/AndroidClosedTesting | [모집 글쓰기](https://www.reddit.com/r/AndroidClosedTesting/submit), [공개 커뮤니티/현행 규칙](https://www.reddit.com/r/AndroidClosedTesting/). submit는 로그인으로 이동. 실제 그룹/closed 모집글 확인. | Reddit 계정 필요. 공개 사이드바에 다른 subreddit 링크·변형된 우회 링크 금지. 혐오/괴롭힘 금지. Karma/가입일 제한은 미공개. | 실제 opt-in 링크를 실은 모집 사례. 공식 closed URL+그룹 제공 권장, 별도 필수 양식 여부 로그인 후 확인. **우선 후보**, 다른 Reddit 홍보 링크 넣지 않음. |
| 5 r/AndroidAppTesters | [글쓰기](https://www.reddit.com/r/AndroidAppTesters/submit), [규칙](https://www.reddit.com/r/AndroidAppTesters/). 실제 맞테스트 글/규칙 확인, submit 로그인 이동. | 공식 스토어 링크만, APK/IPA 직접 배포 금지. 적합한 `12 Testers Needed` flair, 구체적 피드백·실제 상호 참여. 중복 저품질 반복글 금지. Karma/가입일 미공개. | 공식 배포 링크 필요. closed 모집이면 실제 opt-in 경로 포함. **우선 후보**, 참여할 상대 앱을 실제 검토할 수 있는 범위만 약속. |
| 6 r/TestersCommunity | [글쓰기](https://www.reddit.com/r/TestersCommunity/submit), [규칙](https://www.reddit.com/r/TestersCommunity/). 모집글과 테스트 전용 규칙 확인. | `Testers Needed` flair, 앱명/스토어/원하는 피드백 명시. 실제 테스트 댓글에는 설치/사용 스크린샷 요구. 모호한 ‘Tested’ 댓글·제휴/유료 홍보 금지. Karma/가입일 미공개. | 스토어 링크 요구, closed 초대 링크 제공 권장. **우선 후보**, 요청글 작성과 상대 앱 테스트 완료 인증을 혼동하지 않음. |
| 7 Twelve Testers (twelvetesters.com/Syntex) | [실제 가입폼](https://twelvetesters.com/signup), [사용법](https://twelvetesters.com/how-it-works), [규칙](https://twelvetesters.com/community-guidelines). 무료 협업·공개 활성 앱 목록 확인. | 이메일/비밀번호·이메일 코드 인증 필요. 실제 시간 사용/비공개 피드백, 중복 등록·대량 저품질 요청·공개 별점/리뷰/설치 조작 금지. | 앱 아이콘/스크린샷/설명/**Play closed 링크 명시 요구**. **우선 무료 서비스 후보**. 4개 앱의 실제 별도 등록 가능 수는 인증 후 폼에서 확인. |
| 8 12 Testers / InDev’O (12-testers.org) | [공식 사용법](https://12-testers.org/how-it-works), [공식 앱](https://play.google.com/store/apps/details?id=com.twelveTesters.app). 서로 다른 서비스이므로 7번과 혼동 금지. | Google 로그인, 앱 안에서 Play 링크 입력/캠페인. 다른 앱 테스트로 Cheese 획득 또는 유료 구입 구조. 설치·가입·정확한 무료 등록 예산은 미검증. | 공식 설명에 closed 설치 경로·Google 그룹. **무료 상호테스트 조건부**. Play 설명에 구식20명 문구도 있어 Google 요건 근거로 사용하지 않음. |
| 9 SwapTest / 306Games | [공식 사이트](https://swaptest.net/), [공식 앱 등록 진입](https://play.google.com/store/apps/details?id=com.swaptest.swaptest_app). 실제 무료/유료 요금과 상호테스트 설명 확인. | 무료 플랜 **활성 앱 1개 슬롯**, 상호 테스트·실제 앱 안의 일별 스크린샷 방식. 계정/등록 세부폼은 앱 내부라 미확인. | 공식 앱 설명은 Play closed 링크 제출. **무료1앱 후보**, 4앱 무료 동시 등록으로 오인 금지. ‘우회/승인 보장’ 등 사이트 마케팅은 보장 근거 아님. |
| 10 Testers Community / Duho Corp | [공식 앱](https://play.google.com/store/apps/details?id=com.testerscommunity), [사이트](https://www.testerscommunity.com/), [그룹 권한](https://groups.google.com/g/testers-community/about). 앱은16명/16일 Pack 실제 설명; 사이트는 유료 대행 표시. | **Google 그룹은 소유자/관리자만 게시 가능**, 일반 가입자가 모집글 올리는 게시판 아님. 그룹의 옛 ‘3앱 테스트 후 credit’ 소개와 현행 앱 Packs가 달라 무료 비용/등록 조건은 앱에서 재확인. | 앱/사이트 등록폼으로 진행, closed 경로 필요. **조건부 앱 후보**, 그룹에 메일로 무단 모집하지 않음. 웹 결제는 이번 무료 모집으로 실행하지 않음. |
| 11 국내 Discord ‘안드로이드 플레이스토어 비공개테스트 대행’ | [실제 서버 초대](https://discord.com/invite/jRbpWRdvWR), [운영자 공식 소개글 10/12](https://www.androidpub.com/devfree/3121108). 초대 페이지의 서버명은 확인, 내부 채널은 미열람. | Discord 로그인·서버 가입 필요. 운영 소개는 테스터 명단 등록/대한민국 배포/활성 closed 트랙/신청 채널 안내. 비용·게시 권한 미확인. | closed 활성 필요. **직접 품앗이 모집 우선 대상에서 보류**: 글이 설명한 것은 실기기 설치·실행 자동화18일이며 인간 사용성 평가와 별개. 유료 대행 신청으로 전환하지 않음. |
| 12 국내 Kakao 오픈채팅 비공개 테스트 품앗이 | [확인 시도한 방 링크](https://open.kakao.com/o/gcrp8BXf). 2024년 소개에서 발견했으나 공식 공개 링크 이번 접근 실패. | 현존 여부·인원·현재 공지·참여코드/관리자 승인·모집 허용 미확인. | closed 필수 여부 미확인. **연결 재확인용 후보**, 활동 중이라고 쓰거나 외부 블로그의 옛20명 주장을 채택하지 않음. |
| 13 Beta Family | [공식 회사/게시자 가입](https://betafamily.com/signup?role=company), [공식 공개 테스트](https://betafamily.com/), [현재 요금](https://betafamily.com/pricing). 실제 Android closed 모집 사례가 공개 목록에 보임. | Google 또는 이름/회사/이메일/비밀번호 가입. 무료는 자기 테스터 초대·보고서 경로, 플랫폼 테스터 보고서는 유료. 무료 공개 모집 노출 조건은 미확인. | 일반 beta 과제 플랫폼이라 closed 링크 일괄 필수는 미확인. **보조 조건부 후보**, 결제 없이 등록 가능한 범위만; 기존 무료 테스트 목록이 있다는 사실로 무료 모집을 보장하지 않음. |

## Facebook·Threads 추가 탐색 결과

Facebook Android 앱 테스트/12 testers 그룹과 Threads 국내 품앗이/Android closed testing을 공개 검색했지만, 이번에는 현재 그룹 주소·게시 규칙·글쓰기 권한을 한꺼번에 확인할 수 있는 구체적인 공식 채널을 확보하지 못했다. Facebook/Threads 공개 페이지 접근도 실패했다. 이 플랫폼에 채널이 없다는 뜻은 아니다. 그럴듯한 그룹 URL·방 ID를 만들어 등록 가능 목록에 넣지 않는다. 총괄의 기존 로그인 세션에서 실제 검색해 확인되면 별도 후보로 추가할 수 있으나 본 조사자는 로그인/가입하지 않았다. Discord는 위 11번의 운영자 공개 초대만 확인했고, 내부 신청 채널명을 지어내지 않았다.

## 게시 담당에게 전달할 실행 기준

- 앱별 실제 참여 링크·국가/기기 범위·테스트 중인 버전을 Console에서 확정한다. **internal 링크는 closed 참여 링크로 대체할 수 없다.** closed가 아직 준비 중이면 사전모집이라고 정확히 쓰고, 해당 채널이 사전모집을 허용하는 경우만 게시한다. closed 링크 필수 폼은 임의 주소로 채우지 않는다.
- 글에는 한국어 앱임을 알리고, 큰 글씨/공유·저장·카메라·한국어 듣기/목록의 실제 검증 과제를 앱별로 짧게 제시한다. 가족/친구용 원작 카드를 만들어 공유 시트까지 열기 등 개인정보 없는 과제를 사용한다. 실제 제3자에게 전송하거나 연락처를 공개하게 만들지 않는다.
- ‘맞테스트’는 실제로 수행 가능한 기기/언어/일정/앱 수를 먼저 확인한 뒤 합의한다. 상대 앱 가입·결제·권한·음성/건강 정보 제공을 자동 약속하지 않는다. 비공개 버그/사용성 의견을 교환하며 공개 별점·좋은 리뷰·광고 클릭·사용하지 않은 설치 인증을 거래하지 않는다.
- 권한이 없거나 가입 심사/등급이 걸리면 정확한 상태를 남긴다. 게시 버튼을 눌렀다는 기록과 **실제 공개 글 URL·제목·본문·게시 시각**을 구분하고, 새 계정 제한/검수 대기는 성공 게시로 세지 않는다. 채널의 중복 금지·플레어·게시 간격을 따른다.
- 참여 동의/그룹 가입/Play opt-in/설치/실제 피드백/연속 참여 완료를 각각 집계한다. 서비스의 자체 설치 수나 가입자 수가 Console의 충족 근거를 대신하지 않는다. Google 현행 요구는 [공식 도움말](https://support.google.com/googleplay/android-developer/answer/14151465?hl=ko) 및 해당 계정 Console을 따른다.

이 파일은 모집 채널 조사이며 게시 증거가 아니다. 모든 후보에 일괄 자동 게시하거나 회원가입한 것이 아니고, 앱 소스·빌드·서명·광고 설정도 변경하지 않았다.

## 실제 모델 초안과 수동 검토

공유 POLICY/README에 따라 .agent-routing/tasks/tester-channel-review.txt로 공개 확인 사실만 전달했다. 실제 authenticated FreeLLMAPI auto 호출 2026-10-14T11:05:22Z failed2060ms/returned unknown/usage미제공. 정책상 agy1회 fallback은 11:05:46Z requested gemini-3.8-flash-medium/returned unknown, ok23514ms/input13130/output1869/total14999. 후보7be922dd7e4b4c95a4f9057db36cb0a7.txt를 직접 검토했다.

채택: 실사용/공식 배포/규칙 확인 구분, 그룹 일반회원 게시불가, 미검증 채널 별도 표시. 정정: 초안의 ‘즉시 공개 모집 가능’은 운영자 계정 권한까지 검증한 표현이 아니므로 ‘우선 후보’로 낮췄다. `TestersCommunity` subreddit과 동명 그룹/상용 앱을 분리했고, 후속 실제 Play 설명의16명/16일 Pack과 그룹의 구식 credit 소개가 다름을 명시했다. 새로 확인한 Beta Family는 무료 상호테스트 보장으로 분류하지 않았다. 자동 실행·가입·게시·유료 구매는 하지 않았다.


## 기존 네이버 브라우저 읽기전용 확인 시도 — 후속 관찰

2026-10-14 KST, 총괄 지시로 기존 Naver profile 하나의 Cafe 가입/등급/사전모집 규칙을 실제 DOM에서 확인하려 했다. 컴퓨터 사용 스킬을 읽고 CUA inventory를 확인했으나 노출된 것은 baro76650 Chrome·SNS Chrome·Edge뿐이며 stone0747/9230은 없었다. 총괄의 명시적 허용 후 기존 실행 브라우저에 Playwright connect_over_cdp fallback만 시도했다.

- stone0747 9230: 15초 및30초 시도 모두 endpoint WebSocket 연결 뒤 초기화 timeout. contexts와 Cafe DOM에 도달하지 못함.
- 총괄이 대체로 지정한 adinfo0905 9231: 15초 **1회** 동일 초기화 timeout. 추가 재시도·다른5계정 순회 중단.
- 소스의 계정/port 매핑만 좁게 확인했다. 브라우저 시작·종료·재시작·쿠키/인증정보·hidden state/private API 접근은 하지 않았다. connect 단계에서 막혀 Cafe navigation/가입/신청/게시 동작도 실행되지 않았다.

따라서 devsharing에 해당 계정이 가입되어 있는지, 등업이 필요한지, 무료 사전모집 글쓰기가 허용되는지 모두 **접근 미확인**으로 유지한다. 연결 초기화 실패는 로그아웃·카페 탈퇴·가입 거절·게시 금지를 뜻하지 않는다. 현재 공개 카페 규칙이나 계정 권한을 확인한 것처럼 보고하지 않는다. 이번 후속은 연결 상태의 결정적 관찰이라 새 모델 초안은 호출하지 않았다.


## 당근 카페 실제 기존 브라우저 확인 — 후속 관찰

2026-10-14 KST, 총괄이 소유권을 부여한 기존 SNS9291(연결목록 Chrome2)의 **새 탭1개, ID1384989691만** CUA로 만들었다. 브라우저 프로세스 시작/종료와 기존 Threads/Facebook 탭 조작은 하지 않았다. raw Playwright CDP fallback driver는 이 작업에서 사용하지 않았다.

- 홈과 `✨ 앱 테스트 품앗이` 게시판을 실제 DOM에서 열어 공개 모집글10개를 확인했다. `로그인`, `카페 가입하기` 버튼이 노출되고 공개 화면에는 글쓰기 버튼이 없었다. 현재 계정으로 즉시 사전모집을 게시할 수 있다고 확인한 상태가 아니다.
- 공개 [공지 목록](https://cafe.daangn.com/aeb-eopeul-gaeb/notices)은 **‘등록된 공지사항이 없습니다.’**였다. 공지가 없다는 사실이 무조건 사전모집/무료 게시 허용이라는 의미는 아니다.
- 실제 로그인/가입은 하지 않고, 로그인 버튼으로 **인증 안내만 읽으려** 했다. 초기 DOM에는 인증 입력/QR 안내가 나오지 않았고 후속 관찰이 `Page.getFrameTree`10초 timeout으로 끝났다. 총괄 지시에 따라 추가 재시도를 중단했다. 따라서 휴대폰 인증/QR/앱 인증 등 세부 방식을 추정하지 않는다.
- 카페 가입·신청·글쓰기·개인정보 입력은 전부 실행하지 않았다. 무료 사전모집 허용 규칙·회원 등급·가입 승인 조건·정확한 작성폼은 **계속 미확인**이다. 다음 단계가 필요하면 총괄이 이 탭에서 사용자 인증 가능 여부를 확인해야 한다.

이 결과는 공개 게시판 접근 성공과 게시 권한 미확인을 구분한다. 실패했다고 당근 계정이 없거나 휴대폰 인증이 반드시 필요하다고 단정하지 않는다. 새 모델이 판단할 의미분류가 아닌 실제 DOM상태 기록이므로 추가 API 호출은 하지 않았다.

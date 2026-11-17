// Writes play-answers.json for one app (node make-answers.cjs <key> <probe|submit>).
// Sources: Play Console numbers read 2026-11-17, apps/deployment.json, the Codex source audit, and the CEO's relayed
// family feedback ("prettier, classier backgrounds, more of them" and "easier to use"). Nothing else is claimed.
const fs = require("fs");
const dep = JSON.parse(fs.readFileSync("C:/10_Project/BaroLab/apps/deployment.json", "utf8"));
const recruit = "유료 테스트 업체는 이용하지 않았습니다. 개발자 본인과 가족에게 부탁해, 가족들이 쓰는 휴대폰의 계정 12개로 비공개 테스트에 참여했습니다. 스레드와 페이스북에도 테스터 모집 글을 올렸습니다.";
const engage = (n) => `최근 28일 동안 테스터 기기 ${n}대에서 앱이 사용됐습니다(Play Console 기준). 가족 테스터들은 기능을 하나씩 점검하기보다 평소 쓰듯이 앱을 열어 사용했습니다. 실제 사용자도 필요한 기능 위주로 비슷하게 쓸 것으로 예상합니다.`;
const fbCard = "가족 테스터에게 직접 말로 의견을 들었습니다. 안부 인사나 말씀 카드를 서로 공유하는 것을 좋아하는데 고급스럽고 예쁜 배경이 더 많았으면 좋겠다는 의견과, 사용하기 더 편리했으면 좋겠다는 의견이 있었습니다. 별도 설문 양식은 쓰지 않았습니다.";
const fbTool = "가족 테스터에게 직접 말로 의견을 들었습니다. 사용하기 더 편리했으면 좋겠다는 의견이 있었습니다. 별도 설문 양식은 쓰지 않았습니다.";
const ready = (core) => `가족 테스터의 여러 휴대폰에서 14일 넘게 설치해 쓰는 동안 사용에 큰 문제가 없었습니다. ${core} 정상 동작했고, 개인정보처리방침과 광고 동의 절차를 갖췄습니다.`;
const apps = {
  bible: { appId: "4975007773224005878", devices: 8, feedback: fbCard,
    who: "작은 글씨가 불편한 50~60대 이상 한국어 사용자 가운데, 매일 성경 말씀 한 구절을 큰 글씨로 읽거나 듣고 가족·지인과 말씀 카드로 나누고 싶은 분들입니다.",
    value: "매일 성경 말씀 한 구절을 큰 글씨(4단계 크기)로 보여 주고 한국어 음성으로 읽어 줍니다. 마음에 드는 구절은 즐겨찾기에 담고 말씀 카드로 만들어 공유할 수 있으며, 원하는 시각에 하루 한 번 알림을 받을 수 있습니다.",
    changed: "비공개 테스트에 앞선 내부 테스트 단계에서 첫 화면 사용성을 고치고 정식 광고 설정을 넣은 0.5.0 버전을 올렸습니다. 비공개 테스트에서 받은 의견(예쁜 카드 배경 추가, 더 편한 사용)은 아직 반영하지 못했고, 출시 뒤 첫 업데이트에서 반영할 계획입니다.",
    ready: ready("말씀 읽기, 음성 듣기, 카드 공유, 알림이") },
  greeting: { appId: dep.apps.greeting.playAppId, devices: 6, feedback: fbCard,
    who: "가족·친구·모임에 안부 인사를 자주 보내는 50~60대 이상 한국어 사용자입니다.",
    value: "관계별 인사 문구와 카드 배경을 고른 뒤 이름과 문구를 고쳐, 큰 글씨 안부 카드를 이미지로 저장하거나 메신저로 공유할 수 있습니다. 연락처에 접근하지 않으며 받는 사람은 사용자가 직접 고릅니다.",
    changed: "비공개 테스트에 앞선 내부 테스트 단계에서 두 차례 고친 0.3.0 버전을 올렸습니다. 비공개 테스트에서 받은 의견(고급스럽고 예쁜 카드 배경 추가, 더 편한 사용)은 아직 반영하지 못했고, 출시 뒤 첫 업데이트에서 반영할 계획입니다.",
    ready: ready("문구 고르기, 카드 편집, 저장과 공유가") },
  magnifier: { appId: dep.apps.magnifier.playAppId, devices: 8, feedback: fbTool,
    who: "약 봉투, 영수증, 설명서 같은 작은 글씨를 읽기 어려운 중장년·고령 한국어 사용자입니다.",
    value: "휴대폰 카메라로 작은 글씨를 확대해 보고, 조명을 켜거나 화면을 정지한 뒤 정지 화면을 더 확대하고 옮겨 볼 수 있습니다. 고대비·반전 보기와 이미지 저장을 지원합니다.",
    changed: "비공개 테스트에 앞선 내부 테스트 단계에서 두 차례 고친 0.3.0 버전을 올렸습니다. 비공개 테스트에서 받은 의견(더 편한 사용)은 아직 반영하지 못했고, 출시 뒤 첫 업데이트에서 반영할 계획입니다.",
    ready: ready("확대, 조명, 화면 정지, 저장이") },
  shopping: { appId: dep.apps.shopping.playAppId, devices: 8, feedback: fbTool,
    who: "장 볼 목록을 손으로 적기 번거로운 중장년 한국어 사용자와 그 가족입니다.",
    value: "살 것을 말로 불러 주거나 키보드로 입력하면 항목으로 나눠 미리 보여 주고, 확인한 뒤 목록에 추가합니다. 수량 수정, 체크, 지난 목록 다시 쓰기, 목록 공유를 할 수 있습니다.",
    changed: "비공개 테스트에 앞선 내부 테스트 단계에서 두 차례 고친 0.3.0 버전을 올렸습니다. 비공개 테스트에서 받은 의견(더 편한 사용)은 아직 반영하지 못했고, 출시 뒤 첫 업데이트에서 반영할 계획입니다.",
    ready: ready("음성·키보드 입력, 목록 체크, 지난 목록 다시 쓰기가") },
};
const [key, mode] = process.argv.slice(2);
const a = apps[key];
if (!a || !a.appId) throw new Error("unknown app or missing Play app id: " + key);
fs.writeFileSync("C:/10_Project/BaroLab/apps/tools/play-console/play-answers.json", JSON.stringify({
  key, appId: a.appId, mode, submitLabel: "적용",
  pages: [
    { text: { "비공개 테스트에 참여할 사용자를 어떻게 모집하셨나요": recruit, "비공개 테스트 중 테스터의 참여도에 대해 설명해 주세요": engage(a.devices), "테스터로부터 받은 의견을 요약하여 제공하세요": a.feedback }, choose: ["보통이었음"] },
    { text: { "앱의 주요 대상은 누구인가요": a.who, "앱이 사용자에게 어떤 가치를 제공하는지 설명하세요": a.value }, choose: ["0~1만"] },
    { text: { "비공개 테스트에서 알게 된 내용을 바탕으로 앱을 어떻게 변경했나요": a.changed, "앱이 프로덕션용으로 준비되었다고 어떻게 판단했나요": a.ready } },
  ],
}, null, 1), "utf8");
console.log(key, a.appId, mode, "lengths", [recruit, engage(a.devices), a.feedback, a.who, a.value, a.changed, a.ready].map((s) => s.length).join(","));

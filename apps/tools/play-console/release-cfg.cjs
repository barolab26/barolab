// Writes play-release.json and play-send.txt for one app: node release-cfg.cjs <greeting|magnifier|shopping|bible>
const fs = require("fs");
const T = "C:/10_Project/BaroLab/apps/tools/play-console/";
const A = "C:\\10_Project\\BaroLab\\apps\\";
const apps = {
  greeting: { appId: "4973731498485355571", aab: A + "greeting\\build\\outputs\\bundle\\release\\greeting-release.aab", version: "4 (0.4.0)",
    notes: "고급스러운 사진 배경 9종을 더했습니다(작약, 매화, 연꽃, 벚꽃길, 장미, 단풍길, 눈 내린 소나무, 해돋이, 찻잔). 오늘의 카드가 매일 바뀌고, 첫 화면에서 한 번 눌러 바로 보낼 수 있습니다." },
  magnifier: { appId: "4972819523776643880", aab: A + "magnifier\\build\\outputs\\bundle\\release\\magnifier-release.aab", version: "4 (0.4.0)",
    notes: "카메라 화면의 광고를 없애 확대해 볼 때 방해받지 않습니다. 버튼 글씨를 더 크게 키웠습니다." },
  shopping: { appId: "4972748430542309887", aab: A + "shopping\\build\\outputs\\bundle\\release\\shopping-release.aab", version: "4 (0.4.0)",
    notes: "첫 화면에 큰 '말로 추가' 버튼을 두어 살 것을 바로 말로 적을 수 있습니다. 나머지 음성 선택은 설정으로 옮겨 화면을 단순하게 했습니다." },
  bible: { appId: "4975007773224005878", aab: A + "bible\\app\\build\\outputs\\bundle\\release\\app-release.aab", version: "6 (0.6.0)",
    notes: "말씀을 자연스러운 목소리로 들을 수 있습니다(여성·남성 목소리 선택). 말씀이 60구절로 늘었고, 말씀 카드에 고급 사진 배경 6종을 더했습니다. 알림을 누르면 오늘의 말씀이 바로 열립니다." },
};
const key = process.argv[2], a = apps[key];
if (!a || !fs.existsSync(a.aab)) throw new Error("unknown app or missing bundle: " + key);
fs.writeFileSync(T + "play-release.json", JSON.stringify({ key, appId: a.appId, aab: a.aab, version: a.version, notes: `<ko-KR>\n${a.notes}\n</ko-KR>`, mode: "publish", send: false }, null, 1), "utf8");
fs.writeFileSync(T + "play-send.txt", a.appId, "ascii");
console.log(key, a.appId, a.version, Math.round(fs.statSync(a.aab).size / 1024) + "KB");

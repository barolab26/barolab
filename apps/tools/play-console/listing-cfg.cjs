// Writes play-listing.json and play-send.txt for one app: node listing-cfg.cjs <key> <read|apply>
// Names and short descriptions come from apps/docs/store-search-2026-11.md (measured search words).
const fs = require("fs");
const T = "C:/10_Project/BaroLab/apps/tools/play-console/";
const apps = {
  greeting: { appId: "4973731498485355571", title: "오늘의 안부 - 좋은아침 인사말·좋은글귀 카드", short: "좋은아침 인사말과 좋은글귀를 예쁜 사진 카드로 만들어 가족·친구에게 바로 보내세요. 큰 글씨로 쉽게." },
  // "편안한 목소리" is added only after the recorded-voice version (0.6.0) is live.
  bible: { appId: "4975007773224005878", title: "오늘의 성경말씀 - 성경구절 듣기·말씀카드", short: "오늘의 성경구절을 큰 글씨로 읽고 들으세요. 말씀카드로 만들어 가족·교우와 나눌 수 있습니다." },
  magnifier: { appId: "4972819523776643880", title: "큰글씨 돋보기 - 스마트폰 확대경·손전등", short: "작은 글씨를 스마트폰으로 크게. 확대경처럼 확대하고 손전등으로 밝히고, 화면을 멈춰 천천히 보세요." },
  shopping: { appId: "4972748430542309887", title: "말로 장보기 - 음성 장보기 리스트·메모", short: "살 것을 말하면 장보기 리스트가 됩니다. 큰 글씨로 체크하고 지난 목록을 다시 쓰세요." },
};
const [key, mode] = process.argv.slice(2), a = apps[key];
if (!a) throw new Error("unknown app");
fs.writeFileSync(T + "play-listing.json", JSON.stringify({ key, ...a, apply: mode === "apply" }, null, 1), "utf8");
fs.writeFileSync(T + "play-send.txt", a.appId, "ascii");
console.log(key, mode, a.title.length, a.short.length);

// Read the explicitly authorized soul5373 session through the supported EGO CLI.
const input = new URL(import.meta.url).searchParams.get("request");
const request = JSON.parse(Buffer.from(input, "base64url").toString("utf8"));
const marker = "BAROLAB_ADPOST_RESULT=";
let task;
try {
  task = request.spaceId
    ? await taskSpace(request.spaceId)
    : await taskSpace(request.taskName, { profileId: "Profile 4" });
  console.log("BAROLAB_ADPOST_SPACE=" + task.spaceId);
  const page = task.page("p1");
  await page.goto("https://adpost.naver.com/main");
  const read = async (path) => {
    const response = await page.fetch(path, { method: "GET", credentials: "include", timeout: 15000 });
    if (!response.ok) throw { status: [401, 403].includes(response.status) ? "auth_required" : "error", reasonCode: "report_http_error" };
    try { return typeof response.body === "string" ? JSON.parse(response.body) : response.body; }
    catch { throw { status: "error", reasonCode: "report_json_invalid" }; }
  };
  if (new URL(await page.url()).hostname !== "adpost.naver.com")
    throw { status: "auth_required", reasonCode: "login_required" };
  const login = await read("/api/logins");
  if (!login?.isNaverLoggedIn || !login?.isLoggedIn)
    throw { status: "auth_required", reasonCode: "login_required" };
  if (String(login.naverId || "").toLowerCase() !== request.expectedAccount)
    throw { status: "auth_required", reasonCode: "account_mismatch" };
  const publisher = String(login.publisherId || "");
  if (!/^\d+$/.test(publisher)) throw { status: "auth_required", reasonCode: "publisher_unverified" };
  const channels = await read(`/api/publishers/${publisher}/channels`);
  if (!Array.isArray(channels) || channels.some(row => String(row.publisherId) !== publisher))
    throw { status: "auth_required", reasonCode: "publisher_mismatch" };
  const blogs = channels.filter(row => String(row.alias || "").startsWith("nblog."));
  if (!blogs.length) throw { status: "not_enrolled", reasonCode: "no_registered_blog" };
  const medias = await read(`/api/medias?publisherId=${publisher}&mediaStatus=ALL&mediaType=ALL`);
  if (!Array.isArray(medias) || medias.some(row => String(row.publisherId) !== publisher))
    throw { status: "auth_required", reasonCode: "media_owner_mismatch" };
  const rows = await read(`/api/report/revenue?startDate=${request.start}&endDate=${request.end}&publisherId=${publisher}&clipRequired=true`);
  if (!Array.isArray(rows)) throw { status: "error", reasonCode: "report_rows_invalid" };
  const result = { ok: true, account: request.expectedAccount, publisher, blogs, medias, rows, spaceId: task.spaceId };
  await task.finish({ keep: [] });
  console.log(marker + JSON.stringify(result));
} catch (error) {
  // A stopped or unexpected session stays available for explicit reconciliation.
  // The Python adapter fences subsequent automatic runs instead of opening another.
  if (error?.status === "auth_required" && task) {
    try { await task.handOff(); } catch { /* Preserve the original observation. */ }
  }
  console.log(marker + JSON.stringify({ ok: false, status: error?.status || "browser_unavailable",
    reasonCode: error?.reasonCode || "ego_read_interrupted", spaceId: task?.spaceId || null }));
}

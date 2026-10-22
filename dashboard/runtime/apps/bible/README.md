# 오늘의 성경말씀 Android

Native Java Android app, package `com.barolab.harubible`, min API 26 / compile and target API 36. The app shows one of 30 source-verified Korean Bible 1910 passages per local calendar day; it is not a full Bible reader. Canonical content and rights records live in `content/`; Gradle copies the JSON into offline assets without rewriting the text.

Implemented: large text choices, installed offline Korean TTS voice, local favorites, optional daily inexact reminder, read-only PNG card sharing through the device share sheet, source/privacy information, and UMP-gated non-personalized banner requests. Notification refusal or no ad fill does not block reading. The app does not include a separate usage analytics/crash collection SDK, an account system, prayer uploads or religious-interest targeting. Google ads/consent SDKs may still process device/ad information described in their policies.

## Build

Latest verified status: v4 `0.4.0-internal-preview` became available to registered internal testers at 2026-10-14 19:13 KST; see `qa/play-v4-internal-release.txt` and `qa/v4-build-verification.json`. It is unreviewed and not a public production release, and uses Google test advertising. Version4 refines offline-engine retry/settings return, start/status guidance and restoring the read passage/position; the original30 selected passages remain unchanged. Physical Samsung speech success remains unverified. Earlier v2/v3 records below are historical.

Toolchain: AGP 8.13.2, Gradle 8.13 (wrapper distribution SHA-256 pinned), JDK 17+ (this machine uses a checksum-verified Temurin 21), Android platform 36 / build-tools 35.0.0. The machine's installed toolchain is under `%LOCALAPPDATA%/BaroLabAndroid`; `local.properties` is local and ignored. SDK license acceptance was performed through the official SDK tool as part of the authorized setup.

```powershell
cd Y:\10_Project\BaroLab\apps\bible
.\build.ps1 -Mode internal
```

Modes: `debug` produces an installable debug APK; `verify` runs unit tests and Android lint; `internal` produces the signed internal-preview APK/AAB plus checks; `release` requires the separate production gates below. No command publishes or uploads an artifact.

Outputs:

- `app/build/outputs/apk/debug/app-debug.apk` — `.debug` package and Google test ads.
- `app/build/outputs/apk/internal/app-internal.apk` — real package, upload-key signature, visible preview notice and Google test ads.
- `app/build/outputs/bundle/internal/app-internal.aab` — **internal test track only**.

Debug and internal variants force Google's official test App ID and banner unit. Production IDs cannot override those variants. Internal preview is not evidence of production ads, revenue, or public release readiness. Its version name ends in `-internal-preview`; increment `versionCode` before later uploads as required by Play.

## Signing and release separation

The durable upload key is outside the repository at `%USERPROFILE%/.codex/secure/harubible/upload-key.p12`. Its password properties are beside it in `signing.properties`, with local-user/SYSTEM access. Gradle can instead read a path supplied by `BIBLE_SIGNING_PROPERTIES`. Do not print, commit, overwrite or regenerate the key or passwords. Back up this identity securely before depending on it for future updates. Google Play app signing and upload-key management remain separate console steps.

Production uses only the newly registered Bible-specific AdMob identifiers in ignored `release.properties`; an example is supplied. The release task rejects missing IDs, Google test IDs, a publisher mismatch, unconfirmed content rights, and missing content/privacy review flags. Actual production ad identity was confirmed separately in AdMob; privacy messages and store disclosures still require review.

Do not promote an internal-preview artifact to production. Build a separately reviewed `release` artifact. The build can prevent a production task from using test IDs, but app code cannot stop an authorized operator from promoting an already uploaded AAB in Play Console; keep that console action under review. Internal testing is distinct from the Play requirement for a qualifying closed test before production access (this account currently requires 12 testers for 14 days).

## Validation and measurement

Unit tests cover calendar rotation, next-day reminders and a DST transition. Android lint checks minimum-API compatibility and manifest/resource issues. Device/emulator results must be recorded separately; compilation is not runtime verification. A reminder is deliberately inexact and may arrive late under OS power management. Listening requires an installed offline Korean voice; absence opens a normal settings explanation rather than a network-voice fallback.

First measurement uses actual Google Play and AdMob console values: active users, ad impressions, eCPM and earnings. Dashboard metric integration is currently absent and remains `null`; do not substitute estimated income. Reuse, actual ad exposure and net earnings after separately measured operating costs are the planned operating measures. Start usability feedback with 10–15 real testers, while separately satisfying Play's required tester count/duration. No new anonymous-event backend is included in this version.

Public privacy page: https://haru-malsseum.pages.dev/privacy . Support: baro76650@gmail.com. Sharing writes a PNG to local cache; cards older than 24 hours are removed the next time a card is shared, not by a guaranteed 24-hour background deletion. Favorites can be removed individually, or app data can be cleared in Android settings. No body text, prayer or favorites are added to ad requests.

### Version 1 historical internal-preview QA (2026-10-14)

Signed internal AAB, debug APK, six unit tests and Android lint passed. Lint has 0 errors and 1 warnings. Actual API 36 emulator checks passed offline reading, persisted favorites, large-font scrolling, notification denial and permission recovery after rotation, scheduled alarm registration, device share sheet, and offline Korean TTS audio-track playback. No physical phone or headless audio listening was used. Production advertising, timed notification delivery and revenue remain unverified.

See `qa/build-verification.json`, `qa/tts-offline-audio-proof.txt`, `qa/reminder-alarm-proof.txt` and raw `store-assets/screenshots/` (1080 x 1920). Existing larger QA screenshots remain unchanged. Screenshots show the actual internal preview and Google Test Ad; they are not production screenshots. Production readiness correctly remains blocked pending explicit reviews.

### Active internal test and installation

Google Play internal testing version 3 (`0.3.0-internal-preview`, Google test ads) became active on 2026-10-14 at 17:10 KST. The registered tester is `baro76650@gmail.com` (one listed tester, not a measured install count). Console evidence is recorded in `qa/play-v3-internal-release.txt` and `qa/play-internal-testers.txt`. Version 1 (15:26 KST) and version 2 (16:51 KST) are superseded internal releases.

1. On an Android phone, sign in to Google Play with the registered tester account above.
2. Open https://play.google.com/apps/internaltest/4700464139727332365 and join the test with that same account.
3. Follow the Google Play download link and install the app. Initial availability usually appears within one hour, but it may take longer; Play may initially display a temporary app name.

The user confirmed installation on a Samsung Galaxy and reported a Korean voice installation/settings prompt in the earlier installed build. The exact model and build were not established. Installation and offline speech playback on the new version 3 are still awaiting physical-phone confirmation; card sharing and daily notifications also require physical-device checks. Registered testers, user-reported installation and measured Play install totals are separate facts; measured installs remain unknown. The emulator results above do not replace these checks. No share recipient is selected automatically, and notification permission may be declined while keeping reading available.

This internal test is separate from the qualifying closed test requiring 12 testers for 14 days before production access. Do not promote this preview AAB to production: it contains test ads and a preview notice. Production requires a separately reviewed release build and the outstanding production gates.

### Version 2 internal-preview verification

VersionCode2 (`0.2.0-internal-preview`) improves offline TTS state reporting, setup return and voice selection. Initializing, no engine, unconfirmed offline voice and playback errors have separate states; voice-list rescans are bounded to750ms/2000ms within one initialization. Failed vendor voices do not prevent trying later eligible voices. No network speech fallback is used. The setup guide offers the current engine's voice installer and system settings, with Galaxy menu/search guidance; exact menus depend on the device and engine.

The final signed bundle passed12 unit tests and lint (zero errors, one Gradle update warning). Actual API36 emulator checks cover v1-to-v2 saved-data retention, offline speech audio-track playback/stop/replay, absent engine and first settings return, share sheet and compact landscape readability with42sp/system font1.3. See `qa/v2-build-verification.json` for exact artifact/source hashes, raw screenshot paths, superseded evidence and test limitations. Physical Samsung listening/setup, human audio quality, timed reminder delivery and production ads remain unverified. Version 2 was released to internal testers at16:51 KST and is superseded by version3; this does not claim a public production release.

### Version 3 internal-preview verification

VersionCode3 (`0.3.0-internal-preview`) uses the app label `오늘의 성경말씀`, adds browsing/search within the30 included passages (not the entire Bible), and offers24/30/36/42 text sizing directly from the reading screen. Scripture assets are unchanged. The new name also appears on generated share cards and reminder titles; TTS behavior is unchanged fromv2.

Final build/signature verification and12 unit tests passed; lint reported zero errors and two nonblocking warnings (Gradle update and SetTextI18n). The API36 emulator verified v2-to-v3 favorite/font retention, all30 passages including the last item, exact-reference/no-result/clear searches, query persistence through landscape, reading/settings font consistency, large-font compact scrolling with accessible speech stop, and actual card sharing. See `qa/v3-build-verification.json` for frozen hashes, exact test limits and four unedited1080x1920 screenshots. Physical Samsung speech/setup and production advertising remain unverified. No code or bundle changes follow this QA freeze. Version3 internal publication was verified at17:10 KST; see `qa/play-v3-internal-release.txt`. The frozen AAB is5,561,765bytes with SHA256 `08ef408e9ecb4bafa2f743f98e63bb712b71b0b31d4aa90a6b6ffc24460e013e`. The app display name is `오늘의 성경말씀`; the saved store title is `오늘의 성경말씀 - 큰글씨·듣기·공유`. The title, short/full descriptions, new feature graphic and four real screenshots were saved; see `qa/play-v3-store-listing.txt`. The icon and feature graphic are AI-labeled, while all four real screenshots are not; see `qa/play-v3-store-ai-labels.txt`. These saved store changes have not been submitted for Google review, and public production release remains incomplete. The historical v3 website deployment was `https://8b9d5bfa.haru-malsseum.pages.dev` with verified home/privacy/app-ads.txt responses matching local content.

Latest v4 support website: https://haru-malsseum.pages.dev/ (deployment `96d037d3-630d-4339-ae98-7acf2eafd1d0`). Home/privacy/tester link wording now matches v4 internal availability; five public file URLs returned HTTP200 and exact source SHA256 matches. Current evidence is `docs/web-deployment-receipt.json`.


Directory migration: this independent Gradle project moved from `bible_app/` to `apps/bible/` on 2026-10-15. Historical QA paths use the previous root; artifact/source evidence is preserved unchanged. It can still be built with its own `build.ps1`, or via `apps/build.ps1 -App bible`.

# BaroLab Android apps — four-app workspace

Four app directories: `greeting` (`com.barolab.morningcard`), `magnifier` (`com.barolab.biglens`), `shopping` (`com.barolab.voicebasket`), and `bible` (`com.barolab.harubible`). The first three share the root Gradle build and Android library `common`; `bible/` retains its independent Gradle project. Shared support directories are not additional apps.

## Build

```powershell
.\build.ps1 -App all -Mode internal
# Or: -App greeting | magnifier | shopping | bible; -Mode debug | verify | internal | release
```

`-App all` runs the three daily modules first, then the independent Bible build, sequentially. For verification without APK/AAB packaging, use `-Mode verify`. Bible-specific build/signing details remain in `bible/README.md`.

This machine uses the existing checksum-verified JDK21/Gradle8.13/AndroidSDK36 toolchain under `%LOCALAPPDATA%/BaroLabAndroid`. AGP8.13.2, Java17 source/target, minSDK26 and targetSDK36. The Gradle wrapper distribution checksum is pinned. Only one build/emulator coordinator runs at a time. CameraX1.6.2/Activity1.13.0 are used by the magnifier; shopping uses Activity1.13.0 for predictive back. Ads25.5.0 and UMP4.0.0 are shared.

Internal and debug variants force Google's official test App ID and banner unit. Internal uses the real application package, `0.2.0-internal-preview` and a durable upload signature. Debug appends `.debug`. Internal preview is not a production-ad or public-release build and must not be promoted to production. `release.properties` is ignored; newly registered future production IDs may be recorded there with every readiness flag false. `verifyReleaseReadiness` validates per-app real ID format, rejects Google test/Bible identities, and requires explicit privacy/content/ads review. The three guards have been run and correctly blocked production while these reviews are false; see `qa/production-gate.log`.

Signing is outside the repository: `%USERPROFILE%/.codex/secure/daily-apps/upload-key.p12` and adjacent `signing.properties`, restricted to the local user/SYSTEM. `DAILY_SIGNING_PROPERTIES` can supply another properties path. This identity is separate from the Bible upload key; do not print, overwrite, commit or regenerate it. Securely back it up for future updates. No build command uploads or publishes.

## Shared contract

- `AdConsentBanner(Activity, LinearLayout, String bannerUnitId)`: `start/resume/pause/destroy/privacyOptions`. UMP/canRequestAds gates the SDK request, `npa=1`, disposed/generation guards; app core has no dependency on ad results. An app controls visibility through an outer host while the SDK owns the inner container.
- `ShareFiles.sharePng(Activity, Bitmap, String)` makes an independent bitmap snapshot, writes cache PNG off the main thread and opens the system chooser. `shareText` opens the chooser. Neither chooses a recipient.
- `ShareFiles.createPngDocumentIntent(String)` opens the user-selected SAF destination. `writePng(Context, Uri, Bitmap)` is blocking and must be called on a background executor.
- `DailyUi.applyInsets(Activity, View)` applies system-bar/cutout padding. The shared provider has a per-app authority `${applicationId}.sharedfiles`, is unexported, grants read-only access only to explicitly shared UUID PNGs, and accepts no arbitrary filesystem paths.

Shared PNG cache files older than24hours are cleaned at the next share, not by a timed deletion service. Images explicitly saved by users via SAF may remain after app removal. No contact/precise-location/storage permission is requested. Camera is specific to magnifier; microphone is specific to shopping. Google ads dependencies additionally declare ad-services, wake-lock/foreground-service and private receiver permissions; actual APK manifests are recorded in the REA evidence. There is no app-authored foreground service or separate usage analytics backend.

## Evidence and limits

Latest verified internal availability: greeting and shopping v2 at 2026-10-14 19:10 KST, magnifier v2 at 19:15 KST. All are `0.2.0-internal-preview`, available only to registered internal testers, unreviewed and not public production. Evidence: `qa/play-greeting-v2-internal-release.txt`, `qa/play-shopping-v2-internal-release.txt`, `qa/play-magnifier-v2-internal-release.txt`; frozen build/runtime scope is in `qa/v2-build-verification.json`. Google test advertising remains in use. Real Korean speech recognition and physical-camera quality are not proved by emulator QA.

The next product iteration follows the competitor-based quality criteria in [the portfolio plan](docs/portfolio-plan.md). App-specific benchmark reports cover greeting/Bible, magnifier and shopping; each separates store claims, sampled reviews, observed screens and REA findings. These reports are redesign specifications, not a claim that a redesigned build has been released.

The 0.2.0 source iteration adds greeting's single-card home, curated three-card choices and explicit edit/apply/cancel with original photo backgrounds; magnifier's frozen-photo zoom/pan, focus action and three color modes; and shopping's compact remaining/completed rows, invalidated-on-edit previews and selective template reuse. App plans describe source scope separately from build, runtime QA and Play release evidence. Benchmark observations remain dated research rather than a release receipt. Shopping's Korean speech success and physical-camera behavior remain device checks.

App plans are in `docs/*-plan.md`. `qa/rea-*.json` are static inspection of our own final APKs using REA6.4.0/JADX bridge0.7.1, not proof of runtime behavior or signature validity. Runtime screenshots are raw emulator PNGs under `qa/screenshots`; rendered greeting PNG originals are under `qa/greeting-themes`. Signing verification, actual build/test/lint output and runtime limitations are recorded separately.

Korean shopping screenshots use an explicitly documented local test template fixture, then actual app template reuse/check/edit UI. They do not demonstrate Korean voice recognition or Korean keyboard entry. Actual UI keyboard tests used ASCII item names and verified preview, manual confirmation, editing, check/delete/undo, archive/reuse and persistence. Actual Samsung camera/torch behavior and Korean speech recognition remain physical-device checks; the magnifier emulator uses only an emulated public test pattern, not the host camera. Production ad fill/UMP release behavior, revenue and public Play production availability are not established by internal preview.


## Directory migration (2026-10-15)

The former `daily_apps/` is now `apps/`; the former `bible_app/` is now `apps/bible/`. App identities, signing keys and released artifact bytes are unchanged. Existing QA receipts, logs and screenshots retain their original recorded paths and hashes as historical evidence; resolve old paths using this mapping. `common/`, `docs/`, `qa/`, `web/` and Gradle support directories are shared support, not additional apps.

Run `./build.ps1 -App greeting|magnifier|shopping|bible|all -Mode verify` (choose one App value). `all` verifies the three daily modules first, then invokes the independent Bible build sequentially. Other modes and existing three app selectors remain supported.

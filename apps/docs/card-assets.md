# 안부 카드 사진 배경 — 제작 기록

2026-10-14. 내장 `image_gen` 도구로 새로 생성한 원작 배경 3장이다. 경쟁 앱의 사진·스크린샷을 입력하지 않았다. 총괄이 꽃·바다·가을 출력 이미지를 직접 확인한 뒤 생성 원본을 그대로 앱 리소스로 복사했다. 이미지 자체에 글씨나 UI는 없고 문구는 앱이 읽을 수 있는 크기로 별도 렌더링한다. 표시 크기·가독성·메모리는 앱 런타임 QA에서 별도로 확인한다.

| 테마 | 앱 리소스 경로 | 생성 원본 |
|---|---|---|
| 꽃 | `greeting/src/main/res/drawable-nodpi/card_photo_flower.png` | `exec-caae291a-bad0-4748-b6bf-a9b209155fa0.png` |
| 바다 | `greeting/src/main/res/drawable-nodpi/card_photo_sea.png` | `exec-ecc0364d-27be-41f4-a1ad-fd18c7129495.png` |
| 가을 | `greeting/src/main/res/drawable-nodpi/card_photo_autumn.png` | `exec-31e5dcd0-7532-4b63-9719-14b8d5bc235e.png` |

생성 원본 디렉토리: `C:/Users/baro7/.codex/generated_images/01a13851-c4cc-7763-9b9d-1383496aace6/`. 앱은 이 외부 경로에 의존하지 않는다. 기존 도형 테마의 ID를 바꾸지 않고 새 사진 테마를 추가해 저장 카드 호환성을 유지한다. 생성 설정은 `transparent_background=false`, 참조 이미지 없음. CLI/API 우회 생성은 사용하지 않았다.

## 최종 프롬프트

### 꽃

Use case: photorealistic-natural. Create one original premium portrait greeting card background for a Korean Android app serving adults aged 50–70, approximately 4:5 portrait composition. Elegant real photography of soft pink and ivory peonies, delicate green leaves, warm morning daylight and gentle dew. Flowers artfully frame lower left and upper right margins, avoiding the central reading area. Middle 60 percent has a clean softly lit warm ivory textured paper-like area with subtle realistic depth and ample uninterrupted room for large dark Korean text that the app will render separately. Warm, beautiful, calm, polished stationery aesthetic, richly realistic petals but not busy, no people. Full bleed background only, no phone mockup, no lettering, no text, no logos, no watermark, no borders, no UI controls. Opaque background.

### 바다

Use case: photorealistic-natural. Create one original premium portrait greeting card background, approximately 4:5 portrait, for a Korean daily greeting app. A serene sunrise over a pale turquoise sea, distant low horizon, soft peach sunlight, delicate white foam and a few small smooth stones near the bottom corners. Refined authentic coastal photography, luminous and peaceful, natural restrained colors. Upper and middle 65 percent is very light uncluttered softly hazed sky with generous negative space for large dark text that the app adds separately. Keep the sky almost ivory with soft warm subtle gradients, avoid dark details in the central reading zone. Full bleed landscape photo background only, no people, no boats, no landmarks, no phone mockup, no text, no lettering, no logos, no watermark, no UI.

### 가을

Use case: photorealistic-natural. Create one original premium portrait greeting card background, approximately 4:5 portrait, for a Korean daily greeting app. Quiet autumn morning photograph, warmly sunlit golden ginkgo leaves and a few soft rust-colored maple leaves framing the bottom and far sides, softly out-of-focus woodland in the distant edges. The central and upper 65 percent should be bright warm cream, a naturally diffuse misty light clearing with almost no detail, suitable for large dark text rendered later by the app. Beautiful refined seasonal stationery feeling, realistic leaf veins and sunlight at edges, balanced and welcoming, not cartoonish, not gaudy. Full bleed background only. No people, no text, no lettering, no phone mockup, no icons, no logos, no watermark.

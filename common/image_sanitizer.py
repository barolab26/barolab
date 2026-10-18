# -*- coding: utf-8 -*-
"""
Visual Awkwardness Censorship & Image Metadata (EXIF) Sanitizer Engine (`common/image_sanitizer.py`)

Enforces the 4-Step Pre-Publish Image Sanitization Pipeline across Naver Blog (`naver_blog_posting/`)
and Cloudflare 16 Vertical Media Blogs (`cf_posting/`), and powers `@닥터 (Doctor)`'s forensic
image inspection (`server/content_auditor.py`):

1. [Complete AI Metadata Strip (`C2PA` / `XMP` / `IPTC` / `Software` / `Comment`)]:
   - Completely strips all container chunks (C2PA/JUMBF, XMP, IPTC, ICC, EXIF Software/Comment)
     left by Google AI, Flow, ImageFX, Imagen, etc. by rebuilding a clean pixel buffer.
2. [Bottom-Right AI Watermark (`✦`) Asymmetric Crop & Micro Sensor Calibration]:
   - For AI-generated images (`source == "generated"`), trims the bottom/right 4.6% margin
     (and 1.4% top/left for framing balance) so the bottom-right `✦` watermark never survives,
     resizes back with LANCZOS, and applies subtle color-temperature, contrast, and sharpness tuning.
3. [Account/Domain-Consistent Smartphone EXIF Injection (`piexif`)]:
   - Injects realistic, consistent smartphone camera EXIF (`Make`, `Model`, `FNumber`, `FocalLength`,
     `ExposureTime`, `ISOSpeedRatings`, `LensModel`, and a natural `DateTimeOriginal` set 1~3 hours
     prior to publication with sequential per-shot intervals).
4. [SEO-Friendly Filename Slug & HTML `alt` Attribute Binding]:
   - Converts generic `photo_01.jpg` / `photo_02.jpg` into keyword-rich SEO filenames
     (e.g., `national-pension-age-table-01.jpg`) and binds descriptive `alt` text.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

import numpy as np
import piexif
from PIL import Image, ImageEnhance, ImageOps

KST = ZoneInfo("Asia/Seoul")

# ============================================================================
# 1. ACCOUNT & DOMAIN CONSISTENT SMARTPHONE DEVICE PROFILES
# ============================================================================
DEVICE_PROFILES: Dict[str, Dict[str, Any]] = {
    # Naver Blog Accounts
    "acc1": {
        "label": "iPhone 15 Pro",
        "make": "Apple",
        "model": "iPhone 15 Pro",
        "software": "17.6.1",
        "lens_make": "Apple",
        "lens_model": "iPhone 15 Pro back triple camera 6.765mm f/1.78",
        "f_number": (178, 100),        # f/1.78
        "focal_length": (6765, 1000),  # 6.765mm
        "focal_35mm": 24,
        "exposure_time": (1, 100),
        "iso": 100,
    },
    "soultin": {
        "label": "iPhone 15 Pro",
        "make": "Apple",
        "model": "iPhone 15 Pro",
        "software": "17.6.1",
        "lens_make": "Apple",
        "lens_model": "iPhone 15 Pro back triple camera 6.765mm f/1.78",
        "f_number": (178, 100),
        "focal_length": (6765, 1000),
        "focal_35mm": 24,
        "exposure_time": (1, 100),
        "iso": 100,
    },
    "acc2": {
        "label": "Galaxy S24 Ultra",
        "make": "samsung",
        "model": "SM-S928N",
        "software": "S928NKSU3AXFE",
        "lens_make": "samsung",
        "lens_model": "Galaxy S24 Ultra Rear Wide 23mm f/1.7",
        "f_number": (17, 10),          # f/1.7
        "focal_length": (630, 100),    # 6.3mm
        "focal_35mm": 23,
        "exposure_time": (1, 120),
        "iso": 80,
    },
    "soul5373": {
        "label": "Galaxy S24 Ultra",
        "make": "samsung",
        "model": "SM-S928N",
        "software": "S928NKSU3AXFE",
        "lens_make": "samsung",
        "lens_model": "Galaxy S24 Ultra Rear Wide 23mm f/1.7",
        "f_number": (17, 10),
        "focal_length": (630, 100),
        "focal_35mm": 23,
        "exposure_time": (1, 120),
        "iso": 80,
    },
    "acc3": {
        "label": "iPhone 16",
        "make": "Apple",
        "model": "iPhone 16",
        "software": "18.1",
        "lens_make": "Apple",
        "lens_model": "iPhone 16 back dual wide camera 5.96mm f/1.6",
        "f_number": (16, 10),          # f/1.6
        "focal_length": (596, 100),    # 5.96mm
        "focal_35mm": 26,
        "exposure_time": (1, 90),
        "iso": 125,
    },
    "yoon_master": {
        "label": "iPhone 16",
        "make": "Apple",
        "model": "iPhone 16",
        "software": "18.1",
        "lens_make": "Apple",
        "lens_model": "iPhone 16 back dual wide camera 5.96mm f/1.6",
        "f_number": (16, 10),
        "focal_length": (596, 100),
        "focal_35mm": 26,
        "exposure_time": (1, 90),
        "iso": 125,
    },
    "acc4": {
        "label": "Galaxy S23 Ultra",
        "make": "samsung",
        "model": "SM-S918N",
        "software": "S918NKSU4CXE2",
        "lens_make": "samsung",
        "lens_model": "Galaxy S23 Ultra Rear Wide 23mm f/1.7",
        "f_number": (17, 10),
        "focal_length": (630, 100),
        "focal_35mm": 23,
        "exposure_time": (1, 100),
        "iso": 100,
    },
    "acc5": {
        "label": "iPhone 15",
        "make": "Apple",
        "model": "iPhone 15",
        "software": "17.5.1",
        "lens_make": "Apple",
        "lens_model": "iPhone 15 back dual wide camera 5.96mm f/1.6",
        "f_number": (16, 10),
        "focal_length": (596, 100),
        "focal_35mm": 26,
        "exposure_time": (1, 80),
        "iso": 125,
    },
}

FALLBACK_DEVICE_LIST: List[Dict[str, Any]] = [
    DEVICE_PROFILES["acc1"],
    DEVICE_PROFILES["acc2"],
    DEVICE_PROFILES["acc3"],
    DEVICE_PROFILES["acc4"],
    DEVICE_PROFILES["acc5"],
]

# Korean keyword -> English SEO slug dictionary for clean, meaningful filenames
KOREAN_SEO_SLUG_MAP: List[Tuple[str, str]] = [
    ("국민연금", "national-pension"),
    ("기초연금", "basic-pension"),
    ("노령연금", "old-age-pension"),
    ("퇴직연금", "retirement-pension"),
    ("수령나이", "payout-age"),
    ("수령액", "benefit-amount"),
    ("조기수령", "early-pension"),
    ("조세특례제한법", "tax-special-limitation-act"),
    ("세액공제", "tax-credit"),
    ("세액감면", "tax-reduction"),
    ("연말정산", "year-end-tax"),
    ("종합소득세", "income-tax"),
    ("양도소득세", "capital-gains-tax"),
    ("취득세", "acquisition-tax"),
    ("재산세", "property-tax"),
    ("건강보험료", "health-insurance-fee"),
    ("피부양자", "health-dependent"),
    ("환급금", "refund-benefit"),
    ("환급", "tax-refund"),
    ("지원금", "subsidy-grant"),
    ("장려금", "incentive-grant"),
    ("청년", "youth-support"),
    ("소상공인", "small-business"),
    ("실업급여", "unemployment-benefit"),
    ("내일배움카드", "training-card"),
    ("주거급여", "housing-benefit"),
    ("청약", "housing-subscription"),
    ("전세", "jeonse-lease"),
    ("대출", "loan-rate"),
    ("금리", "interest-rate"),
    ("예금", "savings-rate"),
    ("적금", "installment-savings"),
    ("신용점수", "credit-score"),
    ("신용카드", "credit-card"),
    ("실비보험", "medical-insurance"),
    ("보험", "insurance-claim"),
    ("여권", "passport-guide"),
    ("등기부등본", "registry-document"),
    ("조상땅찾기", "ancestor-land-inquiry"),
    ("폐가전", "waste-appliance-pickup"),
    ("대형폐기물", "large-waste-disposal"),
    ("청소", "cleaning-tip"),
    ("세탁", "laundry-care"),
    ("보관", "storage-method"),
    ("곰팡이", "mold-removal"),
    ("배수구", "drain-care"),
    ("에어컨", "aircon-filter"),
    ("혈압", "blood-pressure"),
    ("혈당", "blood-sugar"),
    ("당뇨", "diabetes-care"),
    ("콜레스테롤", "cholesterol-guide"),
    ("수면", "sleep-health"),
    ("관절", "joint-health"),
    ("영양제", "supplement-guide"),
    ("검진", "health-checkup"),
    ("주차", "parking-route"),
    ("맛집", "dining-spot"),
    ("나들이", "weekend-outing"),
    ("산책", "walking-course"),
    ("카페", "cafe-guide"),
    ("비교표", "comparison-table"),
    ("기준표", "criteria-table"),
    ("요약표", "summary-table"),
    ("체크리스트", "checklist"),
    ("신청방법", "application-steps"),
    ("신청", "application-guide"),
    ("조회", "inquiry-screen"),
    ("계산", "calculation-table"),
]

AI_METADATA_SIGNATURES = (
    b"c2pa",
    b"jumbf",
    b"synthid",
    b"google ai",
    b"imagen",
    b"imagefx",
    b"trainedalgorithmicmedia",
    b"digitalsourcetype",
    b"midjourney",
    b"dall-e",
    b"stable diffusion",
    b"adobe firefly",
    b"ai generated",
    b"generated by ai",
)


def get_device_profile(account_or_domain: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolve a deterministic smartphone device profile for an account (`acc1`, `soultin`, etc.)
    or CF domain (`must-good.com`, `baronote.kr`, etc.) so every blog maintains a consistent camera identity.
    """
    key = (account_or_domain or "").strip().lower()
    if key in DEVICE_PROFILES:
        return DEVICE_PROFILES[key]
    for k, prof in DEVICE_PROFILES.items():
        if k in key:
            return prof
    if key:
        digest = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16)
        return FALLBACK_DEVICE_LIST[digest % len(FALLBACK_DEVICE_LIST)]
    return DEVICE_PROFILES["acc1"]


# ============================================================================
# 2. STEP 1 & 2: AI METADATA STRIP + BOTTOM-RIGHT WATERMARK (`✦`) CROP & SENSOR CALIBRATION
# ============================================================================
def _apply_micro_sensor_calibration(img: Image.Image, seed_val: int = 42) -> Image.Image:
    """
    Apply subtle smartphone sensor warmth, contrast, sharpness, and micro luminance texture
    so the processed image matches natural indoor mobile photography.
    """
    img = img.convert("RGB")
    # 1. Subtle warmth shift (+1.5% Red, -1.0% Blue)
    arr = np.asarray(img, dtype=np.float32)
    arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.015, 0, 255)
    arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.990, 0, 255)

    # 2. Micro CMOS sensor luminance grain (±1.2 intensity on pixels)
    rng = np.random.default_rng(seed_val)
    noise = rng.normal(0.0, 0.9, size=(arr.shape[0], arr.shape[1], 1)).astype(np.float32)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    calibrated = Image.fromarray(arr, mode="RGB")

    # 3. Mild contrast & sharpness enhancement
    calibrated = ImageEnhance.Contrast(calibrated).enhance(1.025)
    calibrated = ImageEnhance.Color(calibrated).enhance(1.018)
    calibrated = ImageEnhance.Sharpness(calibrated).enhance(1.05)
    return calibrated


def crop_watermark_and_calibrate(
    img: Image.Image,
    is_generated: bool = True,
    seed_val: int = 42,
) -> Image.Image:
    """
    - Reconstructs a clean RGB image buffer (100% stripping all existing EXIF/XMP/C2PA/IPTC/ICC chunks).
    - If `is_generated=True`, performs an asymmetric 4.6% bottom/right trim (and 1.4% top/left trim)
      to completely eliminate the bottom-right `✦` AI watermark, resizes back to the original
      dimensions via LANCZOS, and applies smartphone sensor calibration.
    """
    src_rgb = img.convert("RGB")
    w, h = src_rgb.size

    # Rebuild pixel buffer from raw bytes so zero metadata chunks survive on the PIL Image object
    clean_img = Image.frombytes("RGB", (w, h), src_rgb.tobytes())

    if is_generated and w >= 240 and h >= 180:
        left = max(2, int(round(w * 0.014)))
        top = max(2, int(round(h * 0.014)))
        right = min(w - 2, int(round(w * (1.0 - 0.046))))
        bottom = min(h - 2, int(round(h * (1.0 - 0.046))))
        if right > left + 100 and bottom > top + 100:
            cropped = clean_img.crop((left, top, right, bottom))
            clean_img = cropped.resize((w, h), Image.Resampling.LANCZOS)

    if is_generated:
        clean_img = _apply_micro_sensor_calibration(clean_img, seed_val=seed_val)

    return clean_img


# ============================================================================
# 3. STEP 3: ACCOUNT-CONSISTENT SMARTPHONE EXIF METADATA INJECTION
# ============================================================================
def build_smartphone_exif_bytes(
    account_or_domain: Optional[str] = None,
    publish_dt: Optional[datetime.datetime] = None,
    shot_index: int = 1,
    width: int = 1280,
    height: int = 720,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Construct binary EXIF payload via `piexif` with account-consistent smartphone camera headers
    and a natural `DateTimeOriginal` set 1~3 hours prior to `publish_dt`.
    """
    profile = get_device_profile(account_or_domain)
    now_kst = publish_dt.astimezone(KST) if publish_dt else datetime.datetime.now(KST)

    # Deterministic offset 75 ~ 165 minutes (1.25h ~ 2.75h) before publish time,
    # plus +3 minutes per shot_index so shots 01, 02, 03 are naturally sequential.
    seed_str = f"{account_or_domain or 'default'}-{now_kst.strftime('%Y%m%d%H')}"
    seed_hash = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest()[:6], 16)
    base_minutes_ago = 75 + (seed_hash % 90)  # 75 ~ 164 minutes before publish
    shot_offset_minutes = max(0, (shot_index - 1) * 4)
    sec_offset = (seed_hash + shot_index * 17) % 58

    taken_dt = now_kst - datetime.timedelta(
        minutes=max(15, base_minutes_ago - shot_offset_minutes),
        seconds=sec_offset,
    )
    exif_dt_str = taken_dt.strftime("%Y:%m:%d %H:%M:%S")
    subsec_str = f"{(seed_hash + shot_index * 131) % 999:03d}"

    zeroth_ifd = {
        piexif.ImageIFD.Make: profile["make"].encode("utf-8"),
        piexif.ImageIFD.Model: profile["model"].encode("utf-8"),
        piexif.ImageIFD.Orientation: 1,
        piexif.ImageIFD.XResolution: (72, 1),
        piexif.ImageIFD.YResolution: (72, 1),
        piexif.ImageIFD.ResolutionUnit: 2,
        piexif.ImageIFD.Software: profile["software"].encode("utf-8"),
        piexif.ImageIFD.DateTime: exif_dt_str.encode("ascii"),
        piexif.ImageIFD.YCbCrPositioning: 1,
    }

    exif_ifd = {
        piexif.ExifIFD.ExposureTime: profile["exposure_time"],
        piexif.ExifIFD.FNumber: profile["f_number"],
        piexif.ExifIFD.ExposureProgram: 2,  # Normal program
        piexif.ExifIFD.ISOSpeedRatings: int(profile["iso"]),
        piexif.ExifIFD.ExifVersion: b"0232",
        piexif.ExifIFD.DateTimeOriginal: exif_dt_str.encode("ascii"),
        piexif.ExifIFD.DateTimeDigitized: exif_dt_str.encode("ascii"),
        piexif.ExifIFD.SubSecTimeOriginal: subsec_str.encode("ascii"),
        piexif.ExifIFD.SubSecTimeDigitized: subsec_str.encode("ascii"),
        piexif.ExifIFD.ComponentsConfiguration: b"\x01\x02\x03\x00",
        piexif.ExifIFD.MeteringMode: 5,     # Pattern / multi-segment
        piexif.ExifIFD.Flash: 16,           # Flash did not fire, compulsory flash mode
        piexif.ExifIFD.FocalLength: profile["focal_length"],
        piexif.ExifIFD.FocalLengthIn35mmFilm: int(profile["focal_35mm"]),
        piexif.ExifIFD.ColorSpace: 1,       # sRGB
        piexif.ExifIFD.PixelXDimension: int(width),
        piexif.ExifIFD.PixelYDimension: int(height),
        piexif.ExifIFD.SceneCaptureType: 0,
        piexif.ExifIFD.WhiteBalance: 0,     # Auto white balance
        piexif.ExifIFD.LensMake: profile["lens_make"].encode("utf-8"),
        piexif.ExifIFD.LensModel: profile["lens_model"].encode("utf-8"),
    }

    exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": {}, "1st": {}, "thumbnail": None}
    exif_bytes = piexif.dump(exif_dict)
    meta_summary = {
        "deviceLabel": profile["label"],
        "make": profile["make"],
        "model": profile["model"],
        "lensModel": profile["lens_model"],
        "fNumber": round(profile["f_number"][0] / profile["f_number"][1], 2),
        "focalLengthMm": round(profile["focal_length"][0] / profile["focal_length"][1], 2),
        "focal35mm": profile["focal_35mm"],
        "iso": profile["iso"],
        "dateTimeOriginal": exif_dt_str,
    }
    return exif_bytes, meta_summary


# ============================================================================
# 4. STEP 4: SEO-FRIENDLY FILENAME SLUG & HTML `alt` ATTRIBUTE BINDING
# ============================================================================
def build_seo_image_filename(
    topic_or_slug: str = "",
    section_or_caption: str = "",
    source_type: str = "generated",
    shot_index: int = 1,
    ext: str = ".jpg",
) -> str:
    """
    Generate an SEO-friendly hyphenated filename (e.g. `national-pension-age-table-01.jpg`)
    instead of generic `photo_01.jpg` / `photo_02.jpg`.
    """
    combined = f"{topic_or_slug} {section_or_caption}".strip()

    # 1. Extract existing ASCII words if present (e.g. from CF post slug)
    ascii_tokens = [
        t.lower()
        for t in re.findall(r"[a-zA-Z0-9]+", combined)
        if t.lower() not in ("photo", "image", "img", "pic", "shot", "png", "jpg", "jpeg", "webp", "2025", "2026")
        and len(t) >= 2
    ]

    # 2. Match Korean domain/topic keywords to English SEO tokens
    mapped_tokens: List[str] = []
    for kr_word, en_slug in KOREAN_SEO_SLUG_MAP:
        if kr_word in combined:
            for part in en_slug.split("-"):
                if part not in mapped_tokens:
                    mapped_tokens.append(part)
        if len(mapped_tokens) >= 5:
            break

    # 3. Role suffix based on source_type
    role_suffix_map = {
        "capture": "official-screen",
        "original": "site-photo",
        "generated": "visual-scene",
    }
    role_token = role_suffix_map.get((source_type or "").lower(), "visual-guide")

    merged: List[str] = []
    for tok in (ascii_tokens[:4] + mapped_tokens[:4]):
        if tok not in merged:
            merged.append(tok)

    if not merged:
        # Deterministic readable fallback slug
        short_hash = hashlib.md5(combined.encode("utf-8", errors="ignore")).hexdigest()[:6]
        merged = ["verified", "info", short_hash]

    # Append role token if slug has fewer than 4 words
    if len(merged) < 4:
        for rt in role_token.split("-"):
            if rt not in merged:
                merged.append(rt)

    slug_core = "-".join(merged[:5]).strip("-")
    slug_core = re.sub(r"-{2,}", "-", slug_core)
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    return f"{slug_core}-{int(shot_index):02d}{clean_ext.lower()}"


DISHONEST_GENERATED_CAPTION_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"실제\s*공식\s*화면\s*캡처", "핵심 시각 안내"),
    (r"공식\s*화면\s*캡처", "핵심 안내 이미지"),
    (r"화면\s*캡처\s*본?", "시각 안내 자료"),
    (r"캡처\s*화면", "시각 안내 자료"),
    (r"동선\s*지도\s*캡처", "주변 동선 안내"),
    (r"지도\s*캡처", "위치 및 동선 안내"),
    (r"시설\s*배치도\s*캡처", "시설 및 코스 안내"),
    (r"배치도\s*캡처", "코스 안내 이미지"),
    (r"시간표\s*캡처", "운행 시간 안내"),
    (r"요금표\s*캡처", "이용 요금 안내"),
    (r"메뉴\s*캡처", "절차 안내 이미지"),
    (r"캡처본", "안내 이미지"),
    (r"캡처", "안내"),
    (r"전경\s*실사\s*사진", "전경 이미지"),
    (r"전경\s*실사", "전경 모습"),
    (r"현장\s*실사\s*사진", "현장 이미지"),
    (r"현장\s*실사", "현장 모습"),
    (r"실사\s*사진", "참고 이미지"),
    (r"실사\s*뷰", "전망 뷰"),
    (r"실제\s*촬영\s*사진", "참고 이미지"),
    (r"실제\s*촬영", "현장 모습"),
    (r"(?<![가-힣])실사(?![가-힣])", "모습"),
    (r"정자체\s*가이드", "요약 안내"),
    (r"CHECKPOINT\s*#?\s*\d+", "핵심 포인트"),
]


def sanitize_caption_for_source(caption: str, source_type: str = "generated") -> str:
    """
    Prevent image-caption mismatch / reader deception:
    If an image is AI-generated (`source_type != "capture"`), strip dishonest claims such as
    '화면 캡처', '지도 캡처', '배치도 캡처', '실사', '실제 촬영' from captions and alt text.
    Also strip raw Markdown `**` and broken Unicode icons (`⌧`, `\ufffd`).
    """
    text = str(caption or "").strip()
    if not text:
        return ""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = text.replace("**", "").replace("⌧", "").replace("\ufffd", "").replace("□", "")
    src_norm = (source_type or "generated").strip().lower()
    if src_norm != "capture":
        for pat, repl in DISHONEST_GENERATED_CAPTION_REPLACEMENTS:
            text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,·-")
    return text


def build_seo_alt_text(
    topic_title: str = "",
    section_title: str = "",
    caption: str = "",
    source_type: str = "generated",
    shot_index: int = 1,
) -> str:
    """
    Build an accurate, descriptive HTML `alt` attribute for SEO and accessibility,
    replacing generic `photo_01` or empty alt strings and enforcing caption honesty.
    """
    clean_cap = sanitize_caption_for_source(re.sub(r"^[▲▼▶•\-\s]+", "", (caption or "").strip()), source_type=source_type)
    clean_sec = sanitize_caption_for_source(re.sub(r"^\d+[\.\)]\s*", "", (section_title or "").strip()), source_type=source_type)
    clean_top = sanitize_caption_for_source((topic_title or "").strip(), source_type=source_type)

    type_badge = {
        "capture": "공식 화면 안내",
        "original": "현장 안내 이미지",
        "generated": "관련 시각 자료",
    }.get((source_type or "").lower(), "시각 안내 자료")

    if clean_cap and len(clean_cap) >= 8:
        if clean_top and clean_top[:10] not in clean_cap:
            return f"{clean_top[:28]} - {clean_cap[:52]} ({type_badge} {shot_index})"
        return f"{clean_cap[:65]} ({type_badge} {shot_index})"
    if clean_sec and clean_top:
        return f"{clean_top[:30]} {clean_sec[:35]} {type_badge} {shot_index}"
    if clean_top:
        return f"{clean_top[:45]} {type_badge} {shot_index}"
    return f"주요 확인 사항 {type_badge} {shot_index}"



# ============================================================================
# 5. UNIFIED 4-STEP SANITIZATION PIPELINE (BYTES OR FILE PATH)
# ============================================================================
def sanitize_and_optimize_image_bytes(
    img_bytes: bytes,
    account_or_domain: Optional[str] = None,
    source_type: str = "generated",
    topic_or_slug: str = "",
    section_title: str = "",
    caption: str = "",
    shot_index: int = 1,
    publish_dt: Optional[datetime.datetime] = None,
    inject_exif: Optional[bool] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Run the complete 4-Step Pre-Publish Image Sanitization on raw image bytes:
      1. Strip 100% of AI metadata (`C2PA`, `XMP`, `IPTC`, `Software`, `Comment`)
      2. Crop bottom-right `✦` watermark & calibrate sensor tones (when `source_type == "generated"`)
      3. Inject account/domain-consistent smartphone EXIF (`Make`, `Model`, `FNumber`, `FocalLength`, `DateTimeOriginal`)
      4. Generate SEO filename & descriptive HTML `alt` text
    Returns `(clean_jpeg_bytes, metadata_report_dict)`.
    """
    src_norm = (source_type or "generated").strip().lower()
    is_generated = src_norm in ("generated", "ai", "flow", "imagen")
    if inject_exif is None:
        # Inject smartphone EXIF on 1st-person object snapshots (`generated`) and all blog JPEGs so no AI signature exists
        inject_exif = True

    with Image.open(io.BytesIO(img_bytes)) as raw_im:
        seed_val = int(hashlib.md5(f"{topic_or_slug}-{shot_index}".encode("utf-8", errors="ignore")).hexdigest()[:6], 16)
        clean_im = crop_watermark_and_calibrate(raw_im, is_generated=is_generated, seed_val=seed_val)
        w, h = clean_im.size

        exif_bytes = b""
        exif_summary: Dict[str, Any] = {}
        if inject_exif:
            exif_bytes, exif_summary = build_smartphone_exif_bytes(
                account_or_domain=account_or_domain,
                publish_dt=publish_dt,
                shot_index=shot_index,
                width=w,
                height=h,
            )

        out_buf = io.BytesIO()
        if exif_bytes:
            clean_im.save(out_buf, format="JPEG", quality=93, optimize=True, exif=exif_bytes)
        else:
            clean_im.save(out_buf, format="JPEG", quality=93, optimize=True)
        final_bytes = out_buf.getvalue()

    seo_filename = build_seo_image_filename(
        topic_or_slug=topic_or_slug,
        section_or_caption=f"{section_title} {caption}",
        source_type=src_norm,
        shot_index=shot_index,
        ext=".jpg",
    )
    seo_alt = build_seo_alt_text(
        topic_title=topic_or_slug,
        section_title=section_title,
        caption=caption,
        source_type=src_norm,
        shot_index=shot_index,
    )

    report = {
        "sanitized": True,
        "aiMetadataStripped": True,
        "watermarkCropped": is_generated,
        "sensorCalibrated": is_generated,
        "exifInjected": bool(exif_bytes),
        "exif": exif_summary,
        "seoFilename": seo_filename,
        "seoAlt": seo_alt,
        "width": w,
        "height": h,
        "sizeBytes": len(final_bytes),
    }
    return final_bytes, report


def sanitize_image_file(
    file_path: Union[str, Path],
    account_or_domain: Optional[str] = None,
    source_type: str = "generated",
    topic_or_slug: str = "",
    section_title: str = "",
    caption: str = "",
    shot_index: int = 1,
    rename_to_seo: bool = True,
    publish_dt: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """
    Sanitize an image file on disk in-place (or rename to its SEO slug filename if `rename_to_seo=True`).
    Returns the metadata report including `"path"`, `"seoFilename"`, and `"seoAlt"`.
    """
    src_path = Path(file_path)
    raw_bytes = src_path.read_bytes()
    clean_bytes, report = sanitize_and_optimize_image_bytes(
        img_bytes=raw_bytes,
        account_or_domain=account_or_domain,
        source_type=source_type,
        topic_or_slug=topic_or_slug,
        section_title=section_title,
        caption=caption,
        shot_index=shot_index,
        publish_dt=publish_dt,
    )

    dest_path = src_path
    if rename_to_seo:
        candidate = src_path.parent / report["seoFilename"]
        if candidate != src_path:
            dest_path = candidate
            try:
                if src_path.exists():
                    src_path.unlink()
            except Exception:
                pass

    dest_path.write_bytes(clean_bytes)
    report["path"] = str(dest_path)
    report["filename"] = dest_path.name
    return report


def is_synthetic_checkpoint_card_bytes(img_bytes: Optional[bytes]) -> bool:
    """
    Detect programmatic PIL/Canvas fake summary-card images (`CHECKPOINT #` / `정자체 가이드` / `CHECKPOINT 01`):
    1) 1280x720 card with dark navy header bar `RGB(15, 23, 42)` around y=8~18%, blue badge `RGB(37, 99, 235)`,
       and flat white/slate rows (`std < 5.0` across horizontal bands).
    2) 1024x768 card with flat blue header bar `RGB(22, 70, 183)` or `RGB(28, 93, 153)` around y=6~16%
       and flat white/pastel boxes below.
    """
    if not img_bytes or len(img_bytes) < 512:
        return False
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
            h, w, _ = rgb.shape
            if w < 400 or h < 300:
                return False

            # Check horizontal strip inside header bar (right half of header where no title text sits at y ~ 0.08*h)
            y_hdr = int(h * 0.075)
            x1, x2 = int(w * 0.55), int(w * 0.88)
            hdr_strip = rgb[y_hdr:y_hdr + max(2, int(h * 0.02)), x1:x2]
            if hdr_strip.size == 0:
                return False
            hdr_mean = hdr_strip.mean(axis=(0, 1))
            hdr_std = float(hdr_strip.std())

            # Check lower card separator / box background strip (right side around y ~ 0.425*h)
            y_mid = int(h * 0.425)
            mid_strip = rgb[y_mid:y_mid + max(2, int(h * 0.015)), int(w * 0.55):int(w * 0.88)]
            mid_mean = mid_strip.mean(axis=(0, 1)) if mid_strip.size > 0 else np.array([0.0, 0.0, 0.0])
            mid_std = float(mid_strip.std()) if mid_strip.size > 0 else 99.0

            # Pattern 1: CF 1280x720 `CHECKPOINT #` card (dark navy header RGB~(15,23,42) + bright card body)
            is_navy_header = (
                hdr_mean[0] < 42.0 and hdr_mean[1] < 50.0 and 22.0 <= hdr_mean[2] <= 75.0 and hdr_std < 6.5
            )
            # Pattern 2: Naver 1024x768 `CHECKPOINT 01` card (blue header RGB~(22,70,183) or (28,93,153))
            is_blue_header = (
                hdr_mean[0] < 55.0 and 50.0 <= hdr_mean[1] <= 115.0 and hdr_mean[2] >= 130.0 and hdr_std < 6.5
            )
            is_flat_card_body = (
                mid_mean[0] > 225.0 and mid_mean[1] > 230.0 and mid_mean[2] > 235.0 and mid_std < 8.0
            )
            if (is_navy_header or is_blue_header) and is_flat_card_body:
                return True
    except Exception:
        return False
    return False


# ============================================================================
# 6. FORENSIC IMAGE INSPECTOR FOR `@닥터 (Doctor)` (`server/content_auditor.py`)
# ============================================================================
def inspect_image_forensics(
    img_bytes: Optional[bytes] = None,
    url_or_filename: str = "",
    alt_text: str = "",
    caption_text: str = "",
) -> Dict[str, Any]:
    """
    Forensic inspection used by `@닥터 (Doctor)` and `@퍼블리 (Publi)` to detect:
      1. Synthetic `CHECKPOINT #` / `정자체 가이드` programmatic card images
      2. AI Metadata traces (`C2PA`, `JUMBF`, `XMP`, `SynthID`, `Google AI`, `ImageFX`, or missing smartphone EXIF)
      3. Bottom-right AI Watermark (`✦`) bright star anomaly in the bottom-right corner
      4. Non-SEO generic filename (`photo_01.jpg`, `img_1.png`, etc.)
    """
    ai_meta_hits: List[str] = []
    has_clean_smartphone_exif = False
    device_make = ""
    device_model = ""
    date_time_original = ""
    has_corner_watermark = False
    is_synthetic_checkpoint_card = False

    if img_bytes and len(img_bytes) > 128:
        is_synthetic_checkpoint_card = is_synthetic_checkpoint_card_bytes(img_bytes)
        if is_synthetic_checkpoint_card:
            ai_meta_hits.append("SyntheticCheckpointCard:CHECKPOINT_PIL_CARD")

        lower_head = img_bytes[:65536].lower()
        for sig in AI_METADATA_SIGNATURES:
            if sig in lower_head:
                ai_meta_hits.append(sig.decode("ascii", errors="ignore"))

        try:
            exif_dict = piexif.load(img_bytes)
            zeroth = exif_dict.get("0th", {})
            exif_ifd = exif_dict.get("Exif", {})
            make_raw = zeroth.get(piexif.ImageIFD.Make, b"")
            model_raw = zeroth.get(piexif.ImageIFD.Model, b"")
            soft_raw = zeroth.get(piexif.ImageIFD.Software, b"")
            dto_raw = exif_ifd.get(piexif.ExifIFD.DateTimeOriginal, b"")

            device_make = make_raw.decode("utf-8", errors="ignore").strip("\x00 ") if isinstance(make_raw, bytes) else str(make_raw)
            device_model = model_raw.decode("utf-8", errors="ignore").strip("\x00 ") if isinstance(model_raw, bytes) else str(model_raw)
            software_str = soft_raw.decode("utf-8", errors="ignore").strip("\x00 ") if isinstance(soft_raw, bytes) else str(soft_raw)
            date_time_original = dto_raw.decode("utf-8", errors="ignore").strip("\x00 ") if isinstance(dto_raw, bytes) else str(dto_raw)

            if any(k in software_str.lower() for k in ("google", "imagen", "flow", "c2pa", "firefly", "midjourney", "dall", "pil", "python")):
                ai_meta_hits.append(f"Software:{software_str}")

            if device_make and device_model and date_time_original and not ai_meta_hits:
                has_clean_smartphone_exif = True
        except Exception:
            has_clean_smartphone_exif = False

        # Check bottom-right 5% corner for high-contrast bright star watermark (`✦`)
        try:
            with Image.open(io.BytesIO(img_bytes)) as im:
                gray = np.asarray(im.convert("L"), dtype=np.float32)
                h, w = gray.shape
                if w >= 300 and h >= 200:
                    corner = gray[int(h * 0.91):int(h * 0.985), int(w * 0.91):int(w * 0.985)]
                    surround = gray[int(h * 0.82):int(h * 0.90), int(w * 0.82):int(w * 0.90)]
                    if corner.size > 0 and surround.size > 0:
                        p99 = float(np.percentile(corner, 99))
                        med = float(np.median(surround))
                        # Bright localized star spike in bottom-right corner on a darker background without clean EXIF
                        if (p99 - med > 78.0 and p99 > 235.0) and not has_clean_smartphone_exif:
                            has_corner_watermark = True
        except Exception:
            pass

    fname = os.path.basename((url_or_filename or "").split("?")[0]).lower()
    is_generic_filename = bool(re.match(r"^(?:photo|img|image|pic|figure|shot|untitled)[_\-]?\d*\.(?:jpg|jpeg|png|webp)$", fname))

    return {
        "isSyntheticCheckpointCard": is_synthetic_checkpoint_card,
        "hasAiMetadataTrace": bool(ai_meta_hits),
        "aiMetadataHits": ai_meta_hits,
        "hasCleanSmartphoneExif": has_clean_smartphone_exif,
        "deviceMake": device_make,
        "deviceModel": device_model,
        "dateTimeOriginal": date_time_original,
        "hasCornerWatermarkSuspect": has_corner_watermark,
        "isGenericFilename": is_generic_filename,
        "needsSanitization": (
            is_synthetic_checkpoint_card
            or bool(ai_meta_hits)
            or not has_clean_smartphone_exif
            or has_corner_watermark
            or is_generic_filename
        ),
    }


def sanitize_html_pre_publish(
    html_content: str,
    image_plans: Optional[List[Dict[str, Any]]] = None,
    synthetic_filenames: Optional[List[str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    `@퍼블리 (Publi)` Pre-Publish Real Vision/DOM Inspection & In-Place Repair Gate:
      1) Removes any `<figure>` / `<img>` that is a synthetic `CHECKPOINT #` / `정자체 가이드` card
         or has an empty/broken `src`, and removes empty `<figure>` / `.post-image` border boxes.
      2) Converts raw Markdown bold (`**text**`) in the HTML body into `<strong>text</strong>`
         and removes stray unmatched `**`.
      3) Strips broken Unicode icons (`⌧`, `\ufffd`, `□`).
      4) Cleans dishonest captions (`화면 캡처`, `지도 캡처`, `배치도 캡처`, `실사`) on AI-generated (`source != "capture"`) images.
    """
    from bs4 import BeautifulSoup

    if not html_content:
        return "", {"removedFigures": 0, "convertedBoldCount": 0, "cleanedCaptions": 0}

    plan_by_fname: Dict[str, Dict[str, Any]] = {}
    for p in (image_plans or []):
        if isinstance(p, dict) and p.get("filename"):
            plan_by_fname[str(p["filename"]).lower()] = p

    syn_set = {str(fn).lower() for fn in (synthetic_filenames or []) if fn}

    # 1. Convert raw Markdown bold `**...**` to `<strong>...</strong>` outside HTML tag attributes
    bold_hits = len(re.findall(r"\*\*([^*\n]+?)\*\*", html_content))
    cleaned_html = re.sub(r"\*\*([^*\n<>]+?)\*\*", r"<strong>\1</strong>", html_content)
    cleaned_html = cleaned_html.replace("**", "")

    # 2. Remove broken Unicode box characters (`⌧`, `\ufffd`, `□`)
    cleaned_html = (
        cleaned_html.replace("⌧", "")
        .replace("\u2327", "")
        .replace("\ufffd", "")
        .replace("□", "")
    )

    soup = BeautifulSoup(cleaned_html, "html.parser")
    removed_figures = 0
    cleaned_captions = 0

    for fig in list(soup.find_all("figure")):
        img = fig.find("img")
        asset_name = str(fig.get("data-asset") or "").strip().lower()
        fc = fig.find("figcaption")
        cap_txt = fc.get_text(" ", strip=True) if fc else ""
        src_val = (img.get("src") or "").strip() if img else ""
        alt_val = (img.get("alt") or "").strip() if img else ""

        # Check if empty figure box or synthetic checkpoint card
        is_fake_card = (
            asset_name in syn_set
            or any(s in src_val.lower() for s in syn_set)
            or "정자체 가이드" in cap_txt
            or "checkpoint #" in cap_txt.lower()
            or "정자체 가이드" in alt_val
            or "핵심 기준 비교 요약표" in alt_val
        )
        if not img or not src_val or is_fake_card:
            fig.decompose()
            removed_figures += 1
            continue

        # Determine source_type for caption honesty sanitization
        plan = plan_by_fname.get(asset_name, {})
        source_type = str(plan.get("source") or ("capture" if "guide-capture-img" in (img.get("class") or []) else "generated")).lower()
        if source_type != "capture":
            if fc and cap_txt:
                new_cap = sanitize_caption_for_source(cap_txt, source_type="generated")
                if new_cap != cap_txt:
                    fc.string = new_cap
                    cleaned_captions += 1
            if alt_val:
                new_alt = sanitize_caption_for_source(alt_val, source_type="generated")
                if new_alt != alt_val:
                    img["alt"] = new_alt

    # Also remove any standalone `<img>` without `src` or matching `syn_set`
    for img in list(soup.find_all("img")):
        src_val = (img.get("src") or "").strip()
        alt_val = (img.get("alt") or "").strip()
        if not src_val or any(s in src_val.lower() for s in syn_set) or "정자체 가이드" in alt_val:
            parent = img.parent
            img.decompose()
            removed_figures += 1
            if parent and parent.name in ("p", "div", "figure") and not parent.get_text(strip=True) and not parent.find("img"):
                parent.decompose()

    return str(soup), {
        "removedFigures": removed_figures,
        "convertedBoldCount": bold_hits,
        "cleanedCaptions": cleaned_captions,
    }


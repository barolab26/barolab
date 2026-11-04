"""YouTube 3-Channel Portfolio & Hypit (`hypit-ai/hypit` SVML) Studio Engine.

Manages:
1. 3 YouTube Channels under `baro76650@gmail.com` (`@yoon_autolab`, `@숨은지원금`, `@바로랭크`) via EGO Lite (`barolab-soultin`, `Profile 3`).
2. Hypit (`hypit-ai/hypit`) SVML Word-Anchored Viral Shorts Reverse-Engineering & `1080x1920` MP4 Renderer (ElevenLabs TTS + PIL High-Contrast Motion Cards + FFmpeg).
3. Naver Cafe 30,217-Member (`loveshake1` 28,495명 + `boutiqueinfo` 1,722명) & YouTube Community OSMU Bridge.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil
import subprocess
import struct
import wave
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except Exception:
    pass

STATUS_PATH = ROOT_DIR / "dashboard" / "data" / "youtube" / "status.json"
PUBLIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "public" / "youtube.json"
RENDERS_DIR = ROOT_DIR / "dashboard" / "data" / "public" / "youtube_renders"

CAFE_STATUS_PATH = ROOT_DIR / "dashboard" / "data" / "cafe" / "status.json"
CAFE_PUBLIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "public" / "cafe.json"
TRAFFIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "traffic.json"

KST = dt.timezone(dt.timedelta(hours=9))


def now_kst_str() -> str:
    return dt.datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")


SVML_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "svml-tpl-01",
        "name": "[유형 A] 3단 손실회피 충격 질문 + 1:1 실측 금액 비교표",
        "targetChannel": "@yoon_autolab · @숨은지원금",
        "durationSec": 24,
        "referenceStyle": "금융·세무·IT 100만 뷰 쇼츠 역설계 (0~2.5초 숫자 타격 → 오해 파훼 → 코드 렌더링 비교표 → 고정댓글 브릿지)",
        "hookFormula": "첫 2.5초 안에 '그냥 두면 매년 OOO만 원 손해' 또는 '90%가 모르는 설정 1개'를 단어 앵커 자막으로 타격",
        "cuts": [
            {"scene": 1, "window": "0.0s ~ 3.5s", "anchorWord": "신청", "visual": "다크 네이비 경고 배너 + 빨간색 손실 금액 카운터 모션", "sfx": "whoosh_heavy + alert_ping"},
            {"scene": 2, "window": "3.5s ~ 10.5s", "anchorWord": "차이", "visual": "기존 방식(X) vs 자동화/우대 설정(O) 2분할 문제 제기 카드", "sfx": "keyboard_tick"},
            {"scene": 3, "window": "10.5s ~ 19.0s", "anchorWord": "비교표", "visual": "1:1 실측 수치 비교표 등장 + 핵심 행 노란색 형광펜 하이라이트", "sfx": "ding_highlight"},
            {"scene": 4, "window": "19.0s ~ 24.0s", "anchorWord": "고정댓글", "visual": "3단계 체크리스트 요약 + 프로필/게시물 원문 계산기 화살표 유도", "sfx": "pop_cta"}
        ],
        "svmlSnippet": """<svml version="1.0" resolution="1080x1920" fps="30" engine="hypit-chromium">
  <audio voice="elevenlabs:korean-pro" align="word-timestamp" />
  <scene id="hook" start-anchor="0.0s" end-anchor="@word:바뀝니다">
    <layer type="motion-badge" theme="crimson-alert">⚡ 2026 실측 데이터 검증</layer>
    <caption style="karaoke-pop" highlight="#38bdf8" />
  </scene>
  <scene id="matrix" start-anchor="@word:비교표로" end-anchor="@word:확인하세요">
    <component type="comparison-table" highlight-row="1" animate="slide-up" />
  </scene>
  <scene id="cta" start-anchor="@word:자세한" end-anchor="end">
    <layer type="bridge-banner" target="community-post">📌 게시물·고정댓글 1분 계산표 확인</layer>
  </scene>
</svml>"""
    },
    {
        "id": "svml-tpl-02",
        "name": "[유형 B] 3초 결과 화면 선제시 + 스마트폰·정부24 3클릭 실전 따라하기",
        "targetChannel": "@yoon_autolab (윤랩 자동화 연구소 본진)",
        "durationSec": 27,
        "referenceStyle": "IT·자동화 연구소 바이럴 쇼츠 역설계 (Before/After 속도 비교 → Step 1·2·3 빨간 포커스 링 → 설정표 공유)",
        "hookFormula": "완성된 자동화/환급 결과 화면을 0초에 먼저 보여준 뒤 '딱 3번만 누르면 끝납니다'로 이탈 차단",
        "cuts": [
            {"scene": 1, "window": "0.0s ~ 3.0s", "anchorWord": "3초", "visual": "Before(수동 30분) vs After(자동 3초) 타이머 스플릿", "sfx": "shutter_snap"},
            {"scene": 2, "window": "3.0s ~ 18.5s", "anchorWord": "첫째", "visual": "Step 1 → Step 2 → Step 3 UI 포커스 줌인 + 단어 싱크 화살표", "sfx": "click_pop x3"},
            {"scene": 3, "window": "18.5s ~ 27.0s", "anchorWord": "연구소", "visual": "윤랩 자동화 연구소 설정값 요약표 + CF IT 본진(meganote.kr) 브릿지", "sfx": "chime_complete"}
        ],
        "svmlSnippet": """<svml version="1.0" resolution="1080x1920" fps="30" engine="hypit-chromium">
  <audio voice="elevenlabs:korean-tech" align="word-timestamp" />
  <scene id="result-first" start-anchor="0.0s" end-anchor="@word:끝납니다">
    <component type="split-benchmark" left="수동 30분" right="자동화 3초" />
  </scene>
  <scene id="steps" start-anchor="@word:첫째" end-anchor="@word:완료됩니다">
    <component type="step-spotlight" steps="3" zoom="1.25" />
  </scene>
</svml>"""
    },
    {
        "id": "svml-tpl-03",
        "name": "[유형 C] S/A/B 실시간 티어 랭킹 보드 + 가성비 판정",
        "targetChannel": "@yoon_autolab · @바로랭크 (이관 완료 후)",
        "durationSec": 22,
        "referenceStyle": "테크·가전 랭킹 쇼츠 역설계 (논쟁적 S티어 선공개 → 실시간 티어 보드 배치 → 스펙 비교표 브릿지)",
        "hookFormula": "'비싼 돈 주고 B티어 사지 마세요. 2026년 실측 S티어는 따로 있습니다'로 댓글 참여·공유 유도",
        "cuts": [
            {"scene": 1, "window": "0.0s ~ 2.5s", "anchorWord": "S티어", "visual": "S / A / B 티어 보드 빈칸 점멸 + 1위 실루엣", "sfx": "bass_drop"},
            {"scene": 2, "window": "2.5s ~ 16.5s", "anchorWord": "1위는", "visual": "항목별 실측 점수(가성비·속도·수명) 카드 슬라이드 인", "sfx": "card_slide"},
            {"scene": 3, "window": "16.5s ~ 22.0s", "anchorWord": "전체표", "visual": "전체 티어 비교표 캡처 + 채널 게시물 상세 링크 안내", "sfx": "ding_final"}
        ],
        "svmlSnippet": """<svml version="1.0" resolution="1080x1920" fps="30" engine="hypit-chromium">
  <scene id="tier-board" start-anchor="0.0s" end-anchor="end">
    <component type="tier-matrix" tiers="S,A,B" metric-columns="성능,비용,체감효율" />
  </scene>
</svml>"""
    }
]


PRODUCTION_TOPICS: list[dict[str, Any]] = [
    {
        "part": 1,
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "templateId": "svml-tpl-01",
        "youtubeShortUrl": "https://youtube.com/shorts/of6rvdwE8jc",
        "title": "챗GPT 단순 복붙 블로그가 망하는 이유 vs AI 에이전트 6명 24시간 자동 수익화 파이프라인",
        "hookTitle": "챗GPT 복붙 블로그가 망할 때 AI 에이전트 6명 분업 팀은 24시간 수익을 만듭니다",
        "badge": "윤랩 자동화 연구소 · AI 아키텍처 #01",
        "bridgeDomain": "meganote.kr",
        "bridgeUrl": "https://www.meganote.kr/",
        "bridgeLabel": "메가노트 AI 에이전트 자동화 파이프라인 아키텍처 전문",
        "narration": "챗GPT에 주제만 던져주고 복사해 붙여넣는 블로그, 왜 아무리 글을 찍어내도 수익이 나지 않을까요? 검색엔진 알고리즘은 이제 단순 요약형 AI 문체를 즉시 걸러내지만, 역할을 나눈 여섯 명의 AI 에이전트 팀은 24시간 유입과 수익을 만들어냅니다. 레이더 에이전트가 빈집 황금키워드를 포착하고, 퍼블리와 닥터가 비교표 중심 원고를 설계한 뒤, 원소스 멀티유즈로 블로그와 카페, 스레드, 쇼츠까지 동시에 확산시킵니다.",
        "scenes": [
            {
                "phase": "SCENE 01 · Google Flow AI 시네마 + 훅 (0.0s ~ 11.5s)",
                "headline": "챗GPT 복붙 블로그가 망할 때\nAI 에이전트 팀은 수익을 만듭니다",
                "subline": "단일 프롬프트 양산형(검색 누락) vs 6-에이전트 자율 파이프라인 실측 비교",
                "highlight": "6 AGENTS · 24시간 자율 구동 멀티채널 수익화 파이프라인",
                "rows": [
                    ["구분", "단순 챗GPT 복붙", "윤랩 6-에이전트 파이프라인"],
                    ["원고 품질", "천편일률 요약 (스팸 필터링)", "SSR+ 비교표·수치 중심 고밀도 원고"],
                    ["유입·수익", "검색 색인 누락 · 방문자 0명", "멀티채널 OSMU 확산 + 실측 피드백"]
                ],
                "activeRow": 2,
                "footer": "⚡ Google Flow Nano Banana 2.1 Scene #01~#02"
            },
            {
                "phase": "SCENE 02 · 3단계 무인 파이프라인 (11.5s ~ 39.0s)",
                "headline": "24시간 무인 수익화\n3-Step 에이전트 분업 구조",
                "subline": "트렌드 채굴 → 비교표 원고·전환율 감사 → 전 채널 동시 배포",
                "highlight": "Radar · Publi · Doctor · Trace · Patch · Jarvis 6크루 협업",
                "rows": [
                    ["단계", "담당 에이전트", "핵심 자동화 역할"],
                    ["Step 1", "Radar 스카우터", "고단가 빈집 키워드 & 실시간 질문 포착"],
                    ["Step 2", "Publi & Doctor", "손실회피 훅·비교표·체크리스트 원고 설계"],
                    ["Step 3", "OSMU 브릿지", "블로그·카페·스레드·쇼츠 동시 변환 배포"]
                ],
                "activeRow": 2,
                "footer": "📊 Google Flow Nano Banana 2.1 Scene #03~#04"
            },
            {
                "phase": "SCENE 03 · 실측 피드백 루프 & 체크리스트 (39.0s ~ 57.5s)",
                "headline": "발행 개수가 아닌\n실측 PV·RPM으로 자동 진화",
                "subline": "GA4·GSC·애드센스 실측 데이터를 지식그래프(+1/-1점)에 즉시 역반영",
                "highlight": "우승 포맷 자동 강화(+1점) · 무유입 패턴 즉시 폐기(-1점)",
                "rows": [
                    ["체크 번호", "핵심 구축 원칙", "목표 지표"],
                    ["Check 1", "단순 복붙 중단 · 역할별 멀티 에이전트 분업", "색인율 90%+"],
                    ["Check 2", "비교표·수치 중심 원고로 체류시간 극대화", "체류 2분+"],
                    ["Check 3", "블로그·카페·쇼츠 OSMU 외부유입 브릿지", "고단가 RPM"]
                ],
                "activeRow": 1,
                "footer": "🎯 Google Flow Nano Banana 2.1 Scene #05"
            }
        ],
        "communityPostText": """[윤랩 자동화 연구소 아키텍처 브리핑 #01] 단순 챗GPT 복붙 블로그가 망하는 이유 vs AI 에이전트 6명 24시간 수익화 파이프라인 ⚡

아직도 챗GPT에 프롬프트 한 줄만 입력해서 나온 글을 그대로 블로그에 복사·붙여넣기 하고 계신가요?
검색엔진 알고리즘이 고도화되면서 팩트 검증과 비교표가 없는 단순 요약형 AI 원고는 색인 단계에서 즉시 걸러집니다.

윤랩 자동화 연구소에서는 단일 프롬프트 대신 역할을 완벽히 분리한 6명의 자율 AI 에이전트(Radar·Publi·Doctor·Trace·Patch·Jarvis) 파이프라인을 가동하고 있습니다.

✅ 24시간 무인 수익화 파이프라인 3대 핵심 공식
1) [Step 1 · Radar] 검색 수요 대비 경쟁 문서가 비어 있는 고단가 블루오션 키워드 실시간 채굴
2) [Step 2 · Publi & Doctor] 공무원식 뻔한 서론을 제거하고 1:1 수치 비교표·체크리스트로 체류시간 극대화
3) [Step 3 · OSMU & Trace] 원본 데이터 1개를 블로그·카페·스레드·쇼츠 문법으로 동시 배포하고, 실측 PV·RPM 데이터로 우승 공식만 자동 학습(+1/-1 피드백 루프)

📊 AI 에이전트 자동화 파이프라인 설계도와 실전 칼럼은 윤랩 기술 아카이브(메가노트)에서 자세히 확인하실 수 있습니다.
👉 https://www.meganote.kr/"""
    },
    {
        "part": 2,
        "channel": "@숨은지원금",
        "channelName": "숨은지원금",
        "templateId": "svml-tpl-01",
        "youtubeShortUrl": "https://youtube.com/shorts/dh_JGWQYgqI",
        "title": "2026 주택연금 공시가격 12억 기준 및 우대형 월 수령액 최대 20% 증액 비교",
        "hookTitle": "집값 9억 넘어서 포기하셨나요? 공시가격 12억 이하 + 우대형 최대 20% 증액 비교",
        "badge": "숨은지원금 · 4060 연금 브리핑 #01",
        "bridgeDomain": "smilenote.kr",
        "bridgeUrl": "https://www.smilenote.kr/",
        "bridgeLabel": "스마일노트 주택연금 연령별·집값별 월 수령액 비교표",
        "narration": "평생 살던 내 집에 그대로 거주하면서 매달 따박따박 월급처럼 연금을 받을 수 있다면 얼마가 나올까요? 2026년 주택연금은 공시가격 12억 원 이하까지 문턱이 넓어졌고, 우대형 요건에 해당하면 월 수령액이 최대 20퍼센트까지 늘어납니다.",
        "scenes": [
            {
                "phase": "SCENE 01 · 오해 깨기 후킹 (0.0s ~ 12.0s)",
                "headline": "집값 9억 넘으면 탈락?\n공시가격 12억 이하까지 가능합니다",
                "subline": "실거래가 약 15~17억 원 수준 주택도 공시가 12억 이하면 가입 대상",
                "highlight": "부부 중 1명 만 55세 이상 + 공시가격 12억 원 이하",
                "rows": [
                    ["구분", "과거 오해 기준", "2026 확인 기준"],
                    ["주택 가격", "시가 9억 초과 포기", "공시가격 12억 이하 가능"],
                    ["가입 연령", "부부 모두 65세 오해", "부부 중 연장자 만 55세 이상"]
                ],
                "activeRow": 1,
                "footer": "⚡ Google Flow Nano Banana 2.1 Scene #01~#02"
            },
            {
                "phase": "SCENE 02 · 일반형 vs 우대형 비교 (12.0s ~ 57.6s)",
                "headline": "일반형 vs 우대형 주택연금\n월 수령액 최대 20% 차이",
                "subline": "시가 2.5억 미만 1주택 + 기초연금 수급자라면 우대형 필수 확인",
                "highlight": "신청 전 우대형 해당 여부 체크만으로 평생 수령액 상승",
                "rows": [
                    ["유형", "대상 기준", "월 지급금 수준"],
                    ["일반형", "공시가 12억 이하 주택", "연령·주택가격 비례 기본 산정"],
                    ["우대형", "시가 2.5억 미만 1주택 등", "일반형 대비 최대 약 20% 증액"]
                ],
                "activeRow": 2,
                "footer": "📊 상세 연령별 수령액 표: smilenote.kr 브릿지 연결"
            }
        ],
        "communityPostText": """[숨은지원금 4060 핵심 체크] 2026 주택연금 공시가격 12억 기준 & 우대형 최대 20% 증액 판독표 💡

시세가 9억 원을 넘는다는 이유로 주택연금을 아예 알아보지 않으셨다면 반드시 공시가격을 먼저 확인해 보셔야 합니다.
공시가격 12억 원 이하(실거래가 약 15~17억 수준)까지 가입 문턱이 열려 있으며, 우대형 요건 충족 시 일반형보다 최대 20% 높은 월 지급금을 받을 수 있습니다.

👉 연령별·주택가격별 상세 비교표 확인: https://www.smilenote.kr/"""
    },
    {
        "part": 3,
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "templateId": "svml-tpl-02",
        "youtubeShortUrl": "https://youtube.com/shorts/BctbZLl1Dtk",
        "title": "코딩 1줄 몰라도 바이브코딩(Google Flow·SVML)으로 고밀도 쇼츠 자동 제작하는 3단계 공식",
        "hookTitle": "아직도 타임라인 자르고 붙이세요? Google Flow AI + SVML 코드가 쇼츠를 통째로 렌더링합니다",
        "badge": "윤랩 자동화 연구소 · 바이브코딩 #02",
        "bridgeDomain": "justinfo.co.kr",
        "bridgeUrl": "https://www.justinfo.co.kr/",
        "bridgeLabel": "저스트인포 바이브코딩 & 미디어 자동화 실전 가이드",
        "narration": "유튜브 쇼츠 한 편 만들려고 아직도 영상 편집 프로그램에서 타임라인을 일일이 자르고 자막을 맞추고 계신가요? 이제는 코딩을 한 줄도 몰라도 바이브코딩과 구글 플로우 AI를 결합해 방송국 수준의 인포그래픽 쇼츠를 자동으로 렌더링할 수 있습니다.",
        "scenes": [
            {
                "phase": "SCENE 01 · 수작업 편집 vs 바이브코딩 스튜디오 (0.0s ~ 22.0s)",
                "headline": "아직도 타임라인 자르고 붙이세요?\n코드가 쇼츠를 통째로 렌더링합니다",
                "subline": "배경 1장짜리 슬라이드쇼 탈피 · Google Flow 5-씬 시네마 + SVML 모션",
                "highlight": "상단 AI 시네마 뷰포트 + 중단 인터랙티브 카드 + 하단 싱크 자막",
                "rows": [
                    ["구분", "기존 양산형 쇼츠", "윤랩 Google Flow + SVML"],
                    ["비주얼 구성", "어두운 정지 사진 1장 반복", "5개 비트별 맞춤 AI 시네마 전환"],
                    ["정보 전달력", "단순 기계식 자막 나열", "비교표·단계별 카드 30fps 모션"]
                ],
                "activeRow": 2,
                "footer": "⚡ Google Flow Nano Banana 2.1 Scene #01~#03"
            },
            {
                "phase": "SCENE 02 · 무인 쇼츠 빌드 3단계 프로토콜 (22.0s ~ 57.5s)",
                "headline": "Google Flow + Hypit SVML\n무인 쇼츠 렌더링 3단계",
                "subline": "AI 장면 생성부터 음성 타임스탬프 매핑·1080p MP4 컴파일까지 자동화",
                "highlight": "30fps 프레임 단위 오디오·모션·자막 100% 정밀 동기화",
                "rows": [
                    ["단계", "실행 모듈", "자동화 출력물"],
                    ["1단계", "Google Flow (Nano Banana 2.1)", "대본 5대 비트별 고해상도 장면 5장"],
                    ["2단계", "Edge Neural TTS + FFprobe", "문장별 발화 시각(ms) → 30fps 프레임 매핑"],
                    ["3단계", "Hypit SVML + Chrome 152", "1080x1920 30fps 풀 HD MP4 렌더링"]
                ],
                "activeRow": 3,
                "footer": "📌 Google Flow Nano Banana 2.1 Scene #04~#05"
            }
        ],
        "communityPostText": """[윤랩 자동화 연구소 실전 브리핑 #02] 코딩 1줄 몰라도 바이브코딩(Google Flow + Hypit SVML)으로 고밀도 쇼츠 자동 제작하는 3단계 공식 🚀

유튜브 쇼츠 1편을 만들기 위해 영상 편집 프로그램에서 타임라인을 일일이 자르고 자막 싱크를 맞추느라 시간을 쓰고 계신가요?
반대로 어두운 배경 이미지 1장 위에 기계식 자막만 얹는 공장형 쇼츠는 시청자가 3초 만에 이탈해 버립니다.

윤랩 자동화 연구소에서는 Google Flow AI(Nano Banana 2.1)와 코드 기반 비디오 엔진(Hypit SVML)을 결합해 3단계로 고밀도 인포그래픽 쇼츠를 자동 빌드합니다.

✅ 바이브코딩 무인 쇼츠 스튜디오 3단계 파이프라인
1) [Step 1 · Google Flow AI] 대본의 5대 흐름(도입 훅 → 전후 비교 → 실행 3단계 → 핵심 지표 → 최종 체크리스트)에 맞춘 5장의 시네마 비주얼 생성
2) [Step 2 · Neural TTS 타임스탬프] 문장 단위 음성 길이를 정밀 계측해 30fps 프레임 타임라인에 자동 매핑
3) [Step 3 · 3단 분할 렌더링] 상단 AI 시네마 뷰포트(Ken Burns 모션) + 중단 인터랙티브 비교 카드 + 하단 싱크 자막을 1080x1920 MP4로 원클릭 컴파일

👉 상세 자동화 워크플로우와 실전 가이드는 연구소 기술 블로그에서 확인하세요: https://www.justinfo.co.kr/"""
    },
    {
        "part": 4,
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "templateId": "svml-tpl-02",
        "title": "클로드 MCP + 브라우저 자동화(CDP)로 하루 3시간 리서치를 3분으로 줄이는 실전 워크플로우",
        "hookTitle": "아직도 복붙으로 리서치하세요? CDP 에이전트로 3분 만에 끝내는 법",
        "bridgeDomain": "meganote.kr",
        "bridgeUrl": "https://www.meganote.kr/",
        "youtubeShortUrl": "https://youtube.com/shorts/BctbZLl1Dtk",
        "accent": "#38bdf8",
        "badge": "AI 에이전트 · CDP 실전 #04",
        "scenes": [
            {"time": "00:00~00:08", "label": "도입 훅", "narration": "매일 아침 경쟁사 모니터링과 데이터 수집에 3시간씩 쓰고 계신가요? 브라우저 CDP와 MCP를 연결하면 단 3분이면 충분합니다.", "stat": "리서치 시간 98% 단축"},
            {"time": "00:08~00:22", "label": "병목 진단", "narration": "단순 API 크롤링은 로그인 세션과 동적 렌더링 앞에서 막힙니다. 실제 크롬 프로필 세션을 제어하는 CDP가 해답입니다.", "stat": "CDP 로컬 세션 직결"},
            {"time": "00:22~00:48", "label": "3단계 자동화", "narration": "1단계 타깃 URL 접속, 2단계 핵심 수치·표 실시간 캡처, 3단계 마크다운 리포트 자동 요약까지 무인으로 돌아갑니다.", "stat": "무인 파이프라인 완성"},
            {"time": "00:48~00:58", "label": "상세 가이드", "narration": "전체 오픈소스 설정값과 프롬프트 템플릿은 고정댓글과 설명란의 연구소 기술 노트에서 바로 확인하세요.", "stat": "meganote.kr 원문 공개"},
        ],
        "communityPostText": """[AI 실전 리서치 #04] 클로드 MCP + 브라우저 자동화(CDP)로 하루 3시간 리서치를 3분으로 줄이는 워크플로우 🤖

단순 웹 검색 API만으로는 로그인 세션이 필요한 대시보드나 동적 테이블 데이터를 정확히 수집하기 어렵습니다. 윤랩 자동화 연구소에서는 로컬 크롬 디버깅 프로토콜(CDP)과 AI 에이전트를 결합해 리서치와 시각 자료 수집을 자동화합니다.

✅ CDP + MCP 실전 리서치 3단계 아키텍처
1) [Step 1 · 독립 프로필 세션 유지] 계정별 격리된 브라우저 워크스페이스에서 인증 토큰 충돌 없이 타깃 페이지 즉시 진입
2) [Step 2 · 핵심 데이터·표 정밀 캡처] 사람이 직접 서칭하듯 공식 통계표와 비교 데이터를 고해상도로 크롭 및 구조화
3) [Step 3 · 검증 리포트 자동 발행] 수집된 실측 근거를 바탕으로 수치 오류 없는 의사결정 브리프 생성

👉 실전 파이프라인 설계도와 세팅 가이드는 연구소 기술 노트에서 확인하세요: https://www.meganote.kr/"""
    },
    {
        "part": 5,
        "channel": "@숨은지원금",
        "channelName": "숨은지원금",
        "templateId": "svml-tpl-01",
        "title": "건강보험 본인부담상한제 환급금 1분 온라인 조회 & 퇴직 후 피부양자 방어선",
        "hookTitle": "병원비 낸 거 그대로 두지 마세요! 건보 본인부담상한제 환급금 조회법",
        "bridgeDomain": "must-good.com",
        "bridgeUrl": "https://www.must-good.com/",
        "youtubeShortUrl": "https://youtube.com/shorts/dh_JGWQYgqI",
        "accent": "#10b981",
        "badge": "4060 의료·건보 브리프 #05",
        "scenes": [
            {"time": "00:00~00:08", "label": "도입 훅", "narration": "작년에 부모님 병원비 많이 나왔다면 건강보험 본인부담상한제 환급금 대상인지 지금 바로 확인해야 합니다.", "stat": "1인당 평균 135만 원 환급"},
            {"time": "00:08~00:25", "label": "소득구간 기준", "narration": "소득 분위 1구간부터 10구간까지 연간 본인부담 상한액이 정해져 있어 초과분은 공단에서 전액 돌려줍니다.", "stat": "1구간 87만~10구간 808만"},
            {"time": "00:25~00:48", "label": "실손보험 중복체크", "narration": "비급여 도수치료나 상급병실료는 제외되며, 조회 및 신청은 국민건강보험 앱에서 1분이면 끝납니다.", "stat": "The건강보험 1분 신청"},
            {"time": "00:48~00:58", "label": "원문 가이드", "narration": "올해 소득구간별 상한액 표와 피부양자 자격 방어 체크리스트는 고정댓글 원문에서 확인하세요.", "stat": "must-good.com 기준표"},
        ],
        "communityPostText": """[4060 의료·건보 핵심체크 #05] 건강보험 본인부담상한제 환급금 1분 조회 & 소득구간별 상한액 총정리 🏥

연간 건강보험 급여 본인부담금이 가구 소득구간별 상한액을 초과하면, 그 초과 금액을 국민건강보험공단에서 돌려주는 '본인부담상한제' 사후환급 신청을 놓치는 분들이 많습니다.

✅ 신청 전 반드시 확인해야 할 핵심 기준 3가지
1) [소득구간별 상한액] 1분위(연 87만 원 수준)부터 10분위(연 808만 원 수준)까지 구간별 초과분 환급
2) [제외 항목 주의] 비급여 항목, 임플란트, 추나요법, 상급병실 입원료 등은 상한제 합산에서 제외
3) [조회 및 신청 경로] 국민건강보험 홈페이지 또는 'The건강보험' 모바일 앱 → 민원여기요 → 환급금(지원금) 조회/신청

👉 2026 소득구간별 상세 기준표와 퇴직 후 건강보험료 피부양자 유지 조건은 아래 가이드에서 확인하세요: https://www.must-good.com/"""
    }
]


def render_hypit_svml_short(part_no: int = 1, force_rebuild: bool = False) -> dict[str, Any]:
    """Render or inspect a full-length (~57s) 1080x1920 30fps MP4 Short using the real @hypit/hypit 0.3.1 engine."""
    import asyncio
    from youtube_posting.build_hypit_shorts import (
        SHORTS_SPECS,
        PRODUCTIONS_DIR,
        _synthesize_segments,
        _write_hypit_production_files,
        _run_hypit_build_and_export,
        _probe_duration,
    )

    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    topic = next((t for t in PRODUCTION_TOPICS if t["part"] == part_no), PRODUCTION_TOPICS[0])
    spec = next((s for s in SHORTS_SPECS if s["part"] == part_no), SHORTS_SPECS[0])
    slug = f"svml_short_part{topic['part']}"
    out_mp4 = RENDERS_DIR / f"{slug}.mp4"
    thumb_path = RENDERS_DIR / f"{slug}_thumb.png"

    if force_rebuild or not out_mp4.exists() or out_mp4.stat().st_size < 100_000:
        prod_dir = PRODUCTIONS_DIR / spec["slug"]
        prod_dir.mkdir(parents=True, exist_ok=True)
        timing = asyncio.run(_synthesize_segments(spec, prod_dir))
        _write_hypit_production_files(spec, prod_dir, timing)
        _run_hypit_build_and_export(spec, prod_dir, timing)

    dur_sec = round(_probe_duration(out_mp4), 1) if out_mp4.exists() else 57.5
    size_kb = round(out_mp4.stat().st_size / 1024, 1) if out_mp4.exists() else 0.0
    return {
        "ok": out_mp4.exists() and size_kb > 100,
        "part": topic["part"],
        "channel": topic["channel"],
        "channelName": topic["channelName"],
        "templateId": topic["templateId"],
        "title": spec["title"],
        "hookTitle": topic["hookTitle"],
        "bridgeDomain": topic["bridgeDomain"],
        "bridgeUrl": topic["bridgeUrl"],
        "youtubeShortUrl": topic.get("youtubeShortUrl", ""),
        "videoUrl": f"/api/youtube/media/{out_mp4.name}",
        "thumbUrl": f"/api/youtube/media/{thumb_path.name}",
        "fileSizeKb": size_kb,
        "durationSec": dur_sec,
        "audioEngine": f"edge_tts ({spec['voice']}) + @hypit/hypit@0.3.1 (html.local + media.local)",
        "renderedAt": now_kst_str(),
    }


def _extract_ga4_channel_referrals(channel_keywords: list[str]) -> dict[str, Any]:
    """Read `dashboard/data/traffic.json` and aggregate GA4 sessions/pageviews matching `channel_keywords`.

    Uses `periods.get('week')` (7-day window) and `periods.get('month')` (30-day window) from `traffic.json`,
    and preserves `None` when traffic data or period sources are missing instead of coercing missing sources to `0`.
    """
    total_today_sessions: int | None = None
    total_7d_sessions: int | None = None
    total_30d_sessions: int | None = None
    domain_breakdown: list[dict[str, Any]] = []
    if TRAFFIC_JSON_PATH.exists():
        try:
            tdata = json.loads(TRAFFIC_JSON_PATH.read_text(encoding="utf-8"))
            sites = tdata.get("sites") or {}
            for dom, sinfo in sites.items():
                ga4_info = sinfo.get("ga4") if isinstance(sinfo, dict) else None
                periods = (ga4_info.get("periods") if isinstance(ga4_info, dict) else None) or {}
                if not isinstance(periods, dict) or not periods:
                    domain_breakdown.append({
                        "domain": dom,
                        "todaySessions": None,
                        "weekSessions": None,
                        "monthSessions": None,
                        "last7DaysSessions": None,
                        "last28DaysSessions": None,
                        "totalPageViewsToday": None,
                    })
                    continue

                def _sum_period_sources(p_obj: Any) -> int | None:
                    if not isinstance(p_obj, dict) or not isinstance(p_obj.get("sources"), list):
                        return None
                    acc = 0
                    for src in p_obj["sources"]:
                        if not isinstance(src, dict):
                            continue
                        s_name = str(src.get("source") or "").lower()
                        c_name = str(src.get("channel") or "").lower()
                        if any(k in s_name or k in c_name for k in channel_keywords):
                            raw_sess = src.get("sessions")
                            if isinstance(raw_sess, (int, float)):
                                acc += int(raw_sess)
                    return acc

                dom_today = _sum_period_sources(periods.get("today"))
                dom_7d = _sum_period_sources(periods.get("week"))
                dom_30d = _sum_period_sources(periods.get("month"))

                if dom_today is not None:
                    total_today_sessions = (total_today_sessions or 0) + dom_today
                if dom_7d is not None:
                    total_7d_sessions = (total_7d_sessions or 0) + dom_7d
                if dom_30d is not None:
                    total_30d_sessions = (total_30d_sessions or 0) + dom_30d

                today_obj = periods.get("today") if isinstance(periods.get("today"), dict) else None
                raw_pv_today = today_obj.get("pageViews") if today_obj else None
                pv_today = int(raw_pv_today) if isinstance(raw_pv_today, (int, float)) else None

                domain_breakdown.append({
                    "domain": dom,
                    "todaySessions": dom_today,
                    "weekSessions": dom_7d,
                    "monthSessions": dom_30d,
                    "last7DaysSessions": dom_7d,
                    "last28DaysSessions": dom_30d,
                    "totalPageViewsToday": pv_today,
                })
        except Exception:
            pass
    domain_breakdown.sort(
        key=lambda x: (
            x["monthSessions"] if x["monthSessions"] is not None else -1,
            x["totalPageViewsToday"] if x["totalPageViewsToday"] is not None else -1,
        ),
        reverse=True,
    )
    return {
        "windowMetadata": {
            "today": {"sourcePeriod": "today", "windowDays": 1},
            "week": {"sourcePeriod": "week", "windowDays": 7},
            "month": {
                "sourcePeriod": "month",
                "windowDays": 30,
                "note": "GA4 month period covers 30 days; last28DaysSessions aliases monthSessions for UI compatibility",
            },
        },
        "todaySessions": total_today_sessions,
        "weekSessions": total_7d_sessions,
        "monthSessions": total_30d_sessions,
        "last7DaysSessions": total_7d_sessions,
        "last28DaysSessions": total_30d_sessions,
        "topDomains": domain_breakdown[:8],
    }


def load_youtube_status() -> dict[str, Any]:
    if STATUS_PATH.exists():
        try:
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_youtube_status(data: dict[str, Any]) -> dict[str, Any]:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    STATUS_PATH.write_text(txt, encoding="utf-8")
    PUBLIC_JSON_PATH.write_text(txt, encoding="utf-8")
    return data


def sync_youtube_live_state() -> dict[str, Any]:
    """Sync live 3-channel state from EGO Lite (`barolab-soultin`) + rendered SVML assets + YouTube performance metrics."""
    from dashboard.common.ego_taskspace import native_sync_youtube_channels

    prev = load_youtube_status()
    renders = [
        render_hypit_svml_short(1),
        render_hypit_svml_short(2),
        render_hypit_svml_short(3),
    ]

    ego_res = native_sync_youtube_channels()
    live_posts = ego_res.get("mainChannelPosts") or prev.get("communityPosts") or []

    channels = [
        {
            "handle": "@yoon_autolab",
            "name": "윤랩 자동화 연구소",
            "role": "IT·테크·AI 에이전트·바이브코딩 자동화 & 수익화 연구소 (메인 본진)",
            "subscribers": 12,
            "activeTabs": ["동영상", "Shorts", "재생목록", "게시물(커뮤니티)"],
            "status": "active_flagship",
            "statusBadge": "🟢 IT/AI 자동화 본진 가동 중",
            "studioUrl": "https://www.youtube.com/@yoon_autolab",
            "postsUrl": "https://www.youtube.com/@yoon_autolab/posts",
            "bridgeDomains": ["meganote.kr", "justinfo.co.kr", "latpeed.com"],
            "strategyNote": "Google Flow AI(Nano Banana 2.1) 5-씬 시네마 + Hypit SVML 모션 쇼츠 → AI·자동화·수익화 아키텍처 본진 연결",
            "renderedShorts": 2,
            "publishedCommunityPosts": len(live_posts),
        },
        {
            "handle": "@숨은지원금",
            "name": "숨은지원금",
            "role": "4060 정책·환급금·주택연금·건보료 1분 요약 Shorts 특공대",
            "subscribers": 2,
            "activeTabs": ["Shorts"],
            "status": "active_shorts",
            "statusBadge": "🟢 4060 정책·연금 쇼츠 가동 중",
            "studioUrl": "https://www.youtube.com/@%EC%88%A8%EC%9D%80%EC%A7%80%EC%9B%90%EA%B8%88",
            "postsUrl": "https://www.youtube.com/@%EC%88%A8%EC%9D%80%EC%A7%80%EC%9B%90%EA%B8%88/shorts",
            "bridgeDomains": ["smilenote.kr", "must-good.com", "topnote.kr", "woorinote.kr"],
            "strategyNote": "복지·연금·세무·환급금 주제는 100% @숨은지원금 채널 전담 · 비교표 쇼츠로 CF 정책 본진 유입",
            "renderedShorts": 1,
            "publishedCommunityPosts": 0,
        },
        {
            "handle": "@바로랭크",
            "name": "바로랭크",
            "role": "쿠팡파트너스(AF1225691) 가전·테크 S/A/B 티어 랭킹 & 커뮤니티 브릿지",
            "subscribers": 18,
            "activeTabs": ["홈", "동영상", "재생목록", "게시물(커뮤니티)"],
            "status": "standby_migration",
            "statusBadge": "⏸️ 쿠팡 계정 이관 대기 (커뮤니티 활성)",
            "studioUrl": "https://www.youtube.com/@%EB%B0%94%EB%A1%9C%EB%9E%AD%ED%81%AC",
            "postsUrl": "https://www.youtube.com/@%EB%B0%94%EB%A1%9C%EB%9E%AD%ED%81%AC/posts",
            "bridgeDomains": ["healthcox.com", "joynote.kr", "nolplace.com"],
            "strategyNote": "쿠팡파트너스 계정 이관 완료 전까지 쿠팡 링크 스탠바이 · 게시물 탭 CF 생활/가전 비교표 브릿지 활용",
            "renderedShorts": 0,
            "publishedCommunityPosts": 0,
        }
    ]

    rendered_parts = {int(r.get("part", 0)) for r in renders}
    r1_dur = next((r.get("durationSec", 57.5) for r in renders if r.get("part") == 1), 57.5)
    r2_dur = next((r.get("durationSec", 57.6) for r in renders if r.get("part") == 2), 57.6)
    r3_dur = next((r.get("durationSec", 58.0) for r in renders if r.get("part") == 3), 58.0)
    planned_queue = [
        {
            "part": 1,
            "channel": "@yoon_autolab",
            "channelName": "윤랩 자동화 연구소 (IT·AI·수익화)",
            "templateId": "svml-tpl-01",
            "title": "챗GPT 단순 복붙 블로그가 망하는 이유 vs AI 에이전트 6명 24시간 자동 수익화 파이프라인",
            "bridgeDomain": "meganote.kr",
            "bridgeUrl": "https://www.meganote.kr/",
            "youtubeShortUrl": "https://youtube.com/shorts/of6rvdwE8jc",
            "scheduleSlot": "YouTube Shorts 라이브 업로드 완료",
            "shortStatus": "published",
            "shortStatusLabel": f"🟢 채널 업로드 완료 ({r1_dur}초 · of6rvdwE8jc)",
            "communityStatus": "published",
            "communityStatusLabel": "🟢 AI 파이프라인 커뮤니티 게시 완료",
            "communityUrl": "https://www.youtube.com/post/UgkxoUAWE6G2JHjFKBwmiu_bDgKkPBViBRd-",
        },
        {
            "part": 2,
            "channel": "@숨은지원금",
            "channelName": "숨은지원금 (4060 정책·연금 전담)",
            "templateId": "svml-tpl-01",
            "title": "2026 주택연금 공시가격 12억 기준 및 우대형 월 수령액 최대 20% 증액 비교",
            "bridgeDomain": "smilenote.kr",
            "bridgeUrl": "https://www.smilenote.kr/",
            "youtubeShortUrl": "https://youtube.com/shorts/dh_JGWQYgqI",
            "scheduleSlot": "YouTube Shorts 라이브 업로드 완료",
            "shortStatus": "published",
            "shortStatusLabel": f"🟢 채널 업로드 완료 ({r2_dur}초 · dh_JGWQYgqI)",
            "communityStatus": "published",
            "communityStatusLabel": "🟢 @숨은지원금 쇼츠 공개 완료",
            "communityUrl": "https://youtube.com/shorts/dh_JGWQYgqI",
        },
        {
            "part": 3,
            "channel": "@yoon_autolab",
            "channelName": "윤랩 자동화 연구소 (IT·AI·수익화)",
            "templateId": "svml-tpl-02",
            "title": "코딩 1줄 몰라도 바이브코딩(Google Flow·SVML)으로 고밀도 쇼츠 자동 제작하는 3단계 공식",
            "bridgeDomain": "justinfo.co.kr",
            "bridgeUrl": "https://www.justinfo.co.kr/",
            "youtubeShortUrl": "https://youtube.com/shorts/BctbZLl1Dtk",
            "scheduleSlot": "YouTube Shorts 라이브 업로드 완료",
            "shortStatus": "published",
            "shortStatusLabel": f"🟢 채널 업로드 완료 ({r3_dur}초 · BctbZLl1Dtk)",
            "communityStatus": "published",
            "communityStatusLabel": "🟢 @yoon_autolab 쇼츠 공개 완료",
            "communityUrl": "https://youtube.com/shorts/BctbZLl1Dtk",
        },
        {
            "part": 4,
            "channel": "@yoon_autolab",
            "channelName": "윤랩 자동화 연구소 (IT·AI·수익화)",
            "templateId": "svml-tpl-02",
            "title": "클로드 MCP + 브라우저 자동화(CDP)로 하루 3시간 리서치를 3분으로 줄이는 실전 워크플로우",
            "bridgeDomain": "meganote.kr",
            "bridgeUrl": "https://www.meganote.kr/",
            "scheduleSlot": "오늘 09:50 슬롯 완료",
            "shortStatus": "rendered",
            "shortStatusLabel": "🟢 SVML 대본·씬 설계 완료 (CDP 워크플로우)",
            "communityStatus": "published",
            "communityStatusLabel": "🟢 커뮤니티 브릿지 게시 완료",
            "communityUrl": "https://www.youtube.com/post/Ugkxt06XkhhKGmIngjtQ12NIMuQwX10Arrsj",
        },
        {
            "part": 5,
            "channel": "@숨은지원금",
            "channelName": "숨은지원금 (4060 정책·연금 전담)",
            "templateId": "svml-tpl-01",
            "title": "건강보험 본인부담상한제 환급금 1분 온라인 조회 & 퇴직 후 피부양자 방어선",
            "bridgeDomain": "must-good.com",
            "bridgeUrl": "https://www.must-good.com/",
            "scheduleSlot": "오늘 15:20 슬롯",
            "shortStatus": "queued",
            "shortStatusLabel": "⏳ 다음 제작 대기 (Flow + SVML)",
            "communityStatus": "queued",
            "communityStatusLabel": "⏳ 고정댓글·커뮤니티 브릿지 대기",
            "communityUrl": "",
        },
        {
            "part": 6,
            "channel": "@바로랭크",
            "channelName": "바로랭크 (가전·테크 랭킹)",
            "templateId": "svml-tpl-03",
            "title": "2026 가성비 미니 PC & AI 작업용 모니터 실측 S/A/B 티어 비교",
            "bridgeDomain": "joynote.kr",
            "bridgeUrl": "https://www.joynote.kr/",
            "scheduleSlot": "모레 10:00 예정",
            "shortStatus": "queued",
            "shortStatusLabel": "⏳ 쿠팡 이관 병행 대기 (Flow + SVML)",
            "communityStatus": "queued",
            "communityStatusLabel": "⏳ 커뮤니티 비교표 대기",
            "communityUrl": "",
        },
    ]

    for item in planned_queue:
        pno = item.get("part")
        topic_match = next((t for t in PRODUCTION_TOPICS if t["part"] == pno), None)
        if not topic_match:
            continue
        snippet = topic_match["communityPostText"].splitlines()[0][:25]
        matched_post = next((p for p in live_posts if snippet in str(p.get("text") or "")), None)
        if matched_post and item.get("communityStatus") != "published":
            item["communityStatus"] = "published"
            item["communityStatusLabel"] = "🟢 커뮤니티 브릿지 게시 완료"
            item["communityUrl"] = matched_post.get("url") or matched_post.get("postUrl") or item.get("communityUrl") or ""
            if item.get("shortStatus") == "queued":
                item["shortStatus"] = "rendered"
                item["shortStatusLabel"] = "🟢 SVML 대본·씬 설계 완료"
            if "예정" in str(item.get("scheduleSlot", "")) or "슬롯" in str(item.get("scheduleSlot", "")):
                item["scheduleSlot"] = f"{item['scheduleSlot']} 완료"

    yt_ga4 = _extract_ga4_channel_referrals(["youtube", "youtu.be", "google_video"])
    prev_meas = prev.get("measurement") if isinstance(prev.get("measurement"), dict) else {}
    obs_rev = prev_meas.get("observedRevenueUsd")
    obs_views = prev_meas.get("observedViews")
    estimated_rpm = (
        round((float(obs_rev) / float(obs_views)) * 1000.0, 2)
        if isinstance(obs_rev, (int, float)) and isinstance(obs_views, (int, float)) and obs_views > 0
        else None
    )
    measurement = {
        "ga4Referrals": yt_ga4,
        "totalSubscribers": 32,
        "renderedMp4Count": len(renders),
        "publishedCommunityCount": len(live_posts),
        "targetDailyShorts": 2,
        "targetCtrPct": 4.8,
        "estimatedHighCpcRpmUsd": estimated_rpm,
        "channelPerformance": [
            {
                "channel": "@yoon_autolab (윤랩 자동화 연구소)",
                "subscribers": 12,
                "completedAssets": f"Google Flow + SVML 쇼츠 2편 (AI 에이전트·바이브코딩) · 커뮤니티 {len(live_posts)}건",
                "targetDomains": "meganote.kr · justinfo.co.kr · latpeed.com",
                "conversionPath": "IT·AI·자동화 쇼츠 시청 → 게시물(커뮤니티) 아키텍처 클릭 → 테크 본진/디지털 프로덕트 유입",
                "status": "🟢 가동 중 (IT/AI 본진)",
            },
            {
                "channel": "@숨은지원금 (4060 정책·연금 쇼츠)",
                "subscribers": 2,
                "completedAssets": "Google Flow + SVML 쇼츠 1편 (주택연금 12억·우대형 20% 비교)",
                "targetDomains": "smilenote.kr · must-good.com · topnote.kr",
                "conversionPath": "4060 연금·환급 쇼츠 시청 → 고정댓글 원문 링크 → CF 정책·연금 계산기 직결",
                "status": "🟢 가동 중 (4060 정책 전담)",
            },
            {
                "channel": "@바로랭크 (쿠팡파트너스·테크 랭킹)",
                "subscribers": 18,
                "completedAssets": "기존 롱폼 2편 · 커뮤니티 브릿지 대기",
                "targetDomains": "healthcox.com · joynote.kr · nolplace.com",
                "conversionPath": "쿠팡파트너스(AF1225691) 이관 완료 즉시 S/A/B 티어 쇼츠 재개",
                "status": "⏸️ 이관 대기 (커뮤니티 활성)",
            },
        ],
    }

    data = {
        "ok": True,
        "updatedAt": now_kst_str(),
        "account": {
            "email": "baro76650@gmail.com",
            "owner": "윤성재 (대표님)",
            "egoProfile": "Profile 3 (barolab-soultin)",
            "cdpOnline": bool(ego_res.get("cdpOnline", True)),
            "selectedStrategy": "A안 — @yoon_autolab(윤랩 자동화 연구소) 메인 플래그십 + @숨은지원금 4060 쇼츠 + @바로랭크(쿠팡 이관 대기)",
            "notebookLmSource": "https://notebook.google.com/notebook/a13b1921-02c9-404e-8010-bd2e0dce9c52",
            "hypitSkillPath": "~/.agents/skills/hypit (hypit-ai/hypit · SVML v1.0)",
        },
        "kpi": {
            "channelCount": 3,
            "totalSubscribers": 32,
            "svmlTemplateCount": len(SVML_TEMPLATES),
            "renderedShortsCount": len(renders),
            "communityPostsCount": len(live_posts),
            "plannedQueueCount": len([q for q in planned_queue if q["shortStatus"] != "rendered" or q["communityStatus"] != "published"]),
            "ga4ReferralSessions7d": yt_ga4["weekSessions"],
            "ga4ReferralSessions30d": yt_ga4["monthSessions"],
            "ga4ReferralSessions28d": yt_ga4["last28DaysSessions"],
            "ga4WindowNote": "GA4 month period covers 30 days (week=7d, month=30d)",
        },
        "channels": channels,
        "svmlTemplates": SVML_TEMPLATES,
        "productionTopics": PRODUCTION_TOPICS,
        "renders": renders,
        "communityPosts": live_posts,
        "plannedQueue": planned_queue,
        "measurement": measurement,
    }
    return save_youtube_status(data)


def produce_youtube_svml_package(part_no: int = 1, publish_community: bool = True) -> dict[str, Any]:
    """Render the SVML Short MP4 for `part_no` AND optionally publish its companion Community Post to `@yoon_autolab`."""
    from dashboard.common.ego_taskspace import native_publish_youtube_community_post

    render_res = render_hypit_svml_short(part_no=part_no) if part_no in (1, 2, 3) else {"ok": True, "part": part_no, "skippedRender": True}
    topic = next((t for t in PRODUCTION_TOPICS if t["part"] == part_no), PRODUCTION_TOPICS[0])

    comm_res = {"ok": False, "skipped": not publish_community}
    if publish_community:
        comm_res = native_publish_youtube_community_post(
            channel_handle="@yoon_autolab",
            post_text=topic["communityPostText"],
        )

    st = load_youtube_status()
    if not render_res.get("skippedRender"):
        renders = [r for r in (st.get("renders") or []) if r.get("part") != render_res.get("part")]
        renders.insert(0, render_res)
        st["renders"] = renders
    if comm_res.get("ok") and comm_res.get("post"):
        posts = st.get("communityPosts") or []
        posts.insert(0, comm_res["post"])
        st["communityPosts"] = posts[:8]
    save_youtube_status(st)
    st = sync_youtube_live_state()
    return {
        "ok": True,
        "render": render_res,
        "communityPublish": comm_res,
        "status": st,
    }


def process_youtube_autonomy_once() -> dict[str, Any]:
    """24/7 Autonomous YouTube Community & Shorts Scheduler (09:50 & 15:20 KST)."""
    now_dt = dt.datetime.now(KST)
    st = load_youtube_status()
    posts = list(st.get("communityPosts") or [])
    planned = {int(q.get("part", 0)): q for q in (st.get("plannedQueue") or [])}
    cur_minutes = now_dt.hour * 60 + now_dt.minute
    if cur_minutes < 9 * 60 + 50:
        return {"ok": True, "action": "waiting_for_slot", "nextSlot": "09:50"}

    for topic in PRODUCTION_TOPICS:
        pno = int(topic.get("part", 0))
        q_item = planned.get(pno)
        if q_item and q_item.get("communityStatus") == "published":
            continue
        snippet = topic["communityPostText"].splitlines()[0][:25]
        if not any(snippet in str(p.get("text") or "") for p in posts):
            return produce_youtube_svml_package(part_no=pno, publish_community=True)
    return {"ok": True, "action": "all_topics_published", "postCount": len(posts)}


# Re-export from dedicated `naver_cafe_posting` package for backward compatibility
from naver_cafe_posting.posting import (
    DEFAULT_CAFE_PUBLISHED_ARTICLES,
    load_cafe_status,
    publish_cafe_bridge_part,
    save_cafe_status,
    sync_cafe_live_state,
)


if __name__ == "__main__":
    out = sync_youtube_live_state()
    print(json.dumps({
        "ok": out.get("ok"),
        "renders": len(out.get("renders", [])),
        "posts": len(out.get("communityPosts", [])),
    }, ensure_ascii=False))

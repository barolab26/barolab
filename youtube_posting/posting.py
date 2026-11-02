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
        "title": "스마트폰·PC 숨은 자동환급·세무 조회 3초 세팅법 (모르면 매년 놓치는 항목 비교)",
        "hookTitle": "매년 직접 찾으러 다니시나요? 딱 1번 자동 조회 설정으로 끝내는 실측 비교표",
        "badge": "윤랩 자동화 연구소 · 실전 리포트 #01",
        "bridgeDomain": "meganote.kr",
        "bridgeUrl": "https://meganote.kr/entry/2026-%EB%B6%80%EB%8F%99%EC%82%B0-%EC%9E%AC%EC%82%B0%EC%84%B8-%EA%B3%B5%EC%8B%9C%EA%B0%80%EA%B2%A9-%EA%B8%B0%EC%A4%80-%EC%A1%B0%ED%9A%8C%EB%B2%95",
        "bridgeLabel": "메가노트 IT·세무 자동조회 실측 비교표 전문",
        "narration": "매년 세금이나 환급금 조회할 때마다 일일이 사이트 찾아다니시나요? 윤랩 자동화 연구소에서 실측한 결과, 단 세 번의 통합 조회 설정만으로 확인 시간을 30분에서 1분으로 줄일 수 있습니다. 화면의 비교표처럼 개별 조회 대신 통합 알림과 공시가격 기준표를 함께 체크하면 누락되는 공제 항목까지 즉시 판별됩니다. 자세한 1분 체크리스트와 계산표는 채널 게시물과 고정 링크에서 바로 확인해 보세요.",
        "scenes": [
            {
                "phase": "SCENE 01 · 3초 충격 후킹 (0.0s ~ 4.0s)",
                "headline": "아직도 사이트마다\n일일이 로그인해서 조회하시나요?",
                "subline": "수동 개별 조회(30분) vs 윤랩 통합 루틴(1분) 실측 비교",
                "highlight": "연간 평균 3~4개 공제·감면 확인 누락 방지",
                "rows": [
                    ["조회 방식", "소요 시간", "누락 위험"],
                    ["개별 사이트 수동 탐색", "평균 25~30분", "높음 (특례 기준 누락)"],
                    ["윤랩 3단계 통합 체크", "1분 이내 완료", "낮음 (기준표 즉시 대조)"]
                ],
                "activeRow": 2,
                "footer": "⚡ SVML Anchor: @word(실측한) · Hook Retention Target 78%+"
            },
            {
                "phase": "SCENE 02 · 핵심 수치 1:1 비교표 (4.0s ~ 11.0s)",
                "headline": "2026 공시가격·세무 통합 조회\n핵심 기준 1:1 비교표",
                "subline": "1세대 1주택 특례세율 적용 구간 vs 일반 구간 한눈에 판독",
                "highlight": "공시가격 9억 이하 구간 특례세율(0.05%~0.35%) 필수 체크",
                "rows": [
                    ["점검 항목", "일반 수동 확인", "윤랩 기준표 판독"],
                    ["공시가격 기준", "단순 시세 추측", "공동주택 공시가격 정밀 대조"],
                    ["특례세율 적용", "미확인 과납 위험", "9억 이하 0.05%p 감면 즉시 판별"],
                    ["분납·공제 체크", "기한 경과 빈번", "사전 체크리스트 3문항 완결"]
                ],
                "activeRow": 2,
                "footer": "📊 SVML Component: comparison-table (highlight-row=2)"
            },
            {
                "phase": "SCENE 03 · 3클릭 실행 프로토콜 (11.0s ~ 16.0s)",
                "headline": "실패 없는 1분 점검\n3-Step 자동화 프로토콜",
                "subline": "복잡한 서류 없이 스마트폰에서 지금 바로 확인하는 순서",
                "highlight": "Step 1 공시가 확인 → Step 2 특례 판정 → Step 3 감면 체크",
                "rows": [
                    ["단계", "핵심 행동", "소요 시간"],
                    ["Step 1", "부동산공시가격 알리미 기준가 조회", "20초"],
                    ["Step 2", "1세대 1주택 특례 구간 대조표 확인", "20초"],
                    ["Step 3", "고령자·장기보유 세액공제 합산 점검", "20초"]
                ],
                "activeRow": 1,
                "footer": "🎯 채널 게시물(커뮤니티)에서 상세 기준표 원문 바로가기 제공"
            }
        ],
        "communityPostText": """[윤랩 자동화 연구소 실전 브리핑 #01] 스마트폰·PC로 1분 만에 끝내는 2026 공시가격·재산세 특례 기준 판독표 ⚡

매년 고지서가 나온 뒤에야 부랴부랴 세율과 공제 조건을 찾아보느라 시간을 쓰시진 않으셨나요?
윤랩 자동화 연구소에서 복잡한 조문 대신 딱 3단계(Step 1 기준가 확인 → Step 2 1주택 특례 대조 → Step 3 공제율 합산)로 판독할 수 있는 실측 기준표를 정리했습니다.

✅ 핵심 점검 포인트 3가지
1) 1세대 1주택 공시가격 9억 원 이하 구간 특례세율(0.05%~0.35%) 해당 여부
2) 과세기준일(6월 1일) 전후 변동 사항 및 합산 배제 체크
3) 분납 신청 기준 및 온라인 즉시 조회 경로

📊 구간별 세율 비교표와 1분 자가진단 체크리스트 전문은 아래 연구소 아카이브 원문에서 바로 확인하실 수 있습니다.
👉 https://meganote.kr/entry/2026-%EB%B6%80%EB%8F%99%EC%82%B0-%EC%9E%AC%EC%82%B0%EC%84%B8-%EA%B3%B5%EC%8B%9C%EA%B0%80%EA%B2%A9-%EA%B8%B0%EC%A4%80-%EC%A1%B0%ED%9A%8C%EB%B2%95"""
    },
    {
        "part": 2,
        "channel": "@숨은지원금",
        "channelName": "숨은지원금",
        "templateId": "svml-tpl-01",
        "title": "2026 주택연금 공시가격 12억 기준 및 우대형 월 수령액 차이 (24초 핵심 비교)",
        "hookTitle": "집값 9억 넘어서 포기하셨나요? 공시가격 12억 이하 + 우대형 최대 20% 증액 비교",
        "badge": "숨은지원금 · 4060 연금 브리핑 #01",
        "bridgeDomain": "smilenote.kr",
        "bridgeUrl": "https://smilenote.kr/entry/2026-%EC%A3%BC%ED%83%9D%EC%97%B0%EA%B8%88-%EA%B0%80%EC%9E%85%EC%A1%B0%EA%B1%B4-%EA%B3%B5%EC%8B%9C%EA%B0%80%EA%B2%A9-12%EC%96%B5-%EC%9B%94%EC%88%98%EB%A0%B9%EC%95%A1-%EA%B3%84%EC%82%B0",
        "bridgeLabel": "스마일노트 주택연금 연령별·집값별 월 수령액 비교표",
        "narration": "집값이 9억을 넘어서 주택연금 대상이 아니라고 생각하셨나요? 기준이 시세가 아닌 공시가격 12억 원 이하로 넓어지면서 실거래가 15억에서 17억 수준 아파트도 신청 대상에 들어옵니다. 특히 부부 중 한 분이 만 55세 이상이면 가능하고, 우대형 요건을 충족하면 일반형보다 월 지급금이 최대 20퍼센트까지 늘어납니다. 내 나이와 집값 기준 정확한 월 수령액 비교표는 고정 링크에서 바로 계산해 보세요.",
        "scenes": [
            {
                "phase": "SCENE 01 · 오해 깨기 후킹 (0.0s ~ 4.0s)",
                "headline": "집값 9억 넘으면 탈락?\n공시가격 12억 이하까지 가능합니다",
                "subline": "실거래가 약 15~17억 원 수준 주택도 공시가 12억 이하면 가입 대상",
                "highlight": "부부 중 1명 만 55세 이상 + 공시가격 12억 원 이하",
                "rows": [
                    ["구분", "과거 오해 기준", "2026 확인 기준"],
                    ["주택 가격", "시가 9억 초과 포기", "공시가격 12억 이하 가능"],
                    ["가입 연령", "부부 모두 65세 오해", "부부 중 연장자 만 55세 이상"]
                ],
                "activeRow": 1,
                "footer": "⚡ SVML Anchor: @word(공시가격) · 4060 정책 쇼츠"
            },
            {
                "phase": "SCENE 02 · 일반형 vs 우대형 비교 (4.0s ~ 11.0s)",
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

👉 연령별·주택가격별 상세 비교표 확인: https://smilenote.kr/entry/2026-%EC%A3%BC%ED%83%9D%EC%97%B0%EA%B8%88-%EA%B0%80%EC%9E%85%EC%A1%B0%EA%B1%B4-%EA%B3%B5%EC%8B%9C%EA%B0%80%EA%B2%A9-12%EC%96%B5-%EC%9B%94%EC%88%98%EB%A0%B9%EC%95%A1-%EA%B3%84%EC%82%B0"""
    },
    {
        "part": 3,
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "templateId": "svml-tpl-02",
        "title": "건강보험 본인부담상한제 환급금 1분 온라인 신청 루틴 (문자 사기 구별법 포함)",
        "hookTitle": "병원비 많이 나온 해, 신청 안 하면 잠자는 환급금 1분 조회 루틴",
        "badge": "윤랩 자동화 연구소 · 실전 리포트 #02",
        "bridgeDomain": "must-good.com",
        "bridgeUrl": "https://must-good.com/entry/2026-%EB%B3%B8%EC%9D%B8%EB%B6%80%EB%8B%B4%EC%83%81%ED%95%9C%EC%A0%9C-%EC%82%AC%ED%9B%84%ED%99%98%EA%B8%89%EA%B8%88-%EC%A1%B0%ED%9A%8C-%EC%8B%A0%EC%B2%AD%EB%B0%A9%EB%B2%95-%EC%86%8C%EB%93%9D%EB%B6%84%EC%9C%84-%EA%B8%B0%EC%A4%80",
        "bridgeLabel": "머스트굿 소득분위별 본인부담상한액 표 & 조회 가이드",
        "narration": "부모님 병원비가 많이 나왔던 해라면 건강보험 본인부담상한제 환급 대상인지 반드시 확인해야 합니다. 문자에 찍힌 의심스러운 인터넷 주소를 누르지 마시고, The건강보험 앱이나 공식 홈페이지에서 환급금 조회 메뉴만 누르면 1분 만에 대상 여부와 입금 계좌 신청이 끝납니다. 내 소득분위별 상한액 기준표는 채널 게시물 링크에서 한눈에 확인하세요.",
        "scenes": [
            {
                "phase": "SCENE 01 · 스미싱 주의 & 공식 루틴 (0.0s ~ 5.0s)",
                "headline": "환급금 문자 링크 클릭 금지!\n공식 앱 3클릭 조회 루틴",
                "subline": "사칭 URL 대신 국민건강보험 공식 경로로 1분 안에 직접 확인",
                "highlight": "비급여 제외 건강보험 본인부담금 연간 상한 초과분 환급",
                "rows": [
                    ["구분", "포함 여부", "핵심 판정 기준"],
                    ["급여 본인부담금", "O (환급 산정 포함)", "소득분위별 연간 상한액 초과분"],
                    ["비급여·도수·1인실", "X (산정 제외)", "실손보험 별도 청구 대상"]
                ],
                "activeRow": 1,
                "footer": "⚡ SVML Anchor: @word(환급) · 3-Click Protocol"
            },
            {
                "phase": "SCENE 02 · 소득구간별 상한 구조 (5.0s ~ 12.0s)",
                "headline": "소득분위가 낮을수록\n돌려받는 기준선이 낮아집니다",
                "subline": "1~3분위 저소득층부터 고소득 구간까지 차등 상한제 적용",
                "highlight": "진료받은 날로부터 3년 이내 미신청 환급금 통합 조회 가능",
                "rows": [
                    ["점검 순서", "실행 경로", "확인 내용"],
                    ["1단계", "국민건강보험 홈페이지 / 앱 로그인", "민원여기요 → 환급금 조회"],
                    ["2단계", "본인부담상한액 초과금 내역 확인", "대상 연도 및 지급 가능액"],
                    ["3단계", "본인 명의 계좌번호 입력 신청", "접수 후 영업일 순차 입금"]
                ],
                "activeRow": 2,
                "footer": "📌 상세 소득분위별 상한액 표: must-good.com 원문 연결"
            }
        ],
        "communityPostText": """[윤랩 자동화 연구소 실전 브리핑 #02] 건강보험 본인부담상한제 환급금 1분 공식 조회 루틴 (스미싱 구별 표 포함) 🛡️

병원비 지출이 컸던 해에 돌려받을 수 있는 '본인부담상한액 초과금'을 조회할 때, 문자 메시지의 출처 불명 링크를 누르는 것은 위험합니다.
반드시 국민건강보험 공식 홈페이지나 'The건강보험' 앱의 [환급금(지원금) 조회/신청] 메뉴로 직접 접속해 1분 만에 안전하게 확인하세요.

✅ 급여 포함 vs 비급여 제외 구분표와 소득분위별 상한 기준 원문:
👉 https://must-good.com/entry/2026-%EB%B3%B8%EC%9D%B8%EB%B6%80%EB%8B%B4%EC%83%81%ED%95%9C%EC%A0%9C-%EC%82%AC%ED%9B%84%ED%99%98%EA%B8%89%EA%B8%88-%EC%A1%B0%ED%9A%8C-%EC%8B%A0%EC%B2%AD%EB%B0%A9%EB%B2%95-%EC%86%8C%EB%93%9D%EB%B6%84%EC%9C%84-%EA%B8%B0%EC%A4%80"""
    }
]


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = [
        "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothicBold.ttf" if bold else "C:/Windows/Fonts/NanumGothic.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _generate_voice_or_chime_audio(text: str, out_wav: Path, target_seconds: float = 14.0) -> dict[str, Any]:
    """Generate ElevenLabs voiceover if API key & quota available; otherwise clean ambient synth chime WAV."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if api_key:
        try:
            import urllib.request
            voice_id = "pNInz6obpgDQGcFmaJgB"  # Adam / standard multilingual voice
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            payload = json.dumps({
                "text": text[:360],
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.55, "similarity_boost": 0.78}
            }).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                method="POST",
            )
            mp3_path = out_wav.with_suffix(".mp3")
            with urllib.request.urlopen(req, timeout=18) as resp:
                audio_bytes = resp.read()
                if len(audio_bytes) > 1000:
                    mp3_path.write_bytes(audio_bytes)
                    return {"engine": "elevenlabs_multilingual_v2", "path": str(mp3_path), "ok": True}
        except Exception:
            pass

    # Fallback: clean soft tech beat + chime cues at scene transitions
    sample_rate = 24000
    total_samples = int(sample_rate * target_seconds)
    with wave.open(str(out_wav), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(total_samples):
            t = i / sample_rate
            # Subtle warm chord pad + transition chimes at 0.0s, 4.5s, 9.5s
            chime = 0.0
            for trigger in (0.05, 4.5, 9.5):
                if trigger <= t <= trigger + 0.45:
                    dt_t = t - trigger
                    chime += 0.25 * math.exp(-dt_t * 7.0) * math.sin(2 * math.pi * 880.0 * dt_t)
            pad = 0.04 * math.sin(2 * math.pi * 220.0 * t) + 0.025 * math.sin(2 * math.pi * 330.0 * t)
            val = max(-0.9, min(0.9, pad + chime))
            frames.extend(struct.pack("<h", int(val * 32767)))
        wf.writeframes(bytes(frames))
    return {"engine": "svml_sfx_chime_track", "path": str(out_wav), "ok": True}


def _render_scene_frame(topic: dict[str, Any], scene: dict[str, Any], scene_idx: int, total_scenes: int, out_png: Path) -> None:
    """Render a 1080x1920 vertical high-contrast Hypit SVML motion card with comparison table and karaoke anchor bar."""
    from PIL import Image, ImageDraw

    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (11, 17, 32))
    draw = ImageDraw.Draw(img)

    # Top subtle gradient header band
    for y in range(0, 380):
        r = int(15 + (y / 380) * 8)
        g = int(23 + (y / 380) * 14)
        b = int(42 + (y / 380) * 28)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    font_badge = _load_font(28, bold=True)
    font_phase = _load_font(25, bold=True)
    font_h1 = _load_font(54, bold=True)
    font_sub = _load_font(30, bold=False)
    font_tbl_h = _load_font(29, bold=True)
    font_tbl_b = _load_font(28, bold=False)
    font_karaoke = _load_font(34, bold=True)
    font_foot = _load_font(24, bold=True)

    # 1. Top Channel + SVML Pill
    draw.rounded_rectangle([64, 78, 620, 138], radius=30, fill=(30, 58, 138), outline=(59, 130, 246), width=2)
    draw.text((92, 92), topic.get("badge", "윤랩 자동화 연구소 · SVML"), font=font_badge, fill=(147, 197, 253))

    draw.rounded_rectangle([760, 78, 1016, 138], radius=30, fill=(6, 78, 59), outline=(16, 185, 129), width=2)
    draw.text((792, 92), f"CUT {scene_idx + 1} / {total_scenes}", font=font_badge, fill=(110, 231, 183))

    # 2. Scene Phase Tag
    draw.text((68, 172), scene.get("phase", "SCENE"), font=font_phase, fill=(56, 189, 248))

    # 3. Main Headline (2 lines)
    y_cursor = 225
    for line in (scene.get("headline") or "").split("\n"):
        draw.text((68, y_cursor), line.strip(), font=font_h1, fill=(248, 250, 252))
        y_cursor += 72

    # 4. Subline
    draw.text((68, y_cursor + 12), scene.get("subline", ""), font=font_sub, fill=(148, 163, 184))

    # 5. Highlight Callout Box
    hl_top = 460
    draw.rounded_rectangle([64, hl_top, W - 64, hl_top + 110], radius=22, fill=(30, 41, 59), outline=(245, 158, 11), width=3)
    draw.text((98, hl_top + 35), f"★ 핵심 판정: {scene.get('highlight', '')}", font=font_tbl_h, fill=(253, 224, 71))

    # 6. SVML 1:1 Comparison Matrix Card
    tbl_top = 620
    rows = scene.get("rows") or []
    row_h = 135
    tbl_h = max(280, len(rows) * row_h + 40)
    draw.rounded_rectangle([64, tbl_top, W - 64, tbl_top + tbl_h], radius=26, fill=(15, 23, 42), outline=(51, 65, 85), width=2)

    col_xs = [96, 380, 710]
    active_row = scene.get("activeRow", 1)
    for r_i, row in enumerate(rows):
        ry = tbl_top + 20 + r_i * row_h
        if r_i == 0:
            draw.rounded_rectangle([80, ry, W - 80, ry + row_h - 14], radius=16, fill=(37, 99, 235))
            txt_color = (255, 255, 255)
            f_use = font_tbl_h
        elif r_i == active_row:
            draw.rounded_rectangle([80, ry, W - 80, ry + row_h - 14], radius=16, fill=(6, 78, 59), outline=(52, 211, 153), width=3)
            txt_color = (167, 243, 208)
            f_use = font_tbl_h
        else:
            draw.rounded_rectangle([80, ry, W - 80, ry + row_h - 14], radius=16, fill=(30, 41, 59))
            txt_color = (226, 232, 240)
            f_use = font_tbl_b

        for c_i, cell in enumerate(row[:3]):
            draw.text((col_xs[c_i], ry + 42), str(cell)[:22], font=f_use, fill=txt_color)

    # 7. Word-Anchored Karaoke Subtitle Box
    k_top = 1340
    draw.rounded_rectangle([64, k_top, W - 64, k_top + 210], radius=28, fill=(17, 24, 39), outline=(56, 189, 248), width=3)
    draw.text((98, k_top + 28), "🎙️ SVML WORD-ANCHORED KARAOKE CAPTION", font=font_foot, fill=(56, 189, 248))
    narration_sentences = [s.strip() for s in (topic.get("narration") or "").split(".") if s.strip()]
    cap_line = narration_sentences[min(scene_idx, len(narration_sentences) - 1)] if narration_sentences else topic.get("hookTitle", "")
    # Wrap caption into 2 lines
    line1 = cap_line[:26]
    line2 = cap_line[26:54]
    draw.text((98, k_top + 78), f"“{line1}", font=font_karaoke, fill=(255, 255, 255))
    if line2:
        draw.text((98, k_top + 132), f"{line2}”", font=font_karaoke, fill=(250, 204, 21))

    # 8. Bottom Bridge CTA Bar
    cta_top = 1610
    draw.rounded_rectangle([64, cta_top, W - 64, cta_top + 175], radius=24, fill=(30, 58, 138), outline=(96, 165, 250), width=2)
    draw.text((98, cta_top + 32), f"📌 상세 계산표·원문 아카이브: {topic.get('bridgeDomain', 'meganote.kr')}", font=font_tbl_h, fill=(255, 255, 255))
    draw.text((98, cta_top + 84), "유튜브 [게시물] 탭 · 고정댓글 링크에서 1분 체크리스트 확인", font=font_sub, fill=(191, 219, 254))
    draw.text((98, cta_top + 130), scene.get("footer", ""), font=font_foot, fill=(147, 197, 253))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_png), format="PNG")


def render_hypit_svml_short(part_no: int = 1) -> dict[str, Any]:
    """Render a crisp 1080x1920 MP4 Short from the SVML blueprint using PIL + ElevenLabs/SFX + FFmpeg."""
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    topic = next((t for t in PRODUCTION_TOPICS if t["part"] == part_no), PRODUCTION_TOPICS[0])
    slug = f"svml_short_part{topic['part']}"
    work_dir = RENDERS_DIR / f"_build_{slug}"
    work_dir.mkdir(parents=True, exist_ok=True)

    scenes = topic.get("scenes") or []
    frame_paths: list[Path] = []
    for idx, sc in enumerate(scenes):
        fp = work_dir / f"scene_{idx:02d}.png"
        _render_scene_frame(topic, sc, idx, len(scenes), fp)
        frame_paths.append(fp)

    # Also copy the first scene as a public thumbnail
    thumb_path = RENDERS_DIR / f"{slug}_thumb.png"
    if frame_paths:
        shutil.copyfile(frame_paths[0], thumb_path)

    total_duration = max(12.0, len(frame_paths) * 4.8)
    audio_info = _generate_voice_or_chime_audio(topic.get("narration", ""), work_dir / "voice.wav", target_seconds=total_duration)

    out_mp4 = RENDERS_DIR / f"{slug}.mp4"
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin and frame_paths:
        concat_txt = work_dir / "concat.txt"
        lines = []
        per_scene = round(total_duration / len(frame_paths), 2)
        for fp in frame_paths:
            lines.append(f"file '{fp.as_posix()}'")
            lines.append(f"duration {per_scene}")
        lines.append(f"file '{frame_paths[-1].as_posix()}'")
        concat_txt.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-i", audio_info["path"],
            "-c:v", "libx264",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            str(out_mp4),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)

    size_kb = round(out_mp4.stat().st_size / 1024, 1) if out_mp4.exists() else 0.0
    return {
        "ok": out_mp4.exists() and size_kb > 10,
        "part": topic["part"],
        "channel": topic["channel"],
        "channelName": topic["channelName"],
        "templateId": topic["templateId"],
        "title": topic["title"],
        "hookTitle": topic["hookTitle"],
        "bridgeDomain": topic["bridgeDomain"],
        "bridgeUrl": topic["bridgeUrl"],
        "videoUrl": f"/api/youtube/media/{out_mp4.name}",
        "thumbUrl": f"/api/youtube/media/{thumb_path.name}",
        "fileSizeKb": size_kb,
        "durationSec": round(total_duration, 1),
        "audioEngine": audio_info["engine"],
        "renderedAt": now_kst_str(),
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
    """Sync live 3-channel state from EGO Lite (`barolab-soultin`) + rendered SVML assets + Naver Cafe OSMU bridges."""
    from dashboard.common.ego_taskspace import native_sync_youtube_channels

    prev = load_youtube_status()
    renders = list(prev.get("renders") or [])
    if len(renders) < 3:
        renders = [
            render_hypit_svml_short(1),
            render_hypit_svml_short(2),
            render_hypit_svml_short(3),
        ]
    else:
        for r in renders:
            if isinstance(r.get("videoUrl"), str) and r["videoUrl"].startswith("/data/youtube_renders/"):
                r["videoUrl"] = r["videoUrl"].replace("/data/youtube_renders/", "/api/youtube/media/")
            if isinstance(r.get("thumbUrl"), str) and r["thumbUrl"].startswith("/data/youtube_renders/"):
                r["thumbUrl"] = r["thumbUrl"].replace("/data/youtube_renders/", "/api/youtube/media/")

    ego_res = native_sync_youtube_channels()
    live_posts = ego_res.get("mainChannelPosts") or prev.get("communityPosts") or []

    channels = [
        {
            "handle": "@yoon_autolab",
            "name": "윤랩 자동화 연구소",
            "role": "A안 메인 본진 (AI·업무 자동화·스마트폰/정부24/세무 실전 기술 연구소)",
            "subscribers": 12,
            "activeTabs": ["동영상", "Shorts", "재생목록", "게시물(커뮤니티)"],
            "status": "active_flagship",
            "statusBadge": "🟢 A안 메인 본진 가동 중",
            "studioUrl": "https://www.youtube.com/@yoon_autolab",
            "postsUrl": "https://www.youtube.com/@yoon_autolab/posts",
            "bridgeDomains": ["meganote.kr", "justinfo.co.kr", "daynote.kr", "baronote.kr"],
            "strategyNote": "Hypit SVML 유형 A/B 쇼츠 + 커뮤니티 탭 1분 체크리스트로 CF IT·비즈니스·세무 본진 직결"
        },
        {
            "handle": "@숨은지원금",
            "name": "숨은지원금",
            "role": "4060 정책·환급금·연금 25초 SVML 요약 Shorts 특공대",
            "subscribers": 2,
            "activeTabs": ["Shorts"],
            "status": "active_shorts",
            "statusBadge": "🟢 4060 정책 쇼츠 가동 중",
            "studioUrl": "https://www.youtube.com/@%EC%88%A8%EC%9D%80%EC%A7%80%EC%9B%90%EA%B8%88",
            "postsUrl": "https://www.youtube.com/@%EC%88%A8%EC%9D%80%EC%A7%80%EC%9B%90%EA%B8%88/shorts",
            "bridgeDomains": ["must-good.com", "smilenote.kr", "topnote.kr", "woorinote.kr"],
            "strategyNote": "자청 4대 결핍(손실회피·즉시판정) 24초 비교표 쇼츠 → 고정댓글로 CF 연금·복지 본진 유입"
        },
        {
            "handle": "@바로랭크",
            "name": "바로랭크",
            "role": "쿠팡파트너스(AF1225691) 가전·생활 랭킹 & 커뮤니티 브릿지",
            "subscribers": 18,
            "activeTabs": ["홈", "동영상", "재생목록", "게시물(커뮤니티)"],
            "status": "standby_migration",
            "statusBadge": "⏸️ 쿠팡 계정 이관 대기 (커뮤니티 활성)",
            "studioUrl": "https://www.youtube.com/@%EB%B0%94%EB%A1%9C%EB%9E%AD%ED%81%AC",
            "postsUrl": "https://www.youtube.com/@%EB%B0%94%EB%A1%9C%EB%9E%AD%ED%81%AC/posts",
            "bridgeDomains": ["healthcox.com", "trendnote.co.kr", "dailymemo.co.kr"],
            "strategyNote": "쿠팡파트너스 계정 이관 완료 전까지 쿠팡 링크 스탠바이 · 게시물 탭 CF 생활/건강 비교표 브릿지 활용"
        }
    ]

    naver_cafes = prev.get("naverCafes") or [
        {
            "cafeId": "loveshake1",
            "clubId": "19858249",
            "menuId": "164",
            "name": "[금융꿀팁]직장인/주부/서민/아파트론/대환/사잇돌/저금리/대출",
            "grade": "가지5단계 (2009년 개설 17년 차)",
            "members": 28495,
            "account": "soul5373 (Profile 4)",
            "latestArticleUrl": "https://cafe.naver.com/loveshake1/162878",
            "latestTitle": "2026 주택연금 가입조건 공시가격 12억 기준 및 월 수령액·우대형 계산 핵심정리",
            "bridgeDomain": "smilenote.kr",
            "status": "live"
        },
        {
            "cafeId": "boutiqueinfo",
            "clubId": "31608088",
            "menuId": "4",
            "name": "고급지식의 모든 것",
            "grade": "가지3단계",
            "members": 1722,
            "account": "soul5373 (Profile 4)",
            "latestArticleUrl": "https://cafe.naver.com/boutiqueinfo/2302",
            "latestTitle": "2026 주택연금 가입조건 공시가격 12억 기준 및 월 수령액·우대형 계산 핵심정리",
            "bridgeDomain": "smilenote.kr",
            "status": "live"
        }
    ]

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
            "cafeBridgeMembers": 30217,
            "cafePublishedCount": len(naver_cafes),
        },
        "channels": channels,
        "svmlTemplates": SVML_TEMPLATES,
        "productionTopics": PRODUCTION_TOPICS,
        "renders": renders,
        "communityPosts": live_posts,
        "naverCafes": naver_cafes,
    }
    return save_youtube_status(data)


def produce_youtube_svml_package(part_no: int = 1, publish_community: bool = True) -> dict[str, Any]:
    """Render the SVML Short MP4 for `part_no` AND optionally publish its companion Community Post to `@yoon_autolab`."""
    from dashboard.common.ego_taskspace import native_publish_youtube_community_post

    render_res = render_hypit_svml_short(part_no=part_no)
    topic = next((t for t in PRODUCTION_TOPICS if t["part"] == part_no), PRODUCTION_TOPICS[0])

    comm_res = {"ok": False, "skipped": not publish_community}
    if publish_community:
        comm_res = native_publish_youtube_community_post(
            channel_handle="@yoon_autolab",
            post_text=topic["communityPostText"],
        )

    st = sync_youtube_live_state()
    # Update or prepend render in status
    renders = [r for r in (st.get("renders") or []) if r.get("part") != render_res.get("part")]
    renders.insert(0, render_res)
    st["renders"] = renders
    st["kpi"]["renderedShortsCount"] = len(renders)
    if comm_res.get("ok") and comm_res.get("post"):
        posts = st.get("communityPosts") or []
        posts.insert(0, comm_res["post"])
        st["communityPosts"] = posts[:8]
        st["kpi"]["communityPostsCount"] = len(st["communityPosts"])
    save_youtube_status(st)
    return {
        "ok": True,
        "render": render_res,
        "communityPublish": comm_res,
        "status": st,
    }


if __name__ == "__main__":
    out = sync_youtube_live_state()
    print(json.dumps({"ok": out.get("ok"), "renders": len(out.get("renders", [])), "posts": len(out.get("communityPosts", []))}, ensure_ascii=False))

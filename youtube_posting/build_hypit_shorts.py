import asyncio
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any
import edge_tts

PROJECT_ROOT = Path(__file__).resolve().parent
RENDERS_DIR = PROJECT_ROOT.parent / "dashboard" / "data" / "public" / "youtube_renders"
PRODUCTIONS_DIR = PROJECT_ROOT / "productions"
ASSETS_DIR = PROJECT_ROOT / "assets"
FLOW_SCENES_DIR = ASSETS_DIR / "flow_scenes"

SHORTS_SPECS: list[dict[str, Any]] = [
    {
        "part": 1,
        "slug": "part1",
        "themeMode": "tech-cyber",
        "voice": "ko-KR-InJoonNeural",
        "rate": "+48%",
        "brolls": [
            "part1_beat1.jpg",
            "part1_beat2.jpg",
            "part1_beat3.jpg",
            "part1_beat4.jpg",
            "part1_beat5.jpg",
        ],
        "sceneCaptions": [
            "SCENE 01 · AI 에이전트 6명 무인 아키텍처",
            "SCENE 02 · 단순 복붙 저품질 vs 분업형 자동화",
            "SCENE 03 · 트렌드 발굴 → 원고 → 멀티채널 배포",
            "SCENE 04 · 색인·체류시간·RPM 실측 피드백 루프",
            "SCENE 05 · 24시간 무인 파이프라인 3대 공식",
        ],
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "categoryPill": "AI 에이전트 · 수익화 자동화",
        "accentColor": "rgba(56,189,248,0.22)",
        "title": "챗GPT 단순 복붙 블로그가 망하는 이유 vs AI 에이전트 6명 24시간 자동 수익화 파이프라인",
        "hookBadge": "챗GPT 단순 복붙 수익화의 종말",
        "hookStat": "6 AGENTS",
        "hookUnit": "24시간 자율 구동 멀티채널 수익화 파이프라인",
        "hookTitle": "챗GPT 복붙 블로그가 망할 때\nAI 에이전트 팀은 수익을 만듭니다",
        "hookSub": "프롬프트 한 줄로 찍어낸 양산형 글이 왜 검색에서 누락되는지 실측 아키텍처로 비교합니다",
        "compareTitle": "단순 챗GPT 복붙 vs 6-에이전트 분업 비교",
        "wrongLabel": "실패 패턴 · 프롬프트 단순 복붙",
        "wrongTitle": "AI 양산형 요약문 · 검색 색인 즉시 누락",
        "wrongDesc": "팩트 검증 없는 천편일률적 요약문은 검색엔진 스팸 필터에 걸려 방문자 0명과 저품질 페널티로 직결됩니다.",
        "rightLabel": "승리 공식 · 역할 분담 6-에이전트 파이프라인",
        "rightTitle": "빈집 키워드 채굴 + 실측 데이터 + OSMU 확산",
        "rightDesc": "트렌드 스카우터부터 전환율 감사·멀티채널 배포까지 6개 전문 에이전트가 분업해 고단가 유입을 만듭니다.",
        "stepsTitle": "24시간 무인 수익화 파이프라인 3단계",
        "steps": [
            {
                "badge": "STEP 01",
                "title": "Radar · 고단가 빈집 키워드 실시간 포착",
                "detail": "검색 수요 대비 경쟁 문서가 적은 블루오션 주제와 실시간 질문 자동 수집",
            },
            {
                "badge": "STEP 02",
                "title": "Publi & Doctor · 비교표·수치 중심 원고 설계",
                "detail": "공무원식 요약을 배제하고 손실회피 훅·비교표·체크리스트로 체류시간 극대화",
            },
            {
                "badge": "STEP 03",
                "title": "OSMU · 블로그·카페·스레드·쇼츠 동시 확산",
                "detail": "검증된 원본 데이터 1개를 매체별 문법으로 자동 변환해 외부유입 퍼널 완성",
            },
        ],
        "ruleBadge": "발행량이 아닌 PV·RPM 실측 피드백 루프",
        "ruleTitle": "단순 발행 완료는 0점,\n유입과 수익이 찍혀야 채택됩니다",
        "ruleDesc": "구글 애널리틱스·서치콘솔·애드센스 실측 지표를 지식그래프에 역반영해 우승 포맷만 스스로 진화시킵니다.",
        "rulePill1": "우승 원고 공식 자동 학습 (+1점 가중치)",
        "rulePill2": "무유입·이탈 패턴 즉시 폐기 (-1점 피벗)",
        "closingTitle": "AI 수익화 파이프라인 구축 3대 체크리스트",
        "check1": "단순 챗GPT 복붙 중단 · 역할별 멀티 에이전트 분업화",
        "check2": "고단가 타깃 키워드 + 비교표·체크리스트 구조화",
        "check3": "블로그·카페·쇼츠 원소스 멀티유즈(OSMU) 브릿지 연결",
        "ctaBanner": "윤랩 자동화 연구소 게시물 탭에서 전체 파이프라인 설계도를 확인하세요",
        "segments": [
            {
                "highlight": "HOOK · 왜 챗GPT 복붙 블로그는 수익이 0원일까?",
                "text": "챗GPT에 주제만 던져주고 복사해 붙여넣는 블로그, 왜 아무리 글을 찍어내도 수익이 나지 않을까요?",
            },
            {
                "highlight": "FACT · 단일 프롬프트 vs 6-에이전트 자율 파이프라인",
                "text": "검색엔진 알고리즘은 이제 단순 요약형 AI 문체를 즉시 걸러내지만, 역할을 나눈 여섯 명의 AI 에이전트 팀은 24시간 유입과 수익을 만들어냅니다.",
            },
            {
                "highlight": "COMPARE · 양산형 스팸 필터링의 구조적 한계",
                "text": "혼자서 프롬프트 한 줄로 글을 뽑아내면 구체적인 수치와 비교표가 빠져 체류시간이 무너지고 색인에서 통째로 누락됩니다.",
            },
            {
                "highlight": "SOLUTION · 6개 전문 에이전트 완벽 분업화",
                "text": "반면 윤랩 자동화 파이프라인은 트렌드 발굴부터 원고 작성, 품질 감사, 멀티채널 배포까지 여섯 단계를 전문 에이전트가 나눠 맡습니다.",
            },
            {
                "highlight": "STEP 01 · Radar 에이전트의 빈집 황금키워드 포착",
                "text": "첫째, 레이더 에이전트가 검색량은 많지만 경쟁 문서가 비어 있는 고단가 블루오션 키워드와 실시간 질문을 먼저 포착합니다.",
            },
            {
                "highlight": "STEP 02 · Publi & Doctor의 비교표·수치 검증",
                "text": "둘째, 퍼블리와 닥터 에이전트가 뻔한 서론을 지우고 핵심 수치 비교표와 전환 동선을 설계해 독자의 체류시간을 극대화합니다.",
            },
            {
                "highlight": "STEP 03 · 원소스 멀티유즈(OSMU) 전 채널 자동 확산",
                "text": "셋째, 완성된 하나의 원본 콘텐츠를 워드프레스와 클라우드플레어 블로그, 네이버 카페, 스레드, 유튜브 쇼츠로 동시에 확산시킵니다.",
            },
            {
                "highlight": "METRIC · 발행 개수가 아닌 실측 PV와 달러 수익",
                "text": "가장 중요한 핵심은 글을 발행했다고 끝나는 것이 아니라, 실제 방문자와 광고 수익 데이터를 추적해 점수를 매긴다는 점입니다.",
            },
            {
                "highlight": "LOOP · 지식그래프 자기진화 피드백 루프",
                "text": "트레이스 에이전트가 매일 조회수와 클릭률을 분석해 수익을 낸 우승 공식만 남기고, 반응 없는 패턴은 즉시 폐기합니다.",
            },
            {
                "highlight": "FINAL · 3대 자동화 공식 & 아키텍처 확인 안내",
                "text": "멀티 에이전트 분업, 비교표 구조화, 멀티채널 브릿지 세 가지를 기억하시고, 채널 게시물 탭에서 전체 자동화 설계도를 바로 확인해 보세요.",
            },
        ],
    },
    {
        "part": 2,
        "slug": "part2",
        "themeMode": "senior-editorial",
        "voice": "ko-KR-SunHiNeural",
        "rate": "+38%",
        "brolls": [
            "part2_beat1.jpg",
            "part2_beat2.jpg",
            "part2_beat3.jpg",
            "part2_beat4.jpg",
            "part2_beat5.jpg",
        ],
        "sceneCaptions": [
            "SCENE 01 · 2026 주택연금 공시가 12억 기준",
            "SCENE 02 · 일반형 vs 우대형 수령액 격차",
            "SCENE 03 · 한국주택금융공사 3단계 조회법",
            "SCENE 04 · 우대형 최대 20% 증액 기준선",
            "SCENE 05 · 가입 전 필수 3대 체크리스트",
        ],
        "channel": "@숨은지원금",
        "channelName": "숨은지원금 · 정책·연금 연구소",
        "categoryPill": "2026 주택연금 · 노후 연금 설계",
        "accentColor": "rgba(16,185,129,0.22)",
        "title": "2026 주택연금 공시가격 12억 기준 및 우대형 월 수령액 최대 20% 증액 비교",
        "hookBadge": "부부 중 1명 만 55세 이상 핵심 기준",
        "hookStat": "+20%",
        "hookUnit": "우대형 주택연금 선택 시 월 수령액 최대 증액 폭",
        "hookTitle": "내 집으로 매달 평생 받는 연금\n일반형 vs 우대형 얼마 차이 날까?",
        "hookSub": "공시가격 12억 원 이하 가입 문턱 완화와 시세 2억 5천만 원 미만 우대형 조건 핵심 비교",
        "compareTitle": "일반형 vs 우대형 주택연금 구조 비교",
        "wrongLabel": "일반형 주택연금 기본 조회",
        "wrongTitle": "우대 요건 미확인 시 기본 지급률 적용",
        "wrongDesc": "1주택 기초연금 수급자임에도 일반형으로만 단순 계산하면 매달 받을 수 있는 추가 증액분을 놓치기 쉽습니다.",
        "rightLabel": "우대형 주택연금 · 최대 20% 증액",
        "rightTitle": "시가 2.5억 미만 + 기초연금 수급 1주택",
        "rightDesc": "우대형 요건을 충족하면 동일 연령·주택가격 대비 매달 수령하는 연금 지급액이 최대 20%까지 늘어납니다.",
        "stepsTitle": "예상 월 수령액 1분 계산 3단계",
        "steps": [
            {
                "badge": "STEP 01",
                "title": "한국주택금융공사 홈페이지·앱 접속",
                "detail": "주택연금 메뉴 → 예상연금조회 계산기 화면 열기",
            },
            {
                "badge": "STEP 02",
                "title": "부부 생년월일 및 주택 시세 입력",
                "detail": "연소자 기준 연령과 한국부동산원·KB 시세 자동 불러오기",
            },
            {
                "badge": "STEP 03",
                "title": "일반형·우대형 및 지급방식 비교",
                "detail": "종신지급방식·정액형 기준으로 우대형 해당 여부 즉시 대조",
            },
        ],
        "ruleBadge": "가입 전 반드시 확인할 평생 지급 보장 규칙",
        "ruleTitle": "집값이 내려가도 첫 수령액 그대로,\n남으면 자녀에게 상속됩니다",
        "ruleDesc": "국가가 평생 지급을 보증하므로 향후 주택 가격 하락에 따른 연금 삭감 위험이 없으며, 연금 총액이 집값보다 적으면 차액은 상속인에게 돌아갑니다.",
        "rulePill1": "가입 기준: 부부 중 1명 만 55세 이상 · 공시가 12억 이하",
        "rulePill2": "우대 기준: 시세 2.5억 미만 1주택 + 기초연금 수급자",
        "closingTitle": "주택연금 신청 전 3대 핵심 요약",
        "check1": "공시가격 12억 원 이하 여부 (다주택 합산 기준 포함)",
        "check2": "시세 2억 5천만 원 미만 시 우대형 최대 20% 증액 체크",
        "check3": "부부 중 연소자 나이와 현재 시세로 예상연금 사전 시뮬레이션",
        "ctaBanner": "채널 게시물 탭에서 연령별·주택가격별 상세 수령액 비교표를 확인하세요",
        "segments": [
            {
                "highlight": "HOOK · 평생 거주하며 매달 받는 주택연금",
                "text": "평생 살던 내 집에 그대로 거주하면서 매달 따박따박 월급처럼 연금을 받을 수 있다면 얼마가 나올까요?",
            },
            {
                "highlight": "CORE · 공시가격 12억 이하 & 우대형 최대 20% 증액",
                "text": "2026년 주택연금은 공시가격 12억 원 이하까지 문턱이 넓어졌고, 우대형 요건에 해당하면 월 수령액이 최대 20퍼센트까지 늘어납니다.",
            },
            {
                "highlight": "COMPARE · 일반형 단순 계산의 함정",
                "text": "많은 분들이 내 집 시세만 넣고 일반형으로 계산해 본 뒤 예상보다 적다며 포기하곤 합니다.",
            },
            {
                "highlight": "BENEFIT · 우대형 주택연금 증액 조건",
                "text": "하지만 부부 기준 1주택자이면서 기초연금 수급자이고 주택 시세가 2억 5천만 원 미만이라면 우대형으로 훨씬 높은 월 지급액을 적용받습니다.",
            },
            {
                "highlight": "STEP 01 · 한국주택금융공사 예상연금조회 접속",
                "text": "내 예상 수령액 확인 첫 단계는 한국주택금융공사 홈페이지나 스마트주택금융 앱에서 예상연금조회 메뉴를 여는 것입니다.",
            },
            {
                "highlight": "STEP 02 · 연소자 연령 및 KB·한국부동산원 시세 입력",
                "text": "둘째, 부부 중 나이가 더 적은 분의 생년월일과 현재 아파트나 주택의 시세를 순서대로 입력합니다.",
            },
            {
                "highlight": "STEP 03 · 종신 정액형 및 우대형 비교",
                "text": "셋째, 지급 유형을 종신 정액형으로 두고 일반형과 우대형 버튼을 번갈아 눌러 월 수령액 차이를 바로 비교합니다.",
            },
            {
                "highlight": "RULE · 집값 하락 무관 평생 동일 금액 보장",
                "text": "특히 주택연금은 가입 후 집값이 떨어져도 처음 결정된 월 수령액이 평생 깎이지 않고 그대로 지급됩니다.",
            },
            {
                "highlight": "SAFETY · 정산 시 남는 차액 상속, 부족분 미청구",
                "text": "반대로 나중에 집값이 남으면 자녀에게 상속되고, 연금을 더 많이 받았더라도 상속인에게 부족분을 절대 청구하지 않습니다.",
            },
            {
                "highlight": "FINAL · 3대 핵심 요약 & 연령별 수령액표 확인",
                "text": "공시가 12억 기준, 우대형 20퍼센트 증액, 연소자 연령 기준 세 가지를 꼭 기억하시고 채널 게시물 탭에서 연령별 비교표를 확인해 보세요.",
            },
        ],
    },
    {
        "part": 3,
        "slug": "part3",
        "themeMode": "vibe-terminal",
        "voice": "ko-KR-InJoonNeural",
        "rate": "+48%",
        "brolls": [
            "part3_beat1.jpg",
            "part3_beat2.jpg",
            "part3_beat3.jpg",
            "part3_beat4.jpg",
            "part3_beat5.jpg",
        ],
        "sceneCaptions": [
            "SCENE 01 · 바이브코딩 무인 미디어 스튜디오",
            "SCENE 02 · 수작업 편집 vs 코드 기반 자동 렌더링",
            "SCENE 03 · Google Flow + SVML + TTS 3단계 조립",
            "SCENE 04 · 30fps 프레임 단위 자막·모션 동기화",
            "SCENE 05 · 1인 자동화 크리에이터 3대 체크리스트",
        ],
        "channel": "@yoon_autolab",
        "channelName": "윤랩 자동화 연구소",
        "categoryPill": "바이브코딩 · 쇼츠 자동화 엔진",
        "accentColor": "rgba(99,102,241,0.24)",
        "title": "코딩 1줄 몰라도 바이브코딩(Google Flow·SVML)으로 고밀도 쇼츠 자동 제작하는 3단계 공식",
        "hookBadge": "수작업 영상 편집 노가다 완벽 탈출",
        "hookStat": "3 STEPS",
        "hookUnit": "Google Flow AI 비주얼 + SVML 모션그래픽 자동 빌드",
        "hookTitle": "아직도 타임라인 자르고 붙이세요?\n코드가 쇼츠를 통째로 렌더링합니다",
        "hookSub": "단순 정지화면 짜깁기가 아닌 5개 씬 AI 비주얼과 30프레임 모션그래픽을 자동 조립하는 비결",
        "compareTitle": "기존 수작업·저품질 양산 vs 코드 기반 스튜디오",
        "wrongLabel": "기존 실패 방식 · 정지화면 텍스트 얹기",
        "wrongTitle": "단조로운 배경 1장 + 기계식 자막 나열",
        "wrongDesc": "화면 변화가 없는 슬라이드쇼 형태는 초반 3초 이탈률이 80%를 넘고 유튜브 알고리즘 추천에서 즉시 배제됩니다.",
        "rightLabel": "윤랩 바이브코딩 · Google Flow + SVML 엔진",
        "rightTitle": "5-비트 AI 시네마 뷰포트 + 동적 모션 카드",
        "rightDesc": "대본의 맥락마다 구글 플로우 AI 장면이 전환되고 비교표와 단계별 카드가 음성에 맞춰 프레임 단위로 살아 움직입니다.",
        "stepsTitle": "바이브코딩 무인 쇼츠 제작 3단계 파이프라인",
        "steps": [
            {
                "badge": "STEP 01",
                "title": "Google Flow AI · 5개 장면 비주얼 생성",
                "detail": "대본의 5대 비트(훅·비교·단계·기준·요약)에 맞춘 고해상도 시네마 이미지 자동 생성",
            },
            {
                "badge": "STEP 02",
                "title": "뉴럴 음성 합성 & 문장별 타임스탬프 추출",
                "detail": "문장 단위 음성 길이를 밀리초 단위로 계측해 30fps 프레임 타임라인에 자동 매핑",
            },
            {
                "badge": "STEP 03",
                "title": "Hypit SVML · 모션그래픽 & 자막 통합 빌드",
                "detail": "상단 AI 시네마 뷰포트, 중단 인터랙티브 카드, 하단 싱크 자막을 1080x1920 MP4로 렌더링",
            },
        ],
        "ruleBadge": "시청 지속시간을 끌어올리는 3단 분할 레이아웃 공식",
        "ruleTitle": "상단 시네마 · 중단 인포그래픽 · 하단 자막,\n시선이 멈출 틈을 주지 마세요",
        "ruleDesc": "상단에서는 구글 플로우 AI 장면이 줌인되며 몰입감을 주고, 중단에서는 비교표와 체크리스트가 순차 등장해 정보 밀도를 완성합니다.",
        "rulePill1": "상단 뷰포트: 5개 씬 Ken Burns 모션 & 크로스페이드",
        "rulePill2": "중·하단 스테이지: 음성 동기화 비교 카드 & 가라오케 자막",
        "closingTitle": "고밀도 자동화 쇼츠 제작 3대 체크리스트",
        "check1": "단일 배경 금지 · 대본 비트별 5개 이상 AI 장면 전환",
        "check2": "음성 길이 기반 30fps 프레임 단위 카드·자막 정밀 싱크",
        "check3": "쇼츠 하단에서 커뮤니티 게시물·블로그 원문으로 퍼널 연결",
        "ctaBanner": "윤랩 자동화 연구소 게시물 탭에서 SVML 템플릿과 자동화 코드를 확인하세요",
        "segments": [
            {
                "highlight": "HOOK · 쇼츠 1편 만드는 데 아직도 3시간씩 쓰시나요?",
                "text": "유튜브 쇼츠 한 편 만들려고 아직도 영상 편집 프로그램에서 타임라인을 일일이 자르고 자막을 맞추고 계신가요?",
            },
            {
                "highlight": "CORE · 바이브코딩으로 완성하는 무인 쇼츠 스튜디오",
                "text": "이제는 코딩을 한 줄도 몰라도 바이브코딩과 구글 플로우 AI를 결합해 방송국 수준의 인포그래픽 쇼츠를 자동으로 렌더링할 수 있습니다.",
            },
            {
                "highlight": "PROBLEM · 배경 1장짜리 양산형 쇼츠가 망하는 이유",
                "text": "기존의 공장식 쇼츠들은 어두운 정지 이미지 한 장 위에 글자만 바꿔 띄우기 때문에 시청자가 3초 만에 이탈해 버립니다.",
            },
            {
                "highlight": "SOLUTION · Google Flow 5-씬 시네마 + SVML 모션",
                "text": "반면 윤랩의 코드 기반 비디오 엔진은 대본의 다섯 가지 흐름에 맞춰 구글 플로우 AI 장면과 모션 그래픽 카드를 동시에 전환합니다.",
            },
            {
                "highlight": "STEP 01 · Google Flow AI로 비트별 맞춤 장면 생성",
                "text": "첫 단계로 대본의 도입 훅, 전후 비교, 실행 단계, 핵심 지표, 최종 요약에 어울리는 다섯 장의 시네마 비주얼을 구글 플로우로 생성합니다.",
            },
            {
                "highlight": "STEP 02 · 음성 타임스탬프 계측 & 30fps 프레임 매핑",
                "text": "둘째, 뉴럴 음성 합성으로 문장별 오디오를 생성한 뒤 정확한 발화 시각을 추출해 30프레임 타임라인에 자동으로 꽂아 넣습니다.",
            },
            {
                "highlight": "STEP 03 · Hypit SVML 컴파일러로 1080p MP4 빌드",
                "text": "셋째, 하이핏 SVML 엔진이 상단 시네마 뷰포트와 중단 인터랙티브 카드, 하단 자막 바를 결합해 풀 HD 영상을 한 번에 뽑아냅니다.",
            },
            {
                "highlight": "LAYOUT · 이탈률을 잡는 3단 분할 시각 아키텍처",
                "text": "핵심은 화면 상단에서 생생한 AI 비주얼이 역동적으로 움직이는 동안, 중단에서는 핵심 숫자와 비교표가 음성에 맞춰 딱딱 떨어지는 것입니다.",
            },
            {
                "highlight": "FUNNEL · 쇼츠 시청자를 블로그·커뮤니티로 전환",
                "text": "이렇게 제작된 고밀도 쇼츠는 시청 지속시간을 높일 뿐 아니라, 채널 게시물과 전문 기술 블로그로 트래픽을 보내는 강력한 엔진이 됩니다.",
            },
            {
                "highlight": "FINAL · 3대 제작 공식 & SVML 설계도 확인 안내",
                "text": "구글 플로우 다중 씬, 프레임 정밀 싱크, 3단 레이아웃 세 가지를 기억하시고 채널 게시물 탭에서 전체 자동화 설계도를 확인해 보세요.",
            },
        ],
    },
]


def _probe_duration(media_path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        text=True,
    ).strip()
    return float(out)


def _generate_bgm_wav(
    out_wav: Path,
    duration_sec: float,
    theme_mode: str = "tech-cyber",
    sample_rate: int = 48000,
) -> None:
    total_samples = int(duration_sec * sample_rate)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        buf = bytearray()
        for i in range(total_samples):
            t = i / sample_rate
            if theme_mode == "senior-editorial":
                # Warm Major Piano/Bell Voicing (C - G - Am - F)
                chord_idx = int(t // 4.0) % 4
                roots = [261.63, 196.00, 220.00, 174.61]
                r = roots[chord_idx]
                note_phase = t % 1.0
                env = math.exp(-2.2 * note_phase)
                pad = (
                    0.42 * math.sin(2.0 * math.pi * r * t)
                    + 0.28 * math.sin(2.0 * math.pi * (r * 1.2599) * t)
                    + 0.20 * math.sin(2.0 * math.pi * (r * 1.4983) * t)
                ) * (0.55 + 0.45 * env)
                sample = max(-0.8, min(0.8, pad * 0.42))
            elif theme_mode == "vibe-terminal":
                # Upbeat Synthwave / Lo-Fi Code Pulse (120 BPM)
                chord_idx = int(t // 3.0) % 4
                roots = [146.83, 196.00, 220.00, 164.81]
                r = roots[chord_idx]
                arp_step = int(t * 4.0) % 4
                arp_mult = [1.0, 1.25, 1.5, 2.0][arp_step]
                pad = (
                    0.34 * math.sin(2.0 * math.pi * r * t)
                    + 0.24 * math.sin(2.0 * math.pi * (r * 1.5) * t)
                    + 0.22 * math.sin(2.0 * math.pi * (r * arp_mult) * t)
                )
                pulse = 0.50 + 0.50 * math.sin(2.0 * math.pi * 2.0 * t)
                sample = max(-0.8, min(0.8, pad * pulse * 0.46))
            else:
                # Tech-Cyber Deep Architecture Synth
                chord_idx = int(t // 4.0) % 4
                roots = [220.0, 174.61, 261.63, 196.00]
                r = roots[chord_idx]
                pad = (
                    0.35 * math.sin(2.0 * math.pi * r * t)
                    + 0.25 * math.sin(2.0 * math.pi * (r * 1.25) * t)
                    + 0.20 * math.sin(2.0 * math.pi * (r * 1.5) * t)
                )
                pulse = 0.55 + 0.45 * math.sin(2.0 * math.pi * 1.5 * t)
                sample = max(-0.8, min(0.8, pad * pulse * 0.45))
            s16 = int(sample * 32767)
            buf.extend(struct.pack("<hh", s16, s16))
        wf.writeframes(bytes(buf))


async def _synthesize_segments(spec: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    seg_dir = work_dir / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    voice = spec["voice"]
    rate = spec.get("rate", "+24%")

    script_sig = hashlib.sha256(
        json.dumps(
            {"voice": voice, "rate": rate, "segments": spec["segments"], "target_cap": 57.2},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    timing_cache = work_dir / "timing.json"
    narration_wav = work_dir / "assets" / "narration.wav"
    bgm_wav = work_dir / "assets" / "bgm.wav"
    if timing_cache.exists() and narration_wav.exists():
        cached = json.loads(timing_cache.read_text(encoding="utf-8"))
        if cached.get("script_sig") == script_sig:
            _generate_bgm_wav(bgm_wav, cached["duration_sec"] + 1.0, spec.get("themeMode", "tech-cyber"))
            cached["narration_wav"] = narration_wav
            cached["bgm_wav"] = bgm_wav
            return cached

    seg_wavs: list[Path] = []
    seg_starts_sec: list[float] = []
    cursor_sec = 0.20

    lead_wav = seg_dir / "lead.wav"
    pause_wav = seg_dir / "pause.wav"
    tail_wav = seg_dir / "tail.wav"
    for p, dur in [(lead_wav, 0.20), (pause_wav, 0.16), (tail_wav, 0.55)]:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                f"{dur:.3f}",
                "-c:a",
                "pcm_s16le",
                str(p),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    concat_list: list[Path] = [lead_wav]
    for idx, seg in enumerate(spec["segments"]):
        mp3_path = seg_dir / f"seg_{idx:02d}.mp3"
        wav_path = seg_dir / f"seg_{idx:02d}.wav"
        if not wav_path.exists():
            communicate = edge_tts.Communicate(seg.get("tts") or seg["text"], voice, rate=rate)
            await communicate.save(str(mp3_path))
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(mp3_path),
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-af",
                    "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_silence=0.08:start_threshold=-45dB,areverse",
                    "-c:a",
                    "pcm_s16le",
                    str(wav_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        dur = _probe_duration(wav_path)
        seg_starts_sec.append(cursor_sec)
        seg_wavs.append(wav_path)
        concat_list.append(wav_path)
        concat_list.append(pause_wav)
        cursor_sec += dur + 0.16

    concat_list.append(tail_wav)
    concat_txt = seg_dir / "concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in concat_list),
        encoding="utf-8",
    )

    narration_wav.parent.mkdir(parents=True, exist_ok=True)
    raw_narration = seg_dir / "raw_narration.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(raw_narration),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    raw_dur = _probe_duration(raw_narration)
    if raw_dur > 57.6:
        tempo_ratio = min(1.35, raw_dur / 57.2)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(raw_narration),
                "-af",
                f"atempo={tempo_ratio:.5f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(narration_wav),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        seg_starts_sec = [round(s / tempo_ratio, 3) for s in seg_starts_sec]
    else:
        shutil.copy2(raw_narration, narration_wav)

    exact_duration = _probe_duration(narration_wav)
    total_frames = int(math.floor(exact_duration * 30.0))
    _generate_bgm_wav(bgm_wav, exact_duration + 1.0, spec.get("themeMode", "tech-cyber"))

    result = {
        "script_sig": script_sig,
        "narration_wav": narration_wav,
        "bgm_wav": bgm_wav,
        "duration_sec": exact_duration,
        "total_frames": total_frames,
        "seg_starts_sec": seg_starts_sec,
        "seg_starts_frames": [max(1, min(total_frames - 5, int(round(s * 30.0)))) for s in seg_starts_sec],
    }
    timing_cache.write_text(
        json.dumps(
            {
                "script_sig": script_sig,
                "duration_sec": exact_duration,
                "total_frames": total_frames,
                "seg_starts_sec": seg_starts_sec,
                "seg_starts_frames": result["seg_starts_frames"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


def _xml_escape(val: str) -> str:
    return (
        str(val)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _write_hypit_production_files(spec: dict[str, Any], prod_dir: Path, timing: dict[str, Any]) -> dict[str, Path]:
    assets_out = prod_dir / "assets"
    assets_out.mkdir(parents=True, exist_ok=True)

    for fname in ("malgunbd.ttf", "malgun.ttf"):
        src_font = ASSETS_DIR / fname
        dst_font = assets_out / fname
        if not dst_font.exists():
            shutil.copy2(src_font, dst_font)

    # Copy all 5 Google Flow scene images into production assets
    brolls = spec["brolls"]
    for idx, bname in enumerate(brolls, start=1):
        src_img = FLOW_SCENES_DIR / bname
        if not src_img.exists():
            # Fallback to broll_frames if needed
            fallback_candidates = list((ASSETS_DIR / "broll_frames").glob("*.jpg"))
            src_img = fallback_candidates[(idx - 1) % len(fallback_candidates)]
        dst_img = assets_out / f"beat{idx}.jpg"
        shutil.copy2(src_img, dst_img)

    total_frames = timing["total_frames"]
    s_frames = timing["seg_starts_frames"]

    beat_compare_f = s_frames[2]
    beat_steps_f = s_frames[4]
    step1_f = s_frames[4]
    step2_f = s_frames[5]
    step3_f = s_frames[6]
    beat_rule_f = s_frames[7]
    beat_closing_f = s_frames[9]

    instants_xml = [
        f'    <time:Instant id="beat-compare" at="{beat_compare_f}f"/>',
        f'    <time:Instant id="beat-steps" at="{beat_steps_f}f"/>',
        f'    <time:Instant id="step-1-at" at="{step1_f}f"/>',
        f'    <time:Instant id="step-2-at" at="{step2_f}f"/>',
        f'    <time:Instant id="step-3-at" at="{step3_f}f"/>',
        f'    <time:Instant id="beat-rule" at="{beat_rule_f}f"/>',
        f'    <time:Instant id="beat-closing" at="{beat_closing_f}f"/>',
    ]
    for idx, f_idx in enumerate(s_frames):
        instants_xml.append(f'    <time:Instant id="cap-{idx}-at" at="{f_idx}f"/>')

    steps_xml = []
    for idx, st in enumerate(spec["steps"]):
        steps_xml.append(
            f'    <shorts:Step id="step-{idx+1}" badge="{_xml_escape(st["badge"])}" '
            f'title="{_xml_escape(st["title"])}" detail="{_xml_escape(st["detail"])}" '
            f'at={{animation.step-{idx+1}-at}}/>'
        )

    captions_xml = []
    for idx, seg in enumerate(spec["segments"]):
        captions_xml.append(
            f'    <shorts:Caption id="cap-{idx+1}" highlight="{_xml_escape(seg["highlight"])}" '
            f'text="{_xml_escape(seg["text"])}" at={{animation.cap-{idx}-at}}/>'
        )

    sc = spec.get("sceneCaptions") or [
        "SCENE 01 · 핵심 훅 & 실측 지표",
        "SCENE 02 · 기존 방식 vs 자동화 비교",
        "SCENE 03 · 3단계 실행 파이프라인",
        "SCENE 04 · 핵심 수익·성능 기준선",
        "SCENE 05 · 실전 적용 3대 체크리스트",
    ]

    theme_mode = spec.get("themeMode", "tech-cyber")
    film_bg = "#F4F1EA" if theme_mode == "senior-editorial" else ("#080514" if theme_mode == "vibe-terminal" else "#040814")

    svml_content = f"""<?svml using="@hypit/markup@1"?>
<svml>
  <import as="time" from="@hypit/timeline-author@1"/>
  <import as="spatial" from="@hypit/spatial@1"/>
  <import as="media" from="@hypit/media@1"/>
  <import as="mediaop" from="@hypit/media-operations@1"/>
  <import as="audio" from="@hypit/audio-track@1"/>
  <import as="shorts" from="@barolab/shorts-scene@1"/>
  <import as="film" from="@hypit/film@1"/>
  <import as="html" from="@hypit/html-video@1"/>
  <import as="style" source="./look.svs"/>

  <time:Clock id="clock" frame-rate="30"/>
  <time:Timeline id="animation" clock={{clock}} end="{total_frames}f">
{chr(10).join(instants_xml)}
  </time:Timeline>

  <spatial:Canvas id="canvas" width="1080" height="1920"/>

  <media:Font id="kr-bold-face" src="./assets/malgunbd.ttf" weight="700" style="normal"/>
  <media:Font id="kr-reg-face" src="./assets/malgun.ttf" weight="400" style="normal"/>
  <media:FontStack id="font-bold" primary={{kr-bold-face}}><media:Fallback font={{kr-reg-face}}/></media:FontStack>
  <media:FontStack id="font-regular" primary={{kr-reg-face}}><media:Fallback font={{kr-bold-face}}/></media:FontStack>

  <media:Image id="broll1" src="./assets/beat1.jpg"/>
  <media:Image id="broll2" src="./assets/beat2.jpg"/>
  <media:Image id="broll3" src="./assets/beat3.jpg"/>
  <media:Image id="broll4" src="./assets/beat4.jpg"/>
  <media:Image id="broll5" src="./assets/beat5.jpg"/>
  <media:Audio id="voice-raw" src="./assets/narration.wav"/>
  <media:Audio id="bgm-raw" src="./assets/bgm.wav"/>

  <mediaop:Normalize id="voice-media" source={{voice-raw}} video="none" audio="default" span-authority="audio" clock={{clock}}/>
  <mediaop:Normalize id="bgm-media" source={{bgm-raw}} video="none" audio="default" span-authority="audio" clock={{clock}}/>

  <shorts:Scene id="scene"
    timeline={{animation.timeline}}
    within={{canvas.bounds}}
    during={{animation.window}}
    font-bold={{font-bold}}
    font-regular={{font-regular}}
    bg-beat1={{broll1}}
    bg-beat2={{broll2}}
    bg-beat3={{broll3}}
    bg-beat4={{broll4}}
    bg-beat5={{broll5}}
    beat-compare={{animation.beat-compare}}
    beat-steps={{animation.beat-steps}}
    beat-rule={{animation.beat-rule}}
    beat-closing={{animation.beat-closing}}
    theme-mode="{_xml_escape(theme_mode)}"
    channel-name="{_xml_escape(spec['channelName'])}"
    category-pill="{_xml_escape(spec['categoryPill'])}"
    accent-color="{_xml_escape(spec['accentColor'])}"
    scene1-caption="{_xml_escape(sc[0])}"
    scene2-caption="{_xml_escape(sc[1])}"
    scene3-caption="{_xml_escape(sc[2])}"
    scene4-caption="{_xml_escape(sc[3])}"
    scene5-caption="{_xml_escape(sc[4])}"
    hook-badge="{_xml_escape(spec['hookBadge'])}"
    hook-stat="{_xml_escape(spec['hookStat'])}"
    hook-unit="{_xml_escape(spec['hookUnit'])}"
    hook-title="{_xml_escape(spec['hookTitle'])}"
    hook-sub="{_xml_escape(spec['hookSub'])}"
    compare-title="{_xml_escape(spec['compareTitle'])}"
    wrong-label="{_xml_escape(spec['wrongLabel'])}"
    wrong-title="{_xml_escape(spec['wrongTitle'])}"
    wrong-desc="{_xml_escape(spec['wrongDesc'])}"
    right-label="{_xml_escape(spec['rightLabel'])}"
    right-title="{_xml_escape(spec['rightTitle'])}"
    right-desc="{_xml_escape(spec['rightDesc'])}"
    steps-title="{_xml_escape(spec['stepsTitle'])}"
    rule-badge="{_xml_escape(spec['ruleBadge'])}"
    rule-title="{_xml_escape(spec['ruleTitle'])}"
    rule-desc="{_xml_escape(spec['ruleDesc'])}"
    rule-pill1="{_xml_escape(spec['rulePill1'])}"
    rule-pill2="{_xml_escape(spec['rulePill2'])}"
    closing-title="{_xml_escape(spec['closingTitle'])}"
    check1="{_xml_escape(spec['check1'])}"
    check2="{_xml_escape(spec['check2'])}"
    check3="{_xml_escape(spec['check3'])}"
    cta-banner="{_xml_escape(spec['ctaBanner'])}">
{chr(10).join(steps_xml)}
{chr(10).join(captions_xml)}
  </shorts:Scene>

  <audio:Track id="voice-track" timeline={{animation.timeline}}>
    <audio:Clip id="voice-clip" source={{voice-media.media}} during={{animation.window}} gain="1"/>
  </audio:Track>

  <audio:Track id="bgm-track" timeline={{animation.timeline}}>
    <audio:Clip id="bgm-clip" source={{bgm-media.media}} during={{animation.window}} gain="0.06" fade-in="15f" fade-out="25f"/>
  </audio:Track>

  <film:Film id="main" canvas={{canvas.canvas}} timeline={{animation.timeline}} appearance={{style.film.main}}>
    <film:Track source={{scene.visual}}/>
    <film:Track source={{voice-track.audio}}/>
    <film:Track source={{bgm-track.audio}}/>
  </film:Film>

  <html:Video id="final" composition={{main.composition}} timeline={{animation.timeline}}/>
</svml>
"""

    svs_content = f"""<?svml using="@hypit/recipe@1"?>
<sheet version="1">
  film.main {{ background: {film_bg}; }}
</sheet>
"""

    svrun_content = """<?svml using="@hypit/markup/run@1"?>
<svrun version="1">
  <author source="./main.svml"/>
  <target output="final.video"/>
</svrun>
"""

    svml_path = prod_dir / "main.svml"
    svs_path = prod_dir / "look.svs"
    svrun_path = prod_dir / "build.svrun"

    svml_path.write_text(svml_content, encoding="utf-8")
    svs_path.write_text(svs_content, encoding="utf-8")
    svrun_path.write_text(svrun_content, encoding="utf-8")

    return {"svml": svml_path, "svs": svs_path, "svrun": svrun_path}


def _run_hypit_build_and_export(spec: dict[str, Any], prod_dir: Path, timing: dict[str, Any]) -> dict[str, Any]:
    part = spec["part"]
    slug = spec["slug"]
    svrun_rel = f"productions/{slug}/build.svrun"
    hypit_cmd = shutil.which("hypit.cmd") or shutil.which("hypit") or "hypit.cmd"

    proc = subprocess.run(
        [hypit_cmd, "build", svrun_rel, "--runtime", "hypit.runtime.json", "--follow"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"hypit build failed for {slug}:\n{proc.stdout}\n{proc.stderr}")

    import re
    m = re.search(r"(bld_[A-Za-z0-9_]+)", proc.stdout)
    if not m:
        raise RuntimeError(f"Could not parse Build ID from hypit output:\n{proc.stdout}")
    build_id = m.group(1)

    out_mp4 = RENDERS_DIR / f"svml_short_part{part}.mp4"
    out_thumb = RENDERS_DIR / f"svml_short_part{part}_thumb.png"
    out_svml = RENDERS_DIR / f"svml_short_part{part}.svml"
    out_mp3 = RENDERS_DIR / f"svml_short_part{part}.mp3"

    if out_mp4.exists():
        out_mp4.unlink()

    subprocess.run(
        [hypit_cmd, "get", build_id, "--output", "final.video", "--to", str(out_mp4)],
        cwd=str(PROJECT_ROOT),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    shutil.copy2(prod_dir / "main.svml", out_svml)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(prod_dir / "assets" / "narration.wav"), "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "2.0", "-i", str(out_mp4), "-frames:v", "1", str(out_thumb)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    review_grid = prod_dir / "review_grid.jpg"
    if review_grid.exists():
        review_grid.unlink()
    subprocess.run(
        [
            hypit_cmd,
            "media",
            "tile",
            str(out_mp4),
            "--start",
            "1",
            "--end",
            str(max(10, int(timing["duration_sec"]) - 2)),
            "--every",
            "6",
            "--columns",
            "3",
            "--cell",
            "480",
            "--to",
            str(review_grid),
        ],
        cwd=str(PROJECT_ROOT),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return {
        "part": part,
        "slug": slug,
        "buildId": build_id,
        "title": spec["title"],
        "channel": spec["channel"],
        "channelName": spec["channelName"],
        "durationSec": round(timing["duration_sec"], 2),
        "totalFrames": timing["total_frames"],
        "mp4Path": str(out_mp4),
        "mp4Url": f"/data/public/youtube_renders/{out_mp4.name}",
        "thumbUrl": f"/data/public/youtube_renders/{out_thumb.name}",
        "svmlUrl": f"/data/public/youtube_renders/{out_svml.name}",
        "fileSizeBytes": out_mp4.stat().st_size,
        "audioEngine": f"edge_tts ({spec['voice']}) + @hypit/audio-track@1",
        "renderEngine": "Google Flow Nano Banana 2.1 (5 Scenes) + @hypit/hypit@0.3.1",
        "reviewGrid": str(review_grid),
    }


async def prepare_all(run_build: bool = True) -> list[dict[str, Any]]:
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for spec in SHORTS_SPECS:
        prod_dir = PRODUCTIONS_DIR / spec["slug"]
        prod_dir.mkdir(parents=True, exist_ok=True)
        timing = await _synthesize_segments(spec, prod_dir)
        paths = _write_hypit_production_files(spec, prod_dir, timing)
        if run_build:
            built = _run_hypit_build_and_export(spec, prod_dir, timing)
            summary.append(built)
        else:
            summary.append(
                {
                    "part": spec["part"],
                    "slug": spec["slug"],
                    "duration_sec": round(timing["duration_sec"], 2),
                    "total_frames": timing["total_frames"],
                    "svml": str(paths["svml"]),
                    "svrun": str(paths["svrun"]),
                }
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    asyncio.run(prepare_all(run_build=True))

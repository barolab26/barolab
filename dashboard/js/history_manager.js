/**
 * BaroLab Posting History & Daily Quota Rollover Manager
 * (c) 2026 BaroLab Master Hub
 * 
 * 1. 매일 00:00 KST 날짜 변경 감지 시 전일(Yesterday) 발행 실적 자동 아카이빙 영구 보존
 * 2. 당일(Today) 신규 23편 할당량(CF 16편 + 네이버 7편) 자동 초기화 및 카운트 시작
 * 3. 날짜별 과거 발행 내역 조회 UI (모달) 공통 제공
 */

(function (window) {
  'use strict';

  const STORAGE_KEY = 'BAROLAB_POSTING_HISTORY_V1';
  const TODAY_KEY = 'BAROLAB_TODAY_DATE';
  const ACC4_RECLASSIFIED_POST = {
    logNo: '224437498045',
    title: '2026 직장인 연말정산 소득공제 엑셀 계산기 무료 서식 & 절세 꿀팁 4가지',
    url: 'https://blog.naver.com/adinfo0905/224437498045',
    sourcePublishedAt: '2026-10-11T00:00:00+09:00',
    accountingDate: '2026-10-10'
  };

  function getNaverAccountingDate(item) {
    const post = ACC4_RECLASSIFIED_POST;
    const exactPost = String(item.logNo || item.postId || '') === post.logNo ||
      String(item.url || item.publicUrl || '').includes('/adinfo0905/' + post.logNo);
    const sameAccount = item.accId === 'acc4' || item.blogId === 'adinfo0905';
    return exactPost || (sameAccount && (item.topic === post.title || item.title === post.title))
      ? post.accountingDate : null;
  }

  // User-directed accounting correction; retain the public source date separately.
  function reconcileNaverOct11Accounting() {
    const todayKey = 'naver_quota_2026-10-11';
    const yesterdayKey = 'naver_quota_2026-10-10';
    const marker = '_patchOct11Acc4V2';
    const originals = {};
    try {
      for (const key of [todayKey, yesterdayKey, STORAGE_KEY]) originals[key] = localStorage.getItem(key);
      const parse = (raw, fallback) => {
        if (raw === null) return fallback;
        const value = JSON.parse(raw);
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid accounting data');
        return value;
      };
      const today = parse(originals[todayKey], {});
      if (today[marker]) return;
      const yesterday = parse(originals[yesterdayKey], {});
      const store = parse(originals[STORAGE_KEY], getInitialHistory());
      const backupKey = 'naver_accounting_backup_224437498045_v1';
      if (localStorage.getItem(backupKey) === null) localStorage.setItem(backupKey, JSON.stringify(originals));
      const source = store['2026-10-11'] && store['2026-10-11'].naver;
      if (source) {
        source.items = source.items.filter(item => !getNaverAccountingDate(item) && item.id !== 'acc4_1');
        source.completed = source.items.length;
      }
      const day = store['2026-10-10'] || (store['2026-10-10'] = {
        date: '2026-10-10', label: '2026년 10월 10일 (토)',
        cf: { target: 16, completed: 0, items: [] }, naver: { target: 7, completed: 0, items: [] }
      });
      const naver = day.naver || (day.naver = { target: 7, completed: 0, items: [] });
      naver.items = naver.items.filter(item => !getNaverAccountingDate(item));
      naver.items.push({
        ...ACC4_RECLASSIFIED_POST, id: 'acc4_224437498045', accountNo: 4, accId: 'acc4',
        name: 'adinfo0905', siteTitle: '월급날 기록장', category: '정보 브릿지',
        schedule: '운영 집계: 10/10', status: '어제 발행으로 분류 (사용자 지정)'
      });
      naver.completed = naver.items.length;
      yesterday.acc4 = { ...yesterday.acc4, count: Math.max(Number(yesterday.acc4?.count) || 0, 1) };
      today.acc4 = { ...today.acc4, count: 0, lastTime: null, topic: '', reserveTime: '' };
      today[marker] = true;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
      localStorage.setItem(yesterdayKey, JSON.stringify(yesterday));
      localStorage.setItem(todayKey, JSON.stringify(today));
    } catch (error) {
      for (const [key, raw] of Object.entries(originals)) {
        try { raw === null ? localStorage.removeItem(key) : localStorage.setItem(key, raw); } catch (_) { }
      }
      console.warn('[HistoryManager] Naver accounting correction failed; original records retained:', error);
    }
  }

  // 한국 표준시(KST) 기준 날짜 문자열 (YYYY-MM-DD) 반환
  function getKSTDateString(offsetDays = 0) {
    const now = new Date();
    // UTC + 9
    const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
    const kstTime = new Date(utc + (9 * 3600000) + (offsetDays * 86400000));
    const y = kstTime.getFullYear();
    const m = String(kstTime.getMonth() + 1).padStart(2, '0');
    const d = String(kstTime.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  // 기본 히스토리 데이터 구조 초기화
  function getInitialHistory() {
    return {
      "2026-10-09": {
        date: "2026-10-09",
        label: "2026년 10월 9일 (금)",
        cf: {
          target: 16,
          completed: 16,
          items: [
            { id: 1, domain: "must-good.com", name: "MustGood", category: "금융 · 혜택", time: "17:02", title: "최대 4.5% 우대금리에 2%대 대출 연계까지! 2026 청년 주택드림 청약통장 가입 조건 및 전환 방법 총정리", url: "https://www.must-good.com/%EC%B5%9C%EB%8C%80-45-%EC%9A%B0%EB%8C%80%EA%B8%88%EB%A6%AC%EC%97%90-2%EB%8C%80-%EB%8C%80%EC%B6%9C-%EC%97%B0%EA%B3%84%EA%B9%8C%EC%A7%80-2026-%EC%B2%AD%EB%85%84-%EC%A3%BC%ED%83%9D%EB%93%9C%EB%A6%BC-%EC%B2%AD%EC%95%BD%ED%86%B5%EC%9E%A5-%EA%B0%80%EC%9E%85-%EC%A1%B0%EA%B1%B4-%EB%B0%8F-%EC%A0%84%ED%99%98-%EB%B0%A9%EB%B2%95-%EC%B4%9D%EC%A0%95%EB%A6%AC" },
            { id: 2, domain: "baronote.kr", name: "바로노트", category: "소비 · 절약", time: "17:21", title: "탄 냄비 버리지 마세요! 베이킹소다와 식초로 5분 만에 새 냄비 만드는 탄 자국 완벽 제거법", url: "https://www.baronote.kr/burned-pot-cleaning-baking-soda-vinegar-guide-2" },
            { id: 3, domain: "justinfo.co.kr", name: "저스트인포", category: "금융 · 혜택", time: "17:24", title: "교통비 최대 53% 환급! 2026 K-패스(K-Pass) 교통카드 신청 자격 및 카드사별 혜택 총정리", url: "https://www.justinfo.co.kr/2026-k-pass-transport-card-benefit-guide-2" },
            { id: 4, domain: "topnote.kr", name: "탑노트", category: "IT · 가전", time: "17:28", title: "인터넷 속도 2배 빨라지는 크롬 캐시·쿠키 삭제 단축키 및 특정 사이트 데이터 정리법", url: "https://www.topnote.kr/chrome-cache-cookie-clear-shortcuts-guide-2" },
            { id: 5, domain: "meganote.kr", name: "메가노트", category: "이슈 · 지식", time: "17:31", title: "저장공간 부족 경고 떴을 때! 스마트폰 용량 10GB 단 1분 만에 확보하는 카카오톡 캐시 정리 꿀팁", url: "https://www.meganote.kr/smartphone-storage-space-cleanup-guide-2" },
            { id: 6, domain: "smilenote.kr", name: "스마일노트", category: "건강 · 라이프", time: "17:34", title: "보약보다 좋다? 아침 공복 따뜻한 물 한 잔의 놀라운 5가지 건강 효능과 올바른 음용법", url: "https://www.smilenote.kr/warm-water-morning-empty-stomach-health-benefits-3" },
            { id: 7, domain: "healthcox.com", name: "HealthCox", category: "의학 · 운동", time: "17:37", title: "하루 5분으로 목 통증 탈출! 거북목·일자목 교정 스트레칭과 바른 자세 루틴 총정리", url: "https://www.healthcox.com/forward-head-posture-correction-exercises" },
            { id: 8, domain: "maxnote.kr", name: "맥스노트", category: "생산성 · 도구", time: "17:40", title: "칼퇴를 부르는 업무 효율 3배 상승! 직장인을 위한 윈도우 11 필수 단축키 모음", url: "https://www.maxnote.kr/windows-11-essential-shortcuts-productivity-guide-2" },
            { id: 9, domain: "must-joy.com", name: "머스트조이", category: "문화 · 취미", time: "17:43", title: "주말 데이트·가족 나들이 명소! 국립중앙박물관 상설전시 무료 관람 꿀팁 및 추천 동선", url: "https://www.must-joy.com/national-museum-of-korea-free-admission-guide" },
            { id: 10, domain: "tripmarvel.com", name: "TripMarvel", category: "국내외 여행", time: "17:45", title: "붉게 물든 절경 속으로! 2026 전국 가을 단풍 명소 베스트 5 및 절정 시기 총정리", url: "https://www.tripmarvel.com/autumn-foliage-best-destinations-korea" },
            { id: 11, domain: "must-pick.com", name: "MustPick", category: "쇼핑 · 추천", time: "17:48", title: "가전제품 구매비 최대 30만 원 환급! 으뜸효율 가전제품 환급 사업 신청 대상 및 방법", url: "https://www.must-pick.com/energy-efficient-home-appliances-refund-guide" },
            { id: 12, domain: "woorinote.kr", name: "우리노트", category: "부동산 · 경제", time: "17:51", title: "소중한 보증금 100% 지키기! HUG 주택도시보증공사 전세보증금 반환보증 가입 조건 및 서류", url: "https://www.woorinote.kr/hug-jeonse-deposit-guarantee-insurance-guide" },
            { id: 13, domain: "daynote.kr", name: "데이노트", category: "일상 · 꿀팁", time: "17:53", title: "과태료 30만 원 피하는 비법! 헷갈리는 올바른 분리수거 배출 방법 및 재활용 마크 총정리", url: "https://www.daynote.kr/proper-recycling-sorting-rules-guide" },
            { id: 14, domain: "nolplace.com", name: "Nolplace", category: "핫플 · 명소", time: "17:56", title: "로맨틱한 밤을 달린다! 연인과 함께 가기 좋은 서울 야경 드라이브 코스 추천 BEST 4", url: "https://www.nolplace.com/seoul-night-view-drive-courses-recommendation" },
            { id: 15, domain: "soulnote.kr", name: "소울노트", category: "도서 · 자기계발", time: "17:58", title: "작심삼일 끝내는 갓생 비법! 실패 없는 하루 5분 미라클 모닝 루틴과 습관 형성 팁", url: "https://www.soulnote.kr/miracle-morning-routine-success-guide" },
            { id: 16, domain: "joynote.kr", name: "조이노트", category: "반려동물 · 취미", time: "18:01", title: "강아지가 머리를 흔든다면 의심! 반려견 귀 청소 주기와 외이도염 예방 관리법 총정리", url: "https://www.joynote.kr/dog-ear-cleaning-otitis-prevention-guide" }
          ]
        },
        naver: {
          target: 7,
          completed: 0,
          items: []
        }
      },
      "2026-10-08": {
        date: "2026-10-08",
        label: "2026년 10월 8일 (목)",
        cf: {
          target: 16,
          completed: 16,
          items: [
            { id: 1, domain: "must-good.com", name: "MustGood", category: "금융 · 혜택", time: "15:37", title: "내 돈인데 안 찾아간 지원금이 있다? 2026 숨은 정부지원금 찾기 (보조금24 원클릭 조회 및 신청 방법)", url: "https://www.must-good.com/2026-hidden-government-subsidy-inquiry-guide" },
            { id: 2, domain: "baronote.kr", name: "바로노트", category: "소비 · 절약", time: "16:10", title: "잠자고 있는 카드 포인트 현금으로 돌려받기! 2026 카드 포인트 통합조회 및 계좌 입금 방법", url: "https://www.baronote.kr/2026-card-point-integrated-inquiry-cashback-guide" },
            { id: 3, domain: "justinfo.co.kr", name: "저스트인포", category: "금융 · 혜택", time: "16:37", title: "동사무소 안 가도 된다! 2026 인감증명서 인터넷 무료 발급 방법 (정부24 온라인 신청 절차 총정리)", url: "https://www.justinfo.co.kr/2026-online-seal-certificate-issuance-guide" },
            { id: 4, domain: "topnote.kr", name: "탑노트", category: "IT · 가전", time: "10:30", title: "크롬 시크릿 모드 다운로드 기록과 방문 기록 보관 범위", url: "https://www.topnote.kr/chrome-incognito-download-history-scope" },
            { id: 5, domain: "meganote.kr", name: "메가노트", category: "이슈 · 지식", time: "11:00", title: "크롬 다운로드 위치 변경, 매번 저장 위치 확인 창 띄우는 법", url: "https://www.meganote.kr/chrome-download-location-ask-save-check" },
            { id: 6, domain: "smilenote.kr", name: "스마일노트", category: "건강 · 라이프", time: "11:30", title: "구글 드라이브 공유 권한 설정, 뷰어·댓글 작성자·편집자 차이", url: "https://www.smilenote.kr/google-drive-share-permissions-guide" },
            { id: 7, domain: "healthcox.com", name: "HealthCox", category: "의학 · 운동", time: "12:00", title: "오래 앉아 있는 시간 줄이는 법, 운동 시간과 알람 주기 추천", url: "https://www.healthcox.com/how-to-reduce-sitting-time-exercise-plan-and-alarm-cadence" },
            { id: 8, domain: "maxnote.kr", name: "맥스노트", category: "생산성 · 도구", time: "12:30", title: "윈도우 클립보드 검색 기록 지우기, 고정 항목 유지와 재부팅 차이", url: "https://www.maxnote.kr/windows-clipboard-pinned-history-clear-restart" },
            { id: 9, domain: "must-joy.com", name: "머스트조이", category: "문화 · 취미", time: "13:00", title: "Gmail 보관처리 삭제 차이, 받은편지함 정리와 검색 확인법", url: "https://www.must-joy.com/gmail-archive-vs-delete-inbox-guide" },
            { id: 10, domain: "tripmarvel.com", name: "TripMarvel", category: "국내외 여행", time: "13:30", title: "해외여행 eSIM 설치 시점, 출국 전 설치와 유효기간 시작 기준", url: "https://www.tripmarvel.com/esim-installation-timing-and-validity-guide" },
            { id: 11, domain: "must-pick.com", name: "MustPick", category: "쇼핑 · 추천", time: "14:00", title: "납세증명서 납부내역증명서 차이, 체납 유무 확인 서류 구분", url: "https://www.must-pick.com/tax-clearance-vs-payment-certificate-guide" },
            { id: 12, domain: "woorinote.kr", name: "우리노트", category: "부동산 · 경제", time: "14:30", title: "윈도우 11 클립보드 기록 지우기, 고정 항목 유지와 전체 삭제", url: "https://www.woorinote.kr/windows-11-clipboard-pinned-history-clear-guide" },
            { id: 13, domain: "daynote.kr", name: "데이노트", category: "일상 · 꿀팁", time: "15:00", title: "구글 드라이브 링크 공유 권한 설정, 일반 액세스 변경 확인법", url: "https://www.daynote.kr/google-drive-link-sharing-access-check" },
            { id: 14, domain: "nolplace.com", name: "Nolplace", category: "핫플 · 명소", time: "15:30", title: "국립공원 야영장 예약 대기 신청, 당첨 알림과 결제 기한", url: "https://www.nolplace.com/national-park-campsite-waiting-reservation-check" },
            { id: 15, domain: "soulnote.kr", name: "소울노트", category: "도서 · 자기계발", time: "16:00", title: "안드로이드 캐시 삭제와 데이터 삭제 차이, 저장공간 확보", url: "https://www.soulnote.kr/android-clear-cache-vs-app-data-guide" },
            { id: 16, domain: "joynote.kr", name: "조이노트", category: "반려동물 · 취미", time: "18:31", title: "집안 털 날림 해결! 반려견 환절기 털갈이 관리법과 빗질 주기 총정리", url: "https://www.joynote.kr/dog-molting-season-grooming-skin-care-guide" }
          ]
        },
        naver: {
          target: 7,
          completed: 1,
          items: [
            { id: 1, accId: "acc1", name: "soultin", siteTitle: "시니어브리프", category: "5060 연금·복지", schedule: "매일 10:00 (1일 1편)", time: "10:18", title: "2026년 국민연금 수령나이 총정리.. 출생연도별 나이표와 조기수령 득실 계산", status: "6단계 예약완료 (10:00)" }
          ]
        }
      }
    };
  }

  // 저장소 로드
  function loadHistoryStore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') return parsed;
      }
    } catch (e) {
      console.warn('[HistoryManager] LocalStorage load failed, using initial:', e);
    }
    const initial = getInitialHistory();
    saveHistoryStore(initial);
    return initial;
  }

  function saveHistoryStore(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (e) {
      console.error('[HistoryManager] LocalStorage save failed:', e);
    }
  }

  // 날짜 변경 체크 및 일일 자동 롤오버 (Rollover)
  function checkAndRolloverDaily() {
    const today = getKSTDateString(0);
    const lastActiveDate = localStorage.getItem(TODAY_KEY) || "2026-10-08";
    const store = loadHistoryStore();

    if (lastActiveDate !== today) {
      console.log(`[HistoryManager] 📅 날짜 변경 감지: ${lastActiveDate} -> ${today}`);
      
      // 1. 오늘 날짜 신규 엔트리가 없으면 생성 (초기화된 0건 상태)
      if (!store[today]) {
        store[today] = {
          date: today,
          label: `${today} (오늘)`,
          cf: {
            target: 16,
            completed: 0,
            items: [],
            sourceStatus: 'unknown'
          },
          naver: {
            target: 7,
            completed: 0,
            items: [],
            sourceStatus: 'unknown'
          }
        };
        saveHistoryStore(store);
      }

      // 2. 현재 활성 날짜 갱신
      localStorage.setItem(TODAY_KEY, today);
    }

    return {
      today,
      lastActiveDate,
      store
    };
  }

  // 오늘 날짜의 포스팅 실적 기록
  function recordPosting(platform, item) {
    if (platform === 'naver' && (item.source !== 'server-public-verification' || !window.NaverSchedule?.publicVerified(item))) return;
    const today = getKSTDateString(0);
    const store = loadHistoryStore();
    if (!store[today]) {
      store[today] = {
        date: today,
        label: `${today} (오늘)`,
        cf: { target: 16, completed: 0, items: [] },
        naver: { target: 7, completed: 0, items: [] }
      };
    }

    const targetList = store[today][platform];
    if (targetList) {
      // 중복 체크 (id 기준)
      const existingIdx = targetList.items.findIndex(it => it.id === item.id);
      if (existingIdx >= 0) {
        targetList.items[existingIdx] = item;
      } else {
        targetList.items.push(item);
      }
      targetList.completed = targetList.items.length;
      saveHistoryStore(store);
    }
  }

  // 오늘 날짜의 포스팅 실적 삭제 (체크 해제 시)
  function removePosting(platform, itemId) {
    if (platform === 'naver') return; // Public evidence is reconciled from the server, not a checkbox.
    const today = getKSTDateString(0);
    const store = loadHistoryStore();
    if (store[today] && store[today][platform]) {
      store[today][platform].items = store[today][platform].items.filter(it => it.id !== itemId);
      store[today][platform].completed = store[today][platform].items.length;
      saveHistoryStore(store);
    }
  }

  // 오늘 날짜 실적 통계 가져오기
  function getTodayStats() {
    const today = getKSTDateString(0);
    const store = loadHistoryStore();
    const entry = store[today] || {
      cf: { target: 16, completed: 0, items: [], sourceStatus: 'unknown' },
      naver: { target: 7, completed: 0, items: [], sourceStatus: 'unknown' }
    };
    const cfComp = (entry.cf && entry.cf.completed) || 0;
    const cfTgt = (entry.cf && entry.cf.target) || 16;
    const nvComp = (entry.naver && entry.naver.completed) || 0;
    const nvTgt = (entry.naver && entry.naver.target) || 7;
    return {
      date: today,
      cfCompleted: cfComp,
      cfTarget: cfTgt,
      cfSourceStatus: entry.cf?.sourceStatus || 'unknown',
      cfSyncedAt: entry.cf?.syncedAt,
      cfActive: entry.cf?.active || null,
      naverCompleted: nvComp,
      naverReserved: (entry.naver && entry.naver.reserved) || 0,
      naverTarget: nvTgt,
      naverSourceStatus: entry.naver?.sourceStatus || 'unknown',
      naverActive: entry.naver?.active || null,
      totalCompleted: cfComp + nvComp,
      totalTarget: cfTgt + nvTgt,
      pct: Math.round(((cfComp + nvComp) / (cfTgt + nvTgt)) * 100)
    };
  }

  // 어제 날짜 실적 통계 가져오기
  function getYesterdayStats() {
    const yesterday = getKSTDateString(-1);
    const store = loadHistoryStore();
    const entry = store[yesterday] || store["2026-10-08"] || {
      cf: { target: 16, completed: 16, items: [] },
      naver: { target: 7, completed: 1, items: [] }
    };
    const cfComp = (entry.cf && entry.cf.completed) || 0;
    const cfTgt = (entry.cf && entry.cf.target) || 16;
    const nvComp = (entry.naver && entry.naver.completed) || 0;
    const nvTgt = (entry.naver && entry.naver.target) || 7;
    return {
      date: entry.date || yesterday,
      cfCompleted: cfComp,
      cfTarget: cfTgt,
      naverCompleted: nvComp,
      naverTarget: nvTgt,
      totalCompleted: cfComp + nvComp,
      totalTarget: cfTgt + nvTgt,
      pct: Math.round(((cfComp + nvComp) / (cfTgt + nvTgt)) * 100)
    };
  }

  // 과거 발행 내역 모달 렌더링
  function injectHistoryModal() {
    if (document.getElementById('barolab-history-modal')) return;

    const modalHtml = `
      <div id="barolab-history-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(15,23,42,0.65); z-index:9999; backdrop-filter:blur(3px); place-items:center;">
        <div style="background:white; border-radius:12px; width:92%; max-width:860px; max-height:88vh; display:flex; flex-direction:column; box-shadow:0 25px 50px -12px rgba(0,0,0,0.25); overflow:hidden; border:1px solid #e2e8f0;">
          <!-- Modal Header -->
          <div style="padding:16px 20px; background:#f8fafc; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <h3 style="margin:0; font-size:16px; font-weight:800; color:#0f172a; display:flex; align-items:center; gap:8px;">
                <span>📜 일자별 누적 발행 히스토리 & 보존 내역</span>
              </h3>
              <p style="margin:2px 0 0; font-size:11px; color:#64748b;">날짜가 변경되어도 과거에 발행 완료된 모든 포스팅 URL 및 기록이 안전하게 보존됩니다.</p>
            </div>
            <button onclick="window.BaroLabHistory.closeModal()" style="border:none; background:#f1f5f9; width:28px; height:28px; border-radius:6px; cursor:pointer; font-weight:700; color:#64748b;">✕</button>
          </div>

          <!-- Date Selector Tabs -->
          <div style="padding:10px 20px; background:#ffffff; border-bottom:1px solid #f1f5f9; display:flex; align-items:center; gap:8px; overflow-x:auto;" id="history-date-tabs">
            <!-- Dynamically Rendered Dates -->
          </div>

          <!-- Modal Body Content -->
          <div style="padding:16px 20px; overflow-y:auto; flex:1;" id="history-modal-body">
            <!-- Dynamically Rendered History Content -->
          </div>

          <!-- Modal Footer -->
          <div style="padding:12px 20px; background:#f8fafc; border-top:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; font-size:11px; color:#64748b;">
            <span>BaroLab Master Archiving Engine · KST</span>
            <button onclick="window.BaroLabHistory.closeModal()" style="padding:6px 14px; background:#0f172a; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">닫기</button>
          </div>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
  }

  function openHistoryModal(selectedDate) {
    injectHistoryModal();
    const modal = document.getElementById('barolab-history-modal');
    if (!modal) return;
    modal.style.display = 'grid';

    const store = loadHistoryStore();
    const dates = Object.keys(store).sort().reverse();
    const activeDate = selectedDate || dates[0];

    // Render Date Tabs
    const tabsContainer = document.getElementById('history-date-tabs');
    if (tabsContainer) {
      tabsContainer.innerHTML = dates.map(dt => {
        const isSelected = dt === activeDate;
        const data = store[dt];
        const cfCnt = data.cf ? data.cf.completed : 0;
        const nvCnt = data.naver ? data.naver.completed : 0;
        const total = cfCnt + nvCnt;
        const isToday = dt === getKSTDateString(0);

        return `
          <button onclick="window.BaroLabHistory.openModal('${dt}')" style="padding:6px 12px; border-radius:8px; font-size:11px; font-weight:700; cursor:pointer; border:1px solid ${isSelected ? '#0872ff' : '#e2e8f0'}; background:${isSelected ? '#eff6ff' : '#f8fafc'}; color:${isSelected ? '#1d4ed8' : '#475569'}; display:flex; align-items:center; gap:6px; white-space:nowrap;">
            <span>📅 ${dt} ${isToday ? '(오늘)' : '(보존)'}</span>
            <span style="background:${isSelected ? '#2563eb' : '#e2e8f0'}; color:${isSelected ? 'white' : '#64748b'}; padding:1px 6px; border-radius:10px; font-size:10px;">${total}편</span>
          </button>
        `;
      }).join('');
    }

    // Render Body Content
    const bodyContainer = document.getElementById('history-modal-body');
    if (bodyContainer) {
      const data = store[activeDate];
      if (!data) {
        bodyContainer.innerHTML = `<div style="text-align:center; padding:30px; color:#94a3b8;">해당 일자의 발행 기록이 없습니다.</div>`;
        return;
      }

      const cfItems = (data.cf && data.cf.items) || [];
      const nvItems = (data.naver && data.naver.items) || [];
      const cfTarget = (data.cf && data.cf.target) || 16;
      const nvTarget = (data.naver && data.naver.target) || 7;

      bodyContainer.innerHTML = `
        <!-- Summary Stats of Selected Date -->
        <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-bottom:16px;">
          <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#1d4ed8; font-weight:700;">CF 블로그 실적</div>
            <div style="font-size:18px; font-weight:800; color:#1e40af; margin-top:2px;">${cfItems.length} <small style="font-size:11px;">/ ${cfTarget}편</small></div>
            <div style="font-size:10px; color:#3b82f6;">${cfItems.length === cfTarget ? '✓ 100% 전원 완료' : '진행 완료 내역'}</div>
          </div>
          <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#15803d; font-weight:700;">네이버 블로그 실적</div>
            <div style="font-size:18px; font-weight:800; color:#166534; margin-top:2px;">${nvItems.length} <small style="font-size:11px;">/ ${nvTarget}편</small></div>
            <div style="font-size:10px; color:#22c55e;">${nvItems.length > 0 ? '✓ 스마트에디터 예약 세팅' : '대기 상태'}</div>
          </div>
          <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:11px; color:#475569; font-weight:700;">당일 합산 완료율</div>
            <div style="font-size:18px; font-weight:800; color:#0f172a; margin-top:2px;">${cfItems.length + nvItems.length} <small style="font-size:11px;">/ ${cfTarget + nvTarget}편</small></div>
            <div style="font-size:10px; color:#64748b;">${Math.round(((cfItems.length + nvItems.length) / (cfTarget + nvTarget)) * 100)}% 달성 기록</div>
          </div>
        </div>

        <!-- 1. Cloudflare Section -->
        <div style="margin-bottom:18px;">
          <h4 style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">
            <span>⚡ Cloudflare 16개 도메인 발행 내역 (${cfItems.length}건)</span>
            <span style="font-size:10px; color:#16a34a; font-weight:700;">HTTP 200 OK 무결성 검증됨</span>
          </h4>
          <div style="border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse; font-size:11.5px; text-align:left;">
              <thead style="background:#f8fafc; border-bottom:1px solid #e2e8f0;">
                <tr>
                  <th style="padding:6px 10px; width:36px; text-align:center;">No</th>
                  <th style="padding:6px 10px; width:110px;">블로그</th>
                  <th style="padding:6px 10px; width:100px;">도메인</th>
                  <th style="padding:6px 10px;">포스팅 제목</th>
                  <th style="padding:6px 10px; width:65px; text-align:center;">시간</th>
                  <th style="padding:6px 10px; width:75px; text-align:center;">링크</th>
                </tr>
              </thead>
              <tbody>
                ${cfItems.length > 0 ? cfItems.map(it => `
                  <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:6px 10px; text-align:center; color:#64748b; font-weight:700;">${it.id}</td>
                    <td style="padding:6px 10px; font-weight:700; color:#0f172a;">${it.name}</td>
                    <td style="padding:6px 10px; color:#475569;"><code>${it.domain}</code></td>
                    <td style="padding:6px 10px; color:#1e293b; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${it.title}">${it.title}</td>
                    <td style="padding:6px 10px; text-align:center; color:#64748b; font-size:10.5px;">${it.time || '--:--'}</td>
                    <td style="padding:6px 10px; text-align:center;">
                      <a href="${it.url}" target="_blank" style="display:inline-block; padding:2px 7px; background:#ecfdf5; color:#047857; border:1px solid #86efac; border-radius:4px; font-size:10px; text-decoration:none; font-weight:700;">글 보기 ↗</a>
                    </td>
                  </tr>
                `).join('') : `
                  <tr><td colspan="6" style="padding:16px; text-align:center; color:#94a3b8;">해당 일자에 완료된 CF 포스팅이 없습니다.</td></tr>
                `}
              </tbody>
            </table>
          </div>
        </div>

        <!-- 2. Naver Section -->
        <div>
          <h4 style="font-size:13px; font-weight:800; color:#0f172a; margin-bottom:8px; display:flex; align-items:center; justify-content:space-between;">
            <span>🟢 네이버 블로그 5개 계정 발행 내역 (${nvItems.length}건)</span>
            <span style="font-size:10px; color:#059669; font-weight:700;">스마트에디터 ONE 서식 및 예약 연동</span>
          </h4>
          <div style="border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse; font-size:11.5px; text-align:left;">
              <thead style="background:#f8fafc; border-bottom:1px solid #e2e8f0;">
                <tr>
                  <th style="padding:6px 10px; width:36px; text-align:center;">No</th>
                  <th style="padding:6px 10px; width:130px;">계정 / 블로그</th>
                  <th style="padding:6px 10px; width:95px;">발행 일정</th>
                  <th style="padding:6px 10px;">기획 포스팅 주제</th>
                  <th style="padding:6px 10px; width:110px; text-align:center;">상태</th>
                </tr>
              </thead>
              <tbody>
                ${nvItems.length > 0 ? nvItems.map(it => `
                  <tr style="border-bottom:1px solid #f1f5f9;">
                    <td style="padding:6px 10px; text-align:center; color:#64748b; font-weight:700;">${it.accountNo || it.id}</td>
                    <td style="padding:6px 10px; font-weight:700; color:#0f172a;">${it.accountNo || it.id}호기 ${it.name} (${it.siteTitle || ''})</td>
                    <td style="padding:6px 10px; color:#475569; font-size:10.5px;">${it.schedule}</td>
                    <td style="padding:6px 10px; color:#1e293b; max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${it.title}">${it.title}</td>
                    <td style="padding:6px 10px; text-align:center;">
                      <span style="display:inline-block; padding:2px 8px; background:#dcfce7; color:#15803d; border-radius:12px; font-size:10px; font-weight:700;">✓ ${it.displayStatus || it.status}</span>
                    </td>
                  </tr>
                `).join('') : `
                  <tr><td colspan="5" style="padding:16px; text-align:center; color:#94a3b8;">해당 일자에 완료된 네이버 포스팅이 없습니다.</td></tr>
                `}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }
  }

  function closeModal() {
    const modal = document.getElementById('barolab-history-modal');
    if (modal) modal.style.display = 'none';
  }

  // Pipeline results are shared across clients; local UI checkboxes are not the CF source of truth.
  async function syncCFPublications() {
    try {
      const [response, stateRes] = await Promise.all([
        fetch('/dashboard/data/cf/daily_schedule.json?t=' + Date.now(), { cache: 'no-store' }),
        fetch('/dashboard/data/cf/pipeline_state.json?t=' + Date.now(), { cache: 'no-store' }).catch(() => null)
      ]);
      if (!response.ok) throw new Error(`CF schedule HTTP ${response.status}`);
      const schedule = await response.json();
      const state = stateRes && stateRes.ok ? await stateRes.json().catch(() => null) : null;
      const today = getKSTDateString();
      if (!Array.isArray(schedule.items)) throw new Error('Invalid CF schedule');
      const store = loadHistoryStore();
      const day = store[today] || { date: today, label: `${today} (오늘)`, naver: { target: 7, completed: 0, items: [] } };
      const seen = new Set();
      const items = (schedule.date === today ? schedule.items : []).filter(item => {
        if (item.status !== 'published' || !/^https?:\/\//.test(item.publicUrl || '') || seen.has(item.publicUrl)) return false;
        seen.add(item.publicUrl);
        return true;
      }).map(item => ({ ...item, url: item.publicUrl, time: item.completedAt, source: 'server-schedule' }));
      let active = null;
      if (state && (state.date === today || state.scheduleDate === today) && ['processing', 'publishing'].includes(state.status) && state.executionState !== 'stopped') {
        active = {
          domain: state.domain || state.activeDomain || '',
          stageName: state.stageName || '작업 중',
          progressPct: Number(state.progressPct || 10),
          detailMessage: state.detailMessage || ''
        };
      }
      day.cf = { target: Number(schedule.total) || schedule.items.length, completed: items.length, items, active };
      day.cf.sourceStatus = schedule.date === today ? 'current' : 'waiting_for_today_schedule';
      day.cf.syncedAt = new Date().toISOString();
      store[today] = day;
      saveHistoryStore(store);
      window.dispatchEvent(new Event('barolab-publications-updated'));
    } catch (error) {
      const store = loadHistoryStore(), today = getKSTDateString();
      if (store[today]?.cf) {
        store[today].cf.sourceStatus = 'sync_failed';
        saveHistoryStore(store);
        window.dispatchEvent(new Event('barolab-publications-updated'));
      }
      console.warn('[HistoryManager] CF server publication sync failed:', error);
    }
  }

  async function syncNaverPublications() {
    try {
      const [response, liveRes] = await Promise.all([
        fetch('/pipeline_status.js?t=' + Date.now(), { cache: 'no-store' }),
        fetch('/api/mission-control', {cache:'no-store',signal:AbortSignal.timeout(2500)})
      ]);
      if (!response.ok || !liveRes.ok) throw new Error('Naver live snapshot unavailable');
      const text = await response.text();
      const live = (await liveRes.json()).naverLive || {};
      const runtime = live.workflow || null, journal = live.journal || null;
      // Parse the JSON assignment without executing a remote script.
      const match = text.match(/^\s*window\.__NAVER_PIPELINE_STATUS__\s*=\s*([\s\S]+?);?\s*$/);
      if (!match) throw new Error('Invalid Naver status');
      const status = JSON.parse(match[1]);
      const today = getKSTDateString(), key = `naver_quota_${today}`;
      if (!window.NaverSchedule) throw new Error('Naver publication adapter missing');
      await window.NaverSchedule.loadPublicEvidence();
      const items = window.NaverSchedule.publications(status, today);
      let reservedCount = 0;
      const reservedItems = [];
      let active = null;
      const quotas = Object.fromEntries(['acc1','acc2','acc3','acc4','acc5'].map(account => {
        const rows = items.filter(item => item.accId === account);
        const slots = window.NaverSchedule.resolve(status, account, today, journal, null, Date.now(), undefined, runtime);
        const resSlots = slots.filter(s => s.state === 'reserved');
        const procSlot = slots.find(s => s.state === 'processing');
        reservedCount += resSlots.length;
        const resMapped = resSlots.map(s => ({
          accId: account,
          time: s.time,
          actualTime: s.actualTime,
          reserveTime: s.info?.reserveTime || (today + ' ' + s.actualTime),
          title: s.info?.topic || '',
          label: s.label || '예약 완료 · 공개 예정'
        }));
        reservedItems.push(...resMapped);
        if (procSlot && !active) {
          active = {
            accId: account,
            account: runtime?.account || account,
            scheduledSlot: procSlot.time,
            actualTime: procSlot.actualTime,
            stageName: procSlot.info?.stageName || procSlot.label || '초안 작업 중',
            progressPct: Number(procSlot.info?.progressPct || 10)
          };
        }
        return [account, {
          count: rows.length,
          reserved: resSlots.length,
          reservedItems: resMapped,
          processing: procSlot ? { stageName: procSlot.info?.stageName || procSlot.label, progressPct: Number(procSlot.info?.progressPct || 10), actualTime: procSlot.actualTime } : null,
          items: rows,
          source: 'server-public-verification'
        }];
      }));
      const store = loadHistoryStore(), entry = store[today] || { date: today, label: today, cf: { target: 16, completed: 0, items: [] } };
      entry.naver = { target: 7, completed: items.length, reserved: reservedCount, reservedItems, active, items, sourceStatus: 'current', syncedAt: new Date().toISOString() };
      store[today] = entry; saveHistoryStore(store);
      localStorage.setItem(key, JSON.stringify(quotas));
      window.dispatchEvent(new Event('barolab-publications-updated'));
    } catch (error) { console.warn('[HistoryManager] Naver server publication sync failed:', error); }
  }

  // 글로벌 API 노출
  window.BaroLabHistory = {
    getKSTDateString,
    checkAndRolloverDaily,
    loadHistoryStore,
    saveHistoryStore,
    getNaverAccountingDate,
    recordPosting,
    removePosting,
    getTodayStats,
    getYesterdayStats,
    syncCFPublications,
    syncNaverPublications,
    openModal: openHistoryModal,
    closeModal
  };

  // 자동 실행 및 날짜 확인
  reconcileNaverOct11Accounting();
  checkAndRolloverDaily();
  let displayedDay = getKSTDateString();
  function refreshDailyDate() {
    const today = getKSTDateString();
    if (today === displayedDay) return;
    checkAndRolloverDaily();
    displayedDay = today;
    window.dispatchEvent(new Event('barolab-publications-updated'));
  }
  setInterval(refreshDailyDate, 1000);
  window.addEventListener('focus', refreshDailyDate);
  window.addEventListener('pageshow', refreshDailyDate);
  document.addEventListener('visibilitychange', refreshDailyDate);
  syncCFPublications();
  syncNaverPublications();
  setInterval(syncCFPublications, 5000);
  setInterval(syncNaverPublications, 5000);

})(window);

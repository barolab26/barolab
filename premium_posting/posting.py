
import os, json, datetime, asyncio
from playwright.async_api import async_playwright

STATUS_FILE = r"c:\10_Project\BaroLab\dashboard\data\premium\status.json"

def load_premium_status():
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "account": "yoon_master",
        "port": 9335,
        "channel_url": "baronotebrief",
        "channel_kr_name": "머스트픽 연금 자산 연구소",
        "status": "심사 진행 중 (Under Review)",
        "review_period": "신청일로부터 영업일 기준 최대 3일~5일",
        "category": "경제/비즈니스",
        "publish_schedule": "주 3회 (월/수/금)",
        "revenue_goal": "$100/day Funnel",
        "posts": []
    }

async def _sync_live():
    st = load_premium_status()
    try:
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp("http://127.0.0.1:9335")
            ctx = b.contexts[0]
            pg = await ctx.new_page()
            try:
                await pg.goto("https://studio.premium.naver.com/home", wait_until="domcontentloaded", timeout=12000)
                await asyncio.sleep(2.0)
                body = await pg.evaluate("() => document.body.innerText")
                url = pg.url
                if "심사가 진행 중" in body or "/join/review" in url:
                    st["status"] = "심사 진행 중 (Under Review)"
                elif "/channel" in url or "채널 관리" in body:
                    st["status"] = "승인 완료 (Active)"
                st["current_url"] = url
                st["last_checked"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            finally:
                await pg.close()
    except Exception as e:
        st["sync_error"] = str(e)
    
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    return st

def sync_premium_live_state():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _sync_live()).result()
        return loop.run_until_complete(_sync_live())
    except Exception:
        return asyncio.run(_sync_live())

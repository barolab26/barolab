"""
Gemini Chat Controller (Ubuntu GUI / CDP Port 9440)
Author: BaroLab Autonomous Team
Description:
  Automates communication with the persistent Google Gemini App running in Google Chrome
  under the active Ubuntu desktop session (DISPLAY=:10, CDP 9440).
  Allows EGO LITE and background pipelines to:
  1. Send live status pings, progress reports, and block alerts into the 'BaroLab 프로젝트' chat.
  2. Read the latest response or directive from Gemini.
"""

import asyncio
import logging
from typing import Optional
from playwright.async_api import async_playwright

logger = logging.getLogger("gemini_chat_controller")

DEFAULT_CDP_URL = "http://127.0.0.1:9440"
BAROLAB_CHAT_URL_KEY = "89e396b9e70f5c80"
BAROLAB_CHAT_TITLE = "BaroLab 프로젝트"


async def send_gemini_message(
    message: str,
    chat_title: str = BAROLAB_CHAT_TITLE,
    chat_key: str = BAROLAB_CHAT_URL_KEY,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout_sec: float = 15.0,
) -> bool:
    """
    Connects to the persistent Chrome CDP session, ensures the 'BaroLab 프로젝트' chat is active,
    types the given message into Gemini's prompt box, and clicks send.
    """
    try:
        async with async_playwright() as p:
            browser = await asyncio.wait_for(p.chromium.connect_over_cdp(cdp_url), timeout=timeout_sec)
            context = browser.contexts[0]
            gemini_page = next((page for page in context.pages if "gemini.google.com" in page.url), None)

            if not gemini_page:
                logger.warning("[GeminiChat] Gemini page not found in open CDP pages.")
                await browser.close()
                return False

            # Ensure we are in the target chat room
            if chat_key not in gemini_page.url:
                target_link = gemini_page.locator(f'a[href*="{chat_key}"], a[aria-label*="{chat_title}"]').first
                if await target_link.count() > 0:
                    await target_link.click()
                    await gemini_page.wait_for_timeout(1000)
                else:
                    await gemini_page.goto(f"https://gemini.google.com/app/{chat_key}")
                    await gemini_page.wait_for_load_state("domcontentloaded")
                    await gemini_page.wait_for_timeout(1500)

            # Locate prompt input box
            prompt_box = gemini_page.locator("div.ql-editor").first
            if await prompt_box.count() == 0:
                logger.warning("[GeminiChat] Prompt box (div.ql-editor) not found.")
                await browser.close()
                return False

            # Never clobber a draft the user is typing: wait (max 60s) for an empty box
            for _ in range(60):
                existing = (await prompt_box.inner_text()).strip()
                if not existing:
                    break
                await gemini_page.wait_for_timeout(1000)
            else:
                logger.warning("[GeminiChat] Prompt box busy (user draft); message not sent.")
                await browser.close()
                return False

            await prompt_box.click()
            await gemini_page.wait_for_timeout(200)

            # Insert message as a single line (newlines can break Quill submit)
            flat = " / ".join(l.strip() for l in message.splitlines() if l.strip())
            await prompt_box.evaluate(
                '(el, text) => { el.focus(); document.execCommand("insertText", false, text); }',
                flat
            )
            await gemini_page.wait_for_timeout(500)

            sent = False
            send_sel = ('button[aria-label*="보내기"], button[aria-label*="Send"], '
                        'button.send-button, button[mat-icon-button].send-button')
            for _ in range(10):
                send_btn = gemini_page.locator(send_sel).first
                if await send_btn.count() > 0 and await send_btn.is_enabled():
                    await send_btn.click()
                    break
                await gemini_page.wait_for_timeout(300)
            else:
                await prompt_box.press("Enter")

            # Verify: prompt box must be empty after sending; otherwise press Enter / Ctrl+Enter
            for key in (None, "Enter", "Control+Enter"):
                await gemini_page.wait_for_timeout(1200)
                if not (await prompt_box.inner_text()).strip():
                    sent = True
                    break
                if key:
                    await prompt_box.press(key)
            if not sent:
                logger.warning("[GeminiChat] Message still in prompt box after send attempts.")
            await browser.close()
            return sent

    except Exception as exc:
        logger.error(f"[GeminiChat] Failed to send message: {exc}")
        return False


async def get_last_gemini_response(
    chat_key: str = BAROLAB_CHAT_URL_KEY,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout_sec: float = 15.0,
) -> Optional[str]:
    """
    Retrieves the latest assistant response text from the active Gemini chat room.
    """
    try:
        async with async_playwright() as p:
            browser = await asyncio.wait_for(p.chromium.connect_over_cdp(cdp_url), timeout=timeout_sec)
            context = browser.contexts[0]
            gemini_page = next((page for page in context.pages if "gemini.google.com" in page.url), None)

            if not gemini_page:
                await browser.close()
                return None

            responses = await gemini_page.locator("message-content, .model-response-text").all()
            if not responses:
                await browser.close()
                return None

            last_text = (await responses[-1].inner_text()).strip()
            await browser.close()
            return last_text

    except Exception as exc:
        logger.error(f"[GeminiChat] Failed to read last response: {exc}")
        return None


def send_gemini_message_sync(message: str) -> bool:
    """Synchronous wrapper for send_gemini_message."""
    try:
        return asyncio.run(send_gemini_message(message))
    except Exception as exc:
        logger.error(f"[GeminiChat] Sync execution error: {exc}")
        return False


def get_last_gemini_response_sync() -> Optional[str]:
    """Synchronous wrapper for get_last_gemini_response."""
    try:
        return asyncio.run(get_last_gemini_response())
    except Exception as exc:
        logger.error(f"[GeminiChat] Sync execution error: {exc}")
        return None


if __name__ == "__main__":
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "[BaroLab Ping] 제미나이 연동 컨트롤러 테스트 정상"
    ok = send_gemini_message_sync(msg)
    print(f"Send status: {ok}")

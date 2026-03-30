import argparse
import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def wait_for_bot_turn(driver: webdriver.Chrome, prev_bot_count: int, timeout_s: int) -> None:
    WebDriverWait(driver, timeout_s).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, ".msg-wrapper.bot .msg.bot")) > prev_bot_count
    )

def _safe_json_loads(text: str | None) -> object | None:
    if not text:
        return None
    t = text.strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception:
        return {"_raw": t}


def capture_conversation(driver: webdriver.Chrome) -> dict:
    """
    Capture:
      - full chat transcript (user+bot bubbles)
      - UI raw order_state JSON panel (if present)
    """
    transcript = driver.execute_script(
        """
        const wrappers = Array.from(document.querySelectorAll('#messages .msg-wrapper'));
        return wrappers.map(w => {
          const label = w.querySelector('.msg-label')?.textContent?.trim() || '';
          const role = w.classList.contains('user') ? 'user' : (w.classList.contains('bot') ? 'bot' : label.toLowerCase() || 'unknown');
          const text = w.querySelector('.msg')?.textContent ?? '';
          return { role, text };
        });
        """
    )

    raw_state_text = driver.execute_script(
        "return document.getElementById('raw-json') ? document.getElementById('raw-json').textContent : '';"
    )
    order_state = _safe_json_loads(raw_state_text)

    pickup_active = driver.execute_script(
        "return document.getElementById('pickup-overlay')?.classList?.contains('active') ?? false;"
    )
    human_active = driver.execute_script(
        "return document.getElementById('human-overlay')?.classList?.contains('active') ?? false;"
    )

    return {
        "transcript": transcript,
        "order_state": order_state,
        "ui": {
            "pickup_overlay_active": bool(pickup_active),
            "human_overlay_active": bool(human_active),
        },
    }


def save_conversation(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def close_overlays_if_open(driver: webdriver.Chrome) -> None:
    # Pickup modal
    try:
        pickup_overlay = driver.find_element(By.CSS_SELECTOR, "#pickup-overlay")
        if "active" in (pickup_overlay.get_attribute("class") or ""):
            driver.find_element(By.CSS_SELECTOR, "#pickup-close-btn").click()
    except Exception:
        pass

    # Human escalation modal
    try:
        human_overlay = driver.find_element(By.CSS_SELECTOR, "#human-overlay")
        if "active" in (human_overlay.get_attribute("class") or ""):
            driver.find_element(By.CSS_SELECTOR, "#human-close-btn").click()
    except Exception:
        pass


def send_message_reliably(driver: webdriver.Chrome, msg: str, timeout_s: int) -> None:
    close_overlays_if_open(driver)

    # Wait for input and send button to be present and ready
    input_el = WebDriverWait(driver, timeout_s).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#user-input"))
    )
    WebDriverWait(driver, timeout_s).until(
        lambda d: d.find_element(By.CSS_SELECTOR, "#send-btn").is_enabled()
    )

    prev_user_count = len(driver.find_elements(By.CSS_SELECTOR, ".msg-wrapper.user .msg.user"))
    send_btn = driver.find_element(By.CSS_SELECTOR, "#send-btn")

    input_el.clear()
    input_el.send_keys(msg)
    send_btn.click()

    # Confirm the send actually happened (user bubble appears).
    try:
        WebDriverWait(driver, 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".msg-wrapper.user .msg.user")) > prev_user_count
        )
        return
    except TimeoutException:
        pass

    # Fallback 1: press Enter in input
    input_el.send_keys(Keys.ENTER)
    try:
        WebDriverWait(driver, 3).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, ".msg-wrapper.user .msg.user")) > prev_user_count
        )
        return
    except TimeoutException:
        pass

    # Fallback 2: JS click send button
    driver.execute_script("document.querySelector('#send-btn').click();")
    WebDriverWait(driver, timeout_s).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, ".msg-wrapper.user .msg.user")) > prev_user_count
    )


def run_flow(driver: webdriver.Chrome, base_url: str, flow: dict, per_turn_timeout_s: int) -> None:
    driver.get(base_url)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#user-input")))

    # Clear current UI state before each flow run
    driver.find_element(By.CSS_SELECTOR, "#clear-btn").click()

    for msg in flow["user_messages"]:
        prev_bot_count = len(driver.find_elements(By.CSS_SELECTOR, ".msg-wrapper.bot .msg.bot"))
        send_message_reliably(driver, msg, timeout_s=per_turn_timeout_s)

        try:
            wait_for_bot_turn(driver, prev_bot_count, timeout_s=per_turn_timeout_s)
        except TimeoutException:
            # Add an inline marker message in chat so the timeout point is visible.
            driver.execute_script(
                """
                const text = arguments[0];
                const wrapper = document.createElement("div");
                wrapper.className = "msg-wrapper bot";
                const label = document.createElement("div");
                label.className = "msg-label";
                label.textContent = "Bot";
                const bubble = document.createElement("div");
                bubble.className = "msg bot pickup";
                bubble.textContent = text;
                wrapper.appendChild(label);
                wrapper.appendChild(bubble);
                const messages = document.getElementById("messages");
                messages.appendChild(wrapper);
                messages.scrollTop = messages.scrollHeight;
                """,
                f"[SELENIUM] Timed out waiting for bot reply after: {msg!r}",
            )
            break


def build_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    # Keep window open even if session ends unexpectedly.
    options.add_experimental_option("detach", True)
    return webdriver.Chrome(options=options)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay user-only regression flows in local chat UI (Selenium).")
    parser.add_argument("--base-url", default="http://localhost:8000/", help="Chat UI URL")
    parser.add_argument(
        "--flows-file",
        default="regression_user_flows.test_menu.json",
        help="Path to user-only flows JSON file",
    )
    parser.add_argument(
        "--per-turn-timeout-s",
        type=int,
        default=60,
        help="Seconds to wait for each bot reply before marking timeout",
    )
    parser.add_argument("--delay-ms", type=int, default=250, help="Small delay between flow launches")
    parser.add_argument(
        "--out-dir",
        default="automation_outputs",
        help="Directory to write convo1.json, convo2.json, ... (default: automation_outputs)",
    )
    args = parser.parse_args()

    flows_path = Path(args.flows_file)
    payload = json.loads(flows_path.read_text(encoding="utf-8"))
    flows = payload.get("flows", [])
    if not flows:
        raise SystemExit(f"No flows found in: {flows_path}")

    drivers: list[webdriver.Chrome] = []
    try:
        out_dir = Path(args.out_dir)
        for idx, flow in enumerate(flows, start=1):
            driver = build_driver()
            drivers.append(driver)
            run_flow(
                driver=driver,
                base_url=args.base_url,
                flow=flow,
                per_turn_timeout_s=args.per_turn_timeout_s,
            )

            convo_payload = {
                "convo_id": f"convo{idx}",
                "flow_id": flow.get("id"),
                "flow_description": flow.get("description"),
                "base_url": args.base_url,
                "flows_file": str(flows_path),
                **capture_conversation(driver),
            }
            save_conversation(out_dir / f"convo{idx}.json", convo_payload)

            time.sleep(args.delay_ms / 1000)

        print("\nAll flows launched. Browsers are intentionally left open for manual validation.")
        print("Press Ctrl+C here when done. Then close browser windows manually.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        # Intentionally do not close drivers automatically (user requested windows stay open).
        # You can uncomment these lines if you later want auto-cleanup:
        # for d in drivers:
        #     d.quit()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())


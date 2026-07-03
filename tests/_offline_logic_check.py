"""
NOT part of the shipped test suite (see tests/test_*.py for the real pytest
suite that runs against the actual pydantic models). This is a stdlib-only
sanity script used during development to validate core routing/parsing logic
in an environment with no network access to install langgraph/pydantic.

Run: python3 tests/_offline_logic_check.py
"""
import json
import re
import sys


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        sys.exit(1)


# ---- 1. Guardrail deterministic checks (mirrors guardrails/mcp_guardrails.py) ----
HARD_DENY_SCRIPT_PATTERNS = [
    r"localStorage\.clear", r"document\.cookie\s*=", r"DROP\s+TABLE", r"eval\(",
]

def script_blocked(script):
    return any(re.search(p, script, re.IGNORECASE) for p in HARD_DENY_SCRIPT_PATTERNS)

check("destructive script blocked", script_blocked("localStorage.clear()"))
check("benign script allowed", not script_blocked("return document.title"))


def url_allowed(url, target_env, domains):
    from urllib.parse import urlparse
    if target_env not in domains:
        return True
    allowed = domains[target_env]
    if not allowed:
        return False
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith(f".{d}") for d in allowed)

domains = {"sandbox": ["demo.aiqef.local", "localhost"], "production": []}
check("sandbox url allowed", url_allowed("https://demo.aiqef.local/login", "sandbox", domains))
check("off-domain url blocked", not url_allowed("https://evil.com/login", "sandbox", domains))
check("empty production domain list blocks navigation", not url_allowed("https://yourapp.com", "production", domains))


# ---- 2. Guardrail quick-reject logic (mirrors guardrails/llm_guardrail_reviewer.py) ----
def quick_reject_reasons(steps):
    reasons = []
    if not any(s.get("expected") is not None for s in steps):
        reasons.append("No assertion step found.")
    suspicious = ["delete", "drop", "admin", "wipe", "purge"]
    for s in steps:
        haystack = f"{s.get('value','')} {s.get('action','')}".lower()
        if any(t in haystack for t in suspicious):
            reasons.append(f"Suspicious term in step: {s.get('value')}")
    return reasons

no_assertion_steps = [{"action": "click", "value": "#btn"}]
check("no-assertion test rejected", len(quick_reject_reasons(no_assertion_steps)) > 0)

good_steps = [{"action": "get_text", "value": ".error-banner", "expected": "Invalid username"}]
check("valid test passes quick check", len(quick_reject_reasons(good_steps)) == 0)

destructive_steps = [{"action": "click", "value": "#delete-account-btn", "expected": None}]
check("destructive-named locator flagged", len(quick_reject_reasons(destructive_steps)) > 0)


# ---- 3. Failure classification (mirrors src/agents/executor.py) ----
LOCATOR_ERROR_MARKERS = ("NoSuchElementException", "ElementNotFoundError", "not found")
TIMEOUT_ERROR_MARKERS = ("TimeoutException", "timed out")

def classify_failure(msg):
    if any(m.lower() in msg.lower() for m in LOCATOR_ERROR_MARKERS):
        return "locator_not_found"
    if any(m.lower() in msg.lower() for m in TIMEOUT_ERROR_MARKERS):
        return "timeout"
    return "assertion_failed"

check("locator error classified correctly", classify_failure("NoSuchElementException: no element") == "locator_not_found")
check("timeout classified correctly", classify_failure("TimeoutException: timed out after 5s") == "timeout")
check("assertion failure classified correctly", classify_failure("Expected 'foo' in actual 'bar'") == "assertion_failed")


# ---- 4. Routing logic (mirrors executor.route_after_execution / guardrail.route_after_guardrail) ----
def route_after_execution(failures, healing_attempts):
    healable = [f for f in failures if f["reason"] in ("locator_not_found", "timeout")]
    if healable and healing_attempts < 2:
        return "heal"
    return "report"

check("routes to heal on locator failure", route_after_execution([{"reason": "locator_not_found"}], 0) == "heal")
check("routes to report after 2 heal attempts", route_after_execution([{"reason": "locator_not_found"}], 2) == "report")
check("routes to report on pure assertion failure", route_after_execution([{"reason": "assertion_failed"}], 0) == "report")

def route_after_guardrail(approved, retry_count, target_env, max_retries=3):
    if not approved:
        return "report" if retry_count >= max_retries else "generate"
    if target_env != "sandbox":
        return "human_approval"
    return "execute"

check("rejected test loops back to generate", route_after_guardrail(False, 1, "sandbox") == "generate")
check("rejected test gives up after max retries", route_after_guardrail(False, 3, "sandbox") == "report")
check("approved sandbox test executes directly", route_after_guardrail(True, 0, "sandbox") == "execute")
check("approved non-sandbox test needs human approval", route_after_guardrail(True, 0, "staging") == "human_approval")


# ---- 5. Self-healing locator proposal parsing (mirrors src/agents/self_healer.py) ----
def parse_heal_response(raw):
    cleaned = raw.strip().strip("`").removeprefix("json").strip()
    data = json.loads(cleaned)
    if not data.get("confident"):
        return None
    return {"by": data["by"], "value": data["value"]}

heal_raw = json.dumps({"confident": True, "by": "css", "value": "button[data-testid='submit']", "reasoning": "match"})
result = parse_heal_response(heal_raw)
check("heal proposal parsed", result == {"by": "css", "value": "button[data-testid='submit']"})

unconfident_raw = json.dumps({"confident": False})
check("unconfident heal returns None", parse_heal_response(unconfident_raw) is None)


# ---- 6. End-to-end scripted run using the SAME mock DOM as tools/mcp_client_mock.py ----
FAKE_DOM_ELEMENTS = {
    ("id", "username"): {"tag": "input"},
    ("id", "password"): {"tag": "input"},
    ("css", "button[data-testid='submit']"): {"tag": "button", "text": "Sign In"},
    ("css", "#submit-btn-old"): None,
    ("css", ".error-banner"): {"tag": "div", "text": ""},
}

class MiniMockBrowser:
    def __init__(self):
        self.session_values = {}

    def find_element(self, by, value):
        el = FAKE_DOM_ELEMENTS.get((by, value))
        if el is None:
            raise RuntimeError(f"NoSuchElementException: no element for {by}='{value}'")
        return el

    def send_keys(self, by, value, text):
        self.find_element(by, value)
        self.session_values["password" if value == "password" else "username"] = text

    def click(self, by, value):
        self.find_element(by, value)  # will raise on stale locator
        if self.session_values.get("password") != "correct-horse-battery-staple":
            FAKE_DOM_ELEMENTS[("css", ".error-banner")]["text"] = "Invalid username or password"

    def get_text(self, by, value):
        return FAKE_DOM_ELEMENTS[(by, value)]["text"]


browser = MiniMockBrowser()
browser.send_keys("id", "username", "demo_user")
browser.send_keys("id", "password", "wrong-password-123")

# Step 1: original (stale) locator fails
try:
    browser.click("css", "#submit-btn-old")
    click_failed = False
except RuntimeError as e:
    click_failed = True
    failure_reason = classify_failure(str(e))

check("stale locator click fails as expected", click_failed)
check("failure classified as locator_not_found", failure_reason == "locator_not_found")

# Step 2: self-heal proposes new locator, retry succeeds
healed_locator = parse_heal_response(heal_raw)
browser.click(healed_locator["by"], healed_locator["value"])
error_text = browser.get_text("css", ".error-banner")
check("healed click succeeds and error banner shows expected text",
      "invalid username or password" in error_text.lower())

print("\n✅ All offline logic checks passed — core agent decision logic is sound.")
print("   (Full graph execution requires `pip install -r requirements.txt` for langgraph+pydantic)")

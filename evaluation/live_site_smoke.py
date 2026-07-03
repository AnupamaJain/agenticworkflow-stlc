"""
Read-only live smoke checks for public automation-practice sites.

This intentionally uses only HTTP GET requests and content assertions. It does
not sign up, log in, add items to cart, submit forms, or attempt checkout.

Usage:
    python evaluation/live_site_smoke.py
    python evaluation/live_site_smoke.py --base-url https://automationexercise.com
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://automationexercise.com"
DEFAULT_OUTPUT_PATH = "demo/sample_run/live_site_smoke.json"
ALLOWED_HOSTS = {"automationexercise.com", "www.automationexercise.com"}


@dataclass
class PageCheck:
    name: str
    path: str
    expected_text: list[str]


@dataclass
class PageResult:
    name: str
    url: str
    status: str
    status_code: int | None
    duration_ms: int
    title: str | None = None
    missing_text: list[str] | None = None
    error: str | None = None


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())

    @property
    def title(self) -> str | None:
        title = " ".join(part for part in self.title_parts if part).strip()
        return title or None


CHECKS = [
    PageCheck(
        name="TC-LIVE-001 home page loads",
        path="/",
        expected_text=[
            "Automation Exercise",
            "Full-Fledged practice website for Automation Engineers",
            "Features Items",
        ],
    ),
    PageCheck(
        name="TC-LIVE-002 products listing loads",
        path="/products",
        expected_text=[
            "All Products",
            "Blue Top",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-003 test cases page loads",
        path="/test_cases",
        expected_text=[
            "Test Cases",
            "Below is the list of test Cases for you to practice the Automation",
        ],
    ),
    PageCheck(
        name="TC-LIVE-004 API list page loads",
        path="/api_list",
        expected_text=[
            "APIs List for practice",
            "Get All Products List",
        ],
    ),
    PageCheck(
        name="TC-LIVE-005 contact page loads",
        path="/contact_us",
        expected_text=[
            "Get In Touch",
            "Name",
            "Email",
        ],
    ),
    PageCheck(
        name="TC-LIVE-006 login page displays login and signup forms",
        path="/login",
        expected_text=[
            "Login to your account",
            "New User Signup!",
            "Signup",
        ],
    ),
    PageCheck(
        name="TC-LIVE-007 cart page loads without mutating cart",
        path="/view_cart",
        expected_text=[
            "Shopping Cart",
            "Cart is empty!",
        ],
    ),
    PageCheck(
        name="TC-LIVE-008 product detail Blue Top loads",
        path="/product_details/1",
        expected_text=[
            "Blue Top",
            "Category",
            "Availability",
            "Brand",
        ],
    ),
    PageCheck(
        name="TC-LIVE-009 product detail Men Tshirt loads",
        path="/product_details/2",
        expected_text=[
            "Men Tshirt",
            "Category",
            "Availability",
            "Brand",
        ],
    ),
    PageCheck(
        name="TC-LIVE-010 product detail Sleeveless Dress loads",
        path="/product_details/3",
        expected_text=[
            "Sleeveless Dress",
            "Category",
            "Availability",
            "Brand",
        ],
    ),
    PageCheck(
        name="TC-LIVE-011 product detail Stylish Dress loads",
        path="/product_details/4",
        expected_text=[
            "Stylish Dress",
            "Category",
            "Availability",
            "Brand",
        ],
    ),
    PageCheck(
        name="TC-LIVE-012 brand Polo page loads",
        path="/brand_products/Polo",
        expected_text=[
            "Brand - Polo Products",
            "Blue Top",
            "Polo",
        ],
    ),
    PageCheck(
        name="TC-LIVE-013 brand H&M page loads",
        path="/brand_products/H&M",
        expected_text=[
            "Brand - H&amp;M Products",
            "H&amp;M",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-014 brand Madame page loads",
        path="/brand_products/Madame",
        expected_text=[
            "Brand - Madame Products",
            "Madame",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-015 women dress category loads",
        path="/category_products/1",
        expected_text=[
            "Women - Dress Products",
            "Sleeveless Dress",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-016 women tops category loads",
        path="/category_products/2",
        expected_text=[
            "Women - Tops Products",
            "Blue Top",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-017 women tshirts category loads",
        path="/category_products/3",
        expected_text=[
            "Women - Tshirts Products",
            "Pure Cotton V-Neck T-Shirt",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-018 men tshirts category loads",
        path="/category_products/4",
        expected_text=[
            "Men - Tshirts Products",
            "Men Tshirt",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-019 men jeans category loads",
        path="/category_products/6",
        expected_text=[
            "Men - Jeans Products",
            "Soft Stretch Jeans",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-020 kids dress category loads",
        path="/category_products/7",
        expected_text=[
            "Kids - Dress Products",
            "Sleeveless Unicorn Patch Gown",
            "View Product",
        ],
    ),
    PageCheck(
        name="TC-LIVE-021 products API returns product list",
        path="/api/productsList",
        expected_text=[
            '"responseCode": 200',
            '"products"',
            '"Blue Top"',
        ],
    ),
    PageCheck(
        name="TC-LIVE-022 brands API returns brand list",
        path="/api/brandsList",
        expected_text=[
            '"responseCode": 200',
            '"brands"',
            '"Polo"',
        ],
    ),
]


def validate_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError("Live smoke tests require an https base URL.")

    host = parsed.hostname or ""
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Host '{host}' is not allowed for this live smoke runner.")

    return base_url.rstrip("/")


def fetch_text(url: str, timeout_s: float) -> tuple[int, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "AI-QEF live smoke test; read-only public-page check",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_s) as response:
        status_code = getattr(response, "status", response.getcode())
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
        return status_code, body


def extract_title(html: str) -> str | None:
    parser = TitleParser()
    parser.feed(html)
    return parser.title


def run_page_check(base_url: str, check: PageCheck, timeout_s: float) -> PageResult:
    url = urljoin(f"{base_url}/", check.path.lstrip("/"))
    start = time.time()
    try:
        status_code, body = fetch_text(url, timeout_s)
        duration_ms = int((time.time() - start) * 1000)
        missing = [text for text in check.expected_text if text not in body]
        return PageResult(
            name=check.name,
            url=url,
            status="passed" if 200 <= status_code < 300 and not missing else "failed",
            status_code=status_code,
            duration_ms=duration_ms,
            title=extract_title(body),
            missing_text=missing,
        )
    except HTTPError as exc:
        duration_ms = int((time.time() - start) * 1000)
        return PageResult(
            name=check.name,
            url=url,
            status="failed",
            status_code=exc.code,
            duration_ms=duration_ms,
            error=str(exc),
        )
    except URLError as exc:
        duration_ms = int((time.time() - start) * 1000)
        return PageResult(
            name=check.name,
            url=url,
            status="failed",
            status_code=None,
            duration_ms=duration_ms,
            error=str(exc.reason),
        )


def write_report(path: str, payload: dict) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-s", type=float, default=15.0)
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    try:
        base_url = validate_base_url(args.base_url)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    results = [run_page_check(base_url, check, args.timeout_s) for check in CHECKS]
    passed = sum(1 for result in results if result.status == "passed")
    payload = {
        "base_url": base_url,
        "mode": "live_read_only_http_smoke",
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "results": [asdict(result) for result in results],
    }
    write_report(args.output, payload)

    print(f"Live smoke summary: {passed}/{len(results)} passed")
    for result in results:
        detail = f"{result.status.upper()} {result.name} {result.status_code or '-'} {result.duration_ms}ms"
        if result.error:
            detail += f" error={result.error}"
        if result.missing_text:
            detail += f" missing={result.missing_text}"
        print(f"  {detail}")
    print(f"Report written to: {args.output}")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

import requests
from bs4 import BeautifulSoup

from models import JobListing

LISTINGS_URL = "https://www.getonbrd.com/jobs/programming"
USER_AGENT = "Mozilla/5.0 (compatible; job-hunter-agent/1.0)"


def fetch_html(url: str = LISTINGS_URL) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def parse_listings(html: str, keywords: list[str]) -> list[JobListing]:
    soup = BeautifulSoup(html, "html.parser")
    lowered_keywords = [keyword.lower() for keyword in keywords]
    listings = []

    cards = soup.select("a.results-item")
    if not cards:
        raise RuntimeError(
            "No job cards found on GetOnBoard listings page; "
            "the site may be unreachable or its HTML structure may have changed"
        )

    for card in cards:
        url = card.get("href", "")
        if not url:
            continue

        job_id = url.rstrip("/").split("/")[-1]
        summary = card.get("title", "").strip()

        title_tag = card.select_one("h4.results-list-title strong")
        title = title_tag.get_text(strip=True) if title_tag else ""

        company_tag = card.select_one("div.size0.flex.gap-1.items-center strong")
        company = company_tag.get_text(strip=True) if company_tag else ""

        haystack = f"{title} {summary}".lower()
        if not any(keyword in haystack for keyword in lowered_keywords):
            continue

        listings.append(
            JobListing(
                id=job_id,
                title=title,
                company=company,
                url=url,
                description=summary,
            )
        )

    return listings


def fetch_listings(keywords: list[str]) -> list[JobListing]:
    return parse_listings(fetch_html(), keywords)

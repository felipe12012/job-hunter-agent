import requests
from bs4 import BeautifulSoup

from models import JobListing

LISTINGS_URL = "https://cl.computrabajo.com/trabajo-de-desarrollador"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9",
}


def fetch_html(url: str = LISTINGS_URL) -> str:
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_listing_summaries(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.box_offer")
    if not cards:
        raise RuntimeError(
            "No job cards found on Computrabajo listings page; "
            "the site may be unreachable or its HTML structure may have changed"
        )

    summaries = []
    for card in cards:
        job_id = card.get("data-id", "")
        title_tag = card.select_one("h2 a")
        if not job_id or not title_tag:
            continue

        href = title_tag.get("href", "")
        url = href if href.startswith("http") else f"https://cl.computrabajo.com{href}"

        company_tag = card.select_one("a[offer-grid-article-company-url]")
        company = company_tag.get_text(strip=True) if company_tag else ""

        summaries.append(
            {
                "id": job_id,
                "title": title_tag.get_text(strip=True),
                "company": company,
                "url": url,
            }
        )

    return summaries


def parse_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h2", string=lambda text: text and "Descripción de la oferta" in text)
    container = heading.find_parent("div") if heading else None
    if container is None:
        return ""

    parts = []
    desc_p = container.find("p", class_="mbB")
    if desc_p:
        parts.append(desc_p.get_text(separator=" ", strip=True))
    req_ul = container.find("ul", class_="disc")
    if req_ul:
        parts.append(req_ul.get_text(separator=" ", strip=True))

    return " ".join(parts)


def _build_listing(summary: dict, description: str) -> JobListing:
    return JobListing(
        id=summary["id"],
        title=summary["title"],
        company=summary["company"],
        url=summary["url"],
        description=description,
        source="computrabajo",
    )


def fetch_listings(keywords: list[str]) -> list[JobListing]:
    summaries = parse_listing_summaries(fetch_html())

    lowered_keywords = [keyword.lower() for keyword in keywords]
    listings = []
    for summary in summaries:
        if not any(keyword in summary["title"].lower() for keyword in lowered_keywords):
            continue

        description = parse_description(fetch_html(summary["url"]))
        listings.append(_build_listing(summary, description))

    return listings

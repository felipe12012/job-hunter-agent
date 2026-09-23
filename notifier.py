import os

import requests

from models import ScoredListing

TELEGRAM_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
MATCH_THRESHOLD = 80
MAX_LISTINGS_PER_DIGEST = 3
MAX_TELEGRAM_TEXT_LENGTH = 4000


def format_digest(scored_listings: list[ScoredListing]) -> str:
    lines = [f"{len(scored_listings)} ofertas top de hoy:\n"]
    for scored in scored_listings:
        lines.append(
            f"*{scored.listing.title}* @ {scored.listing.company} - {scored.match_pct}% match\n"
            f"{scored.listing.url}\n"
            f"Por que: {scored.reasoning}\n"
            f"Borrador:\n{scored.draft_message}\n"
        )
    return "\n".join(lines)


def send_digest(
    scored_listings: list[ScoredListing],
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    qualifying = [s for s in scored_listings if s.match_pct >= MATCH_THRESHOLD]
    if not qualifying:
        return False

    qualifying.sort(key=lambda s: s.match_pct, reverse=True)
    top = qualifying[:MAX_LISTINGS_PER_DIGEST]

    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    text = format_digest(top)
    if len(text) > MAX_TELEGRAM_TEXT_LENGTH:
        text = text[:MAX_TELEGRAM_TEXT_LENGTH]

    response = requests.post(
        TELEGRAM_URL_TEMPLATE.format(token=bot_token),
        json={
            "chat_id": chat_id,
            "text": text,
        },
        timeout=30,
    )
    response.raise_for_status()
    return True

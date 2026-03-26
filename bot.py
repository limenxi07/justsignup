import asyncio
import json
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import get_profile, get_unsent_events, mark_sent, get_event_by_title, search_events, init_db
from pipeline import run_pipeline

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YOUR_ID = int(os.getenv("YOUR_TELEGRAM_USER_ID"))
MINIMUM_THRESHOLD = 6

logging.basicConfig(level=logging.INFO)


# --- Auth guard ---

def only_me(func):
    """Decorator — silently ignores any message not from you."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != YOUR_ID:
            return
        await func(update, context)
    return wrapper


# --- Event card formatter ---

def format_event_card(event: dict) -> str:
    score = event.get("adjusted_score")
    score_str = f"{score}/10" if score is not None else "unscored"

    fee = event.get("fee")
    if fee is None or fee == 0.0:
        fee_str = None
    else:
        fee_str = f"${fee:.2f}"

    date_str = event.get("date") or "date unknown"
    if event.get("date_iso") is None:
        date_str += " (date unconfirmed)"

    location = event.get("location") or "TBC"
    refreshments = event.get("refreshments")
    signup = event.get("signup_link") or "TBC"
    why_go = event.get("why_go") or ""
    title = event.get("title") or "Untitled"
    event_type = event.get("event_type") or "event"
    org = event.get("organisation") or "TBC"

    lines = [
        f"[{score_str}] {event_type} · {org}",
        f"<b>{title}</b>",
        f"📅 {date_str}"
    ]
    if fee_str:
        lines.append(f"📍 {location}   💰 {fee_str}")
    else:
        lines.append(f"📍 {location}")

    if refreshments:
        lines.append(f"🍕 {refreshments}")

    lines.append(f"🔗 {signup}")

    if why_go:
        lines.append(f"\n<i>{why_go}</i>")

    # Link back to original source
    channel_username = event.get("channel_username")
    message_id = event.get("message_id")
    channel = event.get("channel", "Unknown channel")

    if channel_username and message_id:
        source_str = f'<a href="https://t.me/{channel_username}/{message_id}">View original in {channel}</a>'
    elif message_id:
        # private channel — construct the c/ style link using numeric chat_id
        # strip the -100 prefix Telegram adds to channel IDs
        raw_id = str(event.get("channel", "")).lstrip("-100") if not channel_username else None
        source_str = f"📢 {channel}"
    else:
        source_str = f"📢 {channel}"

    lines.append(source_str)

    return "\n".join(lines)


# --- Digest builder ---

def build_digest(events: list[dict]) -> list[str]:
    """
    Split events into Telegram-safe messages (max 4096 chars each).
    Returns a list of message strings to send in sequence.
    """
    if not events:
        return ["nothing new yet! check back later~"]

    cards = [format_event_card(e) for e in events]
    messages = []
    current = f"<b>Your digest — {len(events)} event(s)</b>\n\n"

    for card in cards:
        block = card + "\n\n" + ("─" * 30) + "\n\n"
        if len(current) + len(block) > 4000:
            messages.append(current.strip())
            current = block
        else:
            current += block

    if current.strip():
        messages.append(current.strip())

    return messages


# --- Commands ---

@only_me
async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = get_unsent_events(limit=MINIMUM_THRESHOLD)

    if not events:
        await update.message.reply_text("nothing new yet! check back later~")
        return

    for msg in build_digest(events):
        await update.message.reply_text(msg, parse_mode="HTML")

    for e in events:
        mark_sent(e["id"])


@only_me
async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Usage: /search <keyword>")
        return

    results = search_events(query)
    if not results:
        await update.message.reply_text(f"nothing found matching '{query}'.")
        return

    cards = [format_event_card(e) for e in results[:5]]
    response = f"<b>Search: {query}</b> ({len(results)} result(s))\n\n"
    response += "\n\n" + ("─" * 30) + "\n\n".join(cards)
    await update.message.reply_text(response[:4096], parse_mode="HTML")


@only_me
async def cmd_explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("usage: /explain <partial event name>")
        return

    event = get_event_by_title(query)
    if not event:
        await update.message.reply_text(f"nothing found matching '{query}'.")
        return

    profile = get_profile()
    preferred_days = json.loads(profile.get("preferred_days", "[]"))

    fee = event.get("fee")
    day = event.get("day_of_week")

    penalties = []
    if fee is not None and fee > 0:
        penalties.append(f"paid event (-2)")
    if preferred_days:
        if day is None:
            penalties.append("unknown date (-1)")
        elif day not in preferred_days:
            penalties.append(f"wrong day: {day} (-2)")
    boost = profile.get("boost_refreshments", "False") == "True"
    if boost and event.get("refreshments"):
        penalties.append("refreshments bonus (+1)")

    penalty_str = ", ".join(penalties) if penalties else "none"

    lines = [
        f"<b>{event.get('title')}</b>",
        f"claude_score:    {event.get('claude_score')}",
        f"adjusted_score:  {event.get('adjusted_score')}",
        f"adjustments:     {penalty_str}",
        f"matched_tags:    {', '.join(event.get('matched_tags') or [])}",
        f"why_go:          {event.get('why_go')}",
        "",
        f"type:            {event.get('event_type')}",
        f"organisation:    {event.get('organisation')}",
        f"date:            {event.get('date')}",
        f"location:        {event.get('location')}",
        f"fee:             {event.get('fee')}",
        f"signup:          {event.get('signup_link')}",
        f"deadline:        {event.get('deadline')}",
        f"refreshments:    {event.get('refreshments')}",
        f"target_audience: {', '.join(event.get('target_audience') or [])}",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


@only_me
async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    #TODO: implement full conversational setup inside the bot, instead of just pointing to the CLI setup
    await update.message.reply_text(
        "To update your profile, run this in your terminal:\n\n"
        "<code>python setup.py</code>\n\n"
        "Full conversational /setup inside the bot is coming in a later version.",
        parse_mode="HTML"
    )


@only_me
async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded messages — run full pipeline and return event card."""
    message = update.message
    if not message.forward_date:
        return  # not a forwarded message, ignore

    text = message.text or message.caption
    if not text or not text.strip():
        await message.reply_text("message has no text to process :(")
        return

    await message.reply_text("running pipeline...")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, run_pipeline, text, "forwarded")

    if not result:
        await message.reply_text("not an event!!")
        return

    profile = get_profile()
    preferred_days = json.loads(profile.get("preferred_days", "[]"))
    fee = result.get("fee")
    day = result.get("day_of_week")

    penalties = []
    if fee is not None and fee > 0:
        penalties.append("paid event (-2)")
    if preferred_days:
        if day is None:
            penalties.append("unknown date (-1)")
        elif day not in preferred_days:
            penalties.append(f"wrong day: {day} (-2)")
    boost = profile.get("boost_refreshments", "False") == "True"
    if boost and result.get("refreshments"):
        penalties.append("refreshments bonus (+1)")

    penalty_str = ", ".join(penalties) if penalties else "none"
    card = format_event_card(result)
    breakdown = (
        f"\nclaude_score: {result.get('claude_score')}  "
        f"adjusted: {result.get('adjusted_score')}  "
        f"adjustments: {penalty_str}"
    )

    await message.reply_text(card + breakdown, parse_mode="HTML")


# --- App factory ---

def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("explain", cmd_explain))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(MessageHandler(filters.FORWARDED & filters.TEXT, handle_forwarded))

    return app


if __name__ == "__main__":
    init_db()
    app = build_app()
    print("Bot is running. Send /digest in Telegram to test.")
    app.run_polling()
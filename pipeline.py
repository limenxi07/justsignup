import os
import json
from db import save_event, update_scores, get_profile, event_exists
from typing import Optional
from anthropic import Anthropic

MAX_TOKENS = 1500
MODEL = "claude-sonnet-4-6"
EVENT_SCHEMA = {
    "title":           "REQUIRED. Infer intelligently if not explicit.",
    "event_type":      "REQUIRED. One of: Workshop, Hackathon, Talk, Career_Fair, Recruitment, Mentorship, QA_Session, Networking, Competition, Pitching Competition, Briefing, Other",
    "synopsis":        "REQUIRED. 1 sentence summary of what the event is about.",
    "organisation":    "Organising body/club/company. 'TBC' if not mentioned.",
    "target_audience": (
        "REQUIRED. List of NUS faculty abbreviations this event is most relevant to. "
        "Choose from: FASS, BIZ, SoC, SCLE, DENT, CDE, FoS, LAW, YLL, YST, SSH. "
        "Use ['All'] if the event is open to or relevant to all faculties. "
        "Use your knowledge of each faculty's disciplines to infer relevance even if not explicitly stated. "
        "Examples: a data science talk → ['SoC', 'FoS', 'BIZ']. A law internship → ['LAW']. "
        "A general networking event → ['All']."
    ),
    "date":            "REQUIRED. Human-readable e.g. '22 Oct 2025, 10am-2pm' or 'Ongoing'.",
    "date_iso":        "Best-effort ISO start date 'YYYY-MM-DD'. null if cannot determine.",
    "day_of_week":     "Full day name e.g. 'Monday'. null if date_iso is null.",
    "location":        "Physical location string, 'Online', 'Hybrid', or 'TBC'.",
    "fee":             "Float. 0.0 if free or not mentioned.",
    "signup_link":     "URL, 'Walk-in', or 'TBC'.",
    "deadline":        "Registration deadline 'DD MMM YYYY, HH:MM' if explicitly stated. null otherwise.",
    "key_speakers":    "Names of notable speakers if mentioned. null otherwise.",
    "refreshments":    "e.g. 'Dinner', 'Lunch', 'Light refreshments'. null if not mentioned.",
    "contacts":        "Contact details for enquiries e.g. Telegram @handle. null if not mentioned.",
}
FACULTY_REFERENCE = """
NUS Faculties and their departments:
- FASS: Chinese Studies, Communications and New Media, Economics, English Linguistics and Theatre Studies, Geography, History, Japanese Studies, Malay Studies, Philosophy, Political Science, Psychology, Social Work, Southeast Asian Studies, Sociology and Anthropology
- BIZ: Accounting, Analytics and Operations, Finance, Marketing, Management and Organisation, Real Estate, Strategy and Policy
- SoC: Computer Science, Information Systems and Analytics
- SCLE: Continuing and Lifelong Education
- DENT: Dentistry
- CDE: Architecture, Biomedical Engineering, Built Environment, Chemical and Biomolecular Engineering, Civil and Environmental Engineering, Electrical and Computer Engineering, Industrial Systems Engineering and Management, Materials Science and Engineering, Mechanical Engineering, Industrial Design
- FoS: Biological Sciences, Chemistry, Food Science and Technology, Mathematics, Pharmacy and Pharmaceutical Sciences, Physics, Statistics and Data Science
- LAW: Law
- YLL: Medicine and all clinical departments including Nursing, Pharmacy, and Graduate Medical Studies
- YST: Music
- SSH: Public Health
"""
TONE_INSTRUCTIONS = {
    "professional": (
        "Concise and persuasive. No fluff. Respect the user's time. "
        "Make the case for why this event is worth attending in direct, professional language."
    ),
    "casual": (
        "Like a friend who genuinely wants them there and knows their situation. "
        "Warm, direct, no corporate speak. Be pursuasive but friendly, like how a peer would recommend something they think is a great fit."
    ),
    "cheeky": (
        "Apply light pressure. Call out excuses before they make them. "
        "Playful but still genuinely persuasive."
    ),
    "brutal": (
        "Concise, short, to the point. Colourful language is encouraged. Lay out the brutal truth of why this event is or isn't worth their time, based on their profile. If it is genuinely useful, make them feel it - encourage them strongly to go."
        "Like how a close friend texts — no padding, no softening, just the truth."
    ),
}


def get_client():
    return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def classify(message: str) -> bool:
    """Step 1: Is this an event or opportunity announcement? Uses Haiku."""
    response = get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16,
        system=(
            "You are a classifier. Reply with only 'yes' or 'no'. "
            "Decide if the message is announcing an event, workshop, talk, hackathon, "
            "recruitment drive, or any opportunity students might sign up for."
        ),
        messages=[{"role": "user", "content": message}]
    )
    answer = response.content[0].text.strip().lower()
    return answer == "yes"


def extract(message: str) -> dict:
    """Step 2: Extract message into EVENT_SCHEMA. Uses Sonnet."""
    schema_str = json.dumps(EVENT_SCHEMA, indent=2)
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=(
            "You are an event data extractor. Given a Telegram message, extract all event details "
            "into the provided JSON schema. Return ONLY valid JSON, no markdown, no explanation. "
            "Follow the field instructions exactly. Use null for missing optional fields."
            f"{FACULTY_REFERENCE}"
        ),
        messages=[{
            "role": "user",
            "content": f"Schema:\n{schema_str}\n\nMessage:\n{message}"
        }]
    )

    raw = response.content[0].text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Strip accidental markdown fences if Sonnet adds them despite instructions
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)


def score(extracted: dict, profile: dict) -> dict:
    """
    Step 3: Score event relevancy and generate why_go against user profile.
    Returns dict with claude_score, why_go, matched_tags.
    """
    tone = profile.get("tone", "brutal").lower()
    tone_instruction = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["brutal"])

    interest_tags = json.loads(profile.get("interest_tags", "[]"))
    preferred_days = json.loads(profile.get("preferred_days", "[]"))

    profile_block = f"""
User profile:
- Faculty: {profile.get('faculty', 'Unknown')}
- Year: {profile.get('year', 'Unknown')}
- Career clarity: {profile.get('career_clarity', 'Unknown')}
- Time availability: {profile.get('free_time', 'Unknown')}
- Interest tags: {', '.join(interest_tags) or 'None specified'}
- Preferred event days: {', '.join(preferred_days) or 'Any'}
- Bio: {profile.get('bio', 'Not provided')}
""".strip()

    event_block = f"""
Event details:
- Title: {extracted.get('title')}
- Type: {extracted.get('event_type')}
- Synopsis: {extracted.get('synopsis')}
- Organisation: {extracted.get('organisation')}
- Target audience: {extracted.get('target_audience')}
- Date: {extracted.get('date')} ({extracted.get('day_of_week', 'day unknown')})
- Location: {extracted.get('location')}
- Fee: {extracted.get('fee')}
- Refreshments: {extracted.get('refreshments')}
- Key speakers: {extracted.get('key_speakers')}
""".strip()

    system_prompt = f"""
You are an assertive personal event scout for a university student. Your job is to
evaluate how relevant an event is to this specific user and make them feel it when
it's worth their time. You are direct, specific to their profile, and never hedge.

Tone instruction for why_go: {tone_instruction}

Scoring rules:
- Score purely on interest relevancy to the user's profile, tags, faculty, and bio.
- Do not factor in fee, day of week, or whether it recurs — those are handled separately.
- 1-3: Irrelevant or mismatched to their interests entirely.
- 4-6: Tangentially related or generally useful but not a strong match.
- 7-8: Good match to their interests or career direction.
- 9-10: Direct hit on their stated interests, bio, or career goals.

Return ONLY valid JSON in this exact format, no markdown, no explanation:
{{
  "claude_score": <integer 1-10>,
  "why_go": "<2 sentences max, assertive, personalised to their profile>",
  "matched_tags": [<list of matching interest tags from their profile, empty list if none>]
}}
""".strip()

    response = get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"{profile_block}\n\n{event_block}"
        }]
    )

    raw = response.content[0].text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)


def adjust(claude_score: int, extracted: dict, profile: dict) -> int:
    """
    Step 4: Apply score penalties and bonuses in Python. Zero API cost.
    Returns adjusted_score clamped to 0-10.
    """
    with open("config.yaml") as f:
        import yaml
        config = yaml.safe_load(f)

    adj = config.get("score_adjustments", {})
    score = claude_score

    # Paid event penalty
    fee = extracted.get("fee")
    if fee is not None and fee > 0:
        score += adj.get("paid_event", -2)

    # Wrong day penalty — unknown date gets its own lighter penalty
    preferred_days = json.loads(profile.get("preferred_days", "[]"))
    day_of_week = extracted.get("day_of_week")
    if preferred_days:
        if day_of_week is None:
            score += adj.get("unknown_date", -1)
        elif day_of_week not in preferred_days:
            score += adj.get("wrong_day", -2)

    # Refreshments bonus
    boost = profile.get("boost_refreshments", "False") == "True"
    if boost and extracted.get("refreshments"):
        score += adj.get("has_refreshments", 1)

    return max(0, min(10, score))


def run_pipeline(message: str, channel: str = "unknown",
                 message_id: int = None, channel_username: str = None, chat_id: int = None) -> Optional[dict]:
    print("  [1] Classifying...")
    if not classify(message):
        print("  [1] Not an event, discarding.")
        return None
    print("  [1] Event detected.")

    print("  [2] Extracting...")
    extracted = extract(message)

    # Deduplicate cross-posted events
    title = extracted.get("title", "")
    if event_exists(title):
        print(f"  [2] Duplicate detected: '{title}', discarding.")
        return None

    event_id = save_event(channel, message, extracted, message_id, channel_username, chat_id)
    extracted["_id"] = event_id
    print(f"  [2] Extracted and saved, id: {event_id}")

    print("  [3] Scoring...")
    profile = get_profile()
    score_result = score(extracted, profile)
    claude_score = score_result.get("claude_score", 5)
    why_go = score_result.get("why_go", "")
    matched_tags = score_result.get("matched_tags", [])
    print(f"  [3] claude_score: {claude_score}")

    print("  [4] Adjusting...")
    adjusted = adjust(claude_score, extracted, profile)
    min_threshold = int(profile.get("min_threshold", 1))
    if adjusted < min_threshold:
        print(f"  [4] adjusted_score {adjusted} below min_threshold {min_threshold}, discarding.")
        return None
    print(f"  [4] adjusted_score: {adjusted}")

    update_scores(event_id, claude_score, adjusted, why_go, matched_tags)
    print(f"  [4] Scores written to DB.")

    extracted.update({
        "claude_score":   claude_score,
        "adjusted_score": adjusted,
        "why_go":         why_go,
        "matched_tags":   matched_tags,
    })

    return extracted
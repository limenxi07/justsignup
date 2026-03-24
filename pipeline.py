import os
import json
from typing import Optional
from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


def classify(message: str) -> bool:
    """Step 1: Is this an event or opportunity announcement? Uses Haiku."""
    response = client.messages.create(
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
    response = client.messages.create(
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


def run_pipeline(message: str) -> Optional[dict]:
    """
    Full Day 2 pipeline: classify then extract.
    Returns extracted event dict, or None if not an event.
    """
    print("  [1] Classifying...")
    if not classify(message):
        print("  [1] Not an event, discarding.")
        return None
    print("  [1] Event detected.")

    print("  [2] Extracting...")
    event = extract(message)
    print("  [2] Extracted.")

    return event
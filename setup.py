import json
import sys
from typing import Optional
from dotenv import load_dotenv
from db import init_db, save_profile, get_profile

load_dotenv()

INTEREST_TAGS = [
    "Tech", "Entrepreneurship", "FinTech", "Design", "Consulting",
    "Quant/Finance", "Welfare/Social", "Arts", "Sports", "Career", "General/Networking"
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SKIP = "s"


def prompt_choice(question: str, options: list, skippable: bool = True) -> Optional[str]:
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    if skippable:
        print(f"  s. Skip")
    while True:
        raw = input("Enter number: ").strip().lower()
        if skippable and raw == SKIP:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print(f"  Please enter a number between 1 and {len(options)}." +
              (" Or 's' to skip." if skippable else ""))


def prompt_multiselect(question: str, options: list, skippable: bool = True) -> Optional[list]:
    print(f"\n{question}")
    print("  (enter comma-separated numbers e.g. 1,3,5 — or 'all' for everything)")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    if skippable:
        print(f"  s. Skip")
    while True:
        raw = input("Enter numbers: ").strip().lower()
        if skippable and raw == SKIP:
            return None
        if raw == "all":
            return options
        parts = [p.strip() for p in raw.split(",")]
        if all(p.isdigit() and 1 <= int(p) <= len(options) for p in parts):
            return [options[int(p) - 1] for p in parts]
        print(f"  Please enter valid numbers between 1 and {len(options)}, comma-separated." +
              (" Or 's' to skip." if skippable else ""))


def prompt_bool(question: str, skippable: bool = True) -> Optional[bool]:
    print(f"\n{question}")
    print("  1. Yes")
    print("  2. No")
    if skippable:
        print("  s. Skip")
    while True:
        raw = input("Enter number: ").strip().lower()
        if skippable and raw == SKIP:
            return None
        if raw == "1":
            return True
        if raw == "2":
            return False
        print("  Please enter 1 or 2." + (" Or 's' to skip." if skippable else ""))


def prompt_text(question: str, skippable: bool = True) -> Optional[str]:
    print(f"\n{question}")
    if skippable:
        print("  (or press Enter to skip)")
    raw = input("> ").strip()
    if skippable and not raw:
        return None
    return raw


def prompt_int(question: str, min_val: int, max_val: int, skippable: bool = True) -> Optional[int]:
    print(f"\n{question}")
    if skippable:
        print("  (or press Enter to skip)")
    while True:
        raw = input("Enter number: ").strip()
        if skippable and not raw:
            return None
        if raw.isdigit() and min_val <= int(raw) <= max_val:
            return int(raw)
        print(f"  Please enter a number between {min_val} and {max_val}." +
              (" Or press Enter to skip." if skippable else ""))


def run_setup():
    init_db()

    existing = get_profile()
    if existing:
        print("\nExisting profile found. Running setup will overwrite fields you answer.")
        print("Skip any question to keep its current value.")

    print("\n--- Just Sign Up: Profile Setup ---")
    print("This takes about 5 minutes. Skip any question by entering 's' or pressing Enter.")
    print("You can re-run this anytime to update your profile.\n")

    updates = {}

    faculty = prompt_choice(
        "What's your faculty?",
        ["Computing", "Engineering", "Business", "Science",
         "Arts & Social Sciences", "Law", "Medicine", "Design & Environment", "Other"]
    )
    if faculty is not None:
        updates["faculty"] = faculty

    year = prompt_choice(
        "What year are you in?",
        ["Y1", "Y2", "Y3", "Y4", "Masters", "PhD"]
    )
    if year is not None:
        updates["year"] = year

    career_clarity = prompt_choice(
        "How clear are you on your career direction?",
        ["Decided", "Have some ideas but still undecided", "Clueless"]
    )
    if career_clarity is not None:
        updates["career_clarity"] = career_clarity

    free_time = prompt_choice(
        "How much time are you willing to dedicate to enriching events per week?",
        ["Low (0-3h)", "Medium (3-5h)", "High (5-10h)", "Extreme Side Questing (10h+)"]
    )
    if free_time is not None:
        updates["free_time"] = free_time

    interest_tags = prompt_multiselect(
        "What are your interest areas? Pick all that apply.",
        INTEREST_TAGS
    )
    if interest_tags is not None:
        updates["interest_tags"] = json.dumps(interest_tags)

    bio = prompt_text(
        "Write 2-3 sentences about yourself — your goals, what you're looking for, "
        "anything that helps personalise your event recommendations."
    )
    if bio is not None:
        updates["bio"] = bio

    preferred_days = prompt_multiselect(
        "Which days are you generally free for events?",
        DAYS
    )
    if preferred_days is not None:
        updates["preferred_days"] = json.dumps(preferred_days)

    boost_refreshments = prompt_bool(
        "Give a scoring bonus to events with free food or drinks?"
    )
    if boost_refreshments is not None:
        updates["boost_refreshments"] = str(boost_refreshments)

    tone = prompt_choice(
        "What tone do you want for event recommendations?",
        ["Professional", "Casual", "Cheeky", "Brutal"]
    )
    if tone is not None:
        updates["tone"] = tone.lower()

    min_threshold = prompt_int(
        "Minimum relevancy score for an event to be stored at all? "
        "Events scoring below this are discarded entirely.",
        1, 10
    )
    if min_threshold is not None:
        updates["min_threshold"] = str(min_threshold)

    digest_frequency = prompt_choice(
        "How often do you want to receive your digest?",
        ["Daily", "2x in a week", "Weekly", "Biweekly"]
    )
    if digest_frequency is not None:
        updates["digest_frequency"] = digest_frequency

    if not updates:
        print("\nNo answers given, profile unchanged.")
        return

    save_profile(updates)

    print("\nProfile saved. Here's what was updated:\n")
    display = {
        "faculty":             updates.get("faculty"),
        "year":                updates.get("year"),
        "career_clarity":      updates.get("career_clarity"),
        "free_time":           updates.get("free_time"),
        "interests":           ", ".join(interest_tags) if interest_tags else None,
        "preferred_days":      ", ".join(preferred_days) if preferred_days else None,
        "boost_refreshments":  updates.get("boost_refreshments"),
        "tone":                updates.get("tone"),
        "digest_frequency":    updates.get("digest_frequency"),
        "bio":                 updates.get("bio"),
    }
    for key, val in display.items():
        if val is not None:
            print(f"  {key:<22} {val}")

    print("\nAll set. Run this again anytime with: python setup.py")


if __name__ == "__main__":
    run_setup()
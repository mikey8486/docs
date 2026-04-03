#!/usr/bin/env python3
"""Intent Weaver

A tiny CLI that turns messy human promises into a concrete execution plan.

Why it is unusual:
- It builds a "promise graph" from natural-language commitments.
- It predicts collision risk (time + cognitive load overlap).
- It generates anti-forgetting triggers and a realistic first-action plan.

No third-party dependencies required.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List


DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
HOURS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE)
ENERGY_PATTERN = re.compile(r"\b(low|medium|high)\s+energy\b", re.IGNORECASE)


@dataclass
class Commitment:
    text: str
    due: date
    est_hours: float
    energy: str


@dataclass
class PlanStep:
    day: date
    commitment_idx: int
    action: str
    minutes: int


def parse_commitment(line: str, default_due: date) -> Commitment:
    due_match = DATE_PATTERN.search(line)
    due = default_due
    if due_match:
        due = date.fromisoformat(due_match.group(1))

    hour_match = HOURS_PATTERN.search(line)
    est_hours = float(hour_match.group(1)) if hour_match else 2.0

    energy_match = ENERGY_PATTERN.search(line)
    energy = energy_match.group(1).lower() if energy_match else "medium"

    clean_text = line.strip().lstrip("-*").strip()
    return Commitment(text=clean_text, due=due, est_hours=est_hours, energy=energy)


def energy_weight(energy: str) -> float:
    return {"low": 0.8, "medium": 1.0, "high": 1.3}.get(energy, 1.0)


def collision_score(commitments: List[Commitment]) -> float:
    if len(commitments) < 2:
        return 0.0

    score = 0.0
    for i, a in enumerate(commitments):
        for b in commitments[i + 1 :]:
            day_distance = abs((a.due - b.due).days)
            deadline_pressure = math.exp(-day_distance / 4)
            load_overlap = min(a.est_hours * energy_weight(a.energy), b.est_hours * energy_weight(b.energy))
            score += deadline_pressure * load_overlap

    return round(score, 2)


def first_action(text: str) -> str:
    verbs = [
        "Draft",
        "Outline",
        "Research",
        "Prototype",
        "Message",
        "Schedule",
        "Review",
    ]
    words = [w for w in re.split(r"\W+", text) if w]
    if not words:
        return "Clarify the outcome in one sentence"
    head = " ".join(words[:6])
    verb = verbs[len(words) % len(verbs)]
    return f"{verb} the core of: '{head}'"


def build_plan(commitments: List[Commitment], start: date, daily_capacity_minutes: int) -> List[PlanStep]:
    remaining = [max(30, int(c.est_hours * 60)) for c in commitments]
    plan: List[PlanStep] = []

    sorted_indexes = sorted(
        range(len(commitments)),
        key=lambda i: (commitments[i].due, -energy_weight(commitments[i].energy), -commitments[i].est_hours),
    )

    day = start
    max_days = 45
    for _ in range(max_days):
        capacity = daily_capacity_minutes
        progressed = False

        for idx in sorted_indexes:
            if remaining[idx] <= 0:
                continue
            chunk = min(45, remaining[idx], capacity)
            if chunk <= 0:
                continue

            action = first_action(commitments[idx].text)
            plan.append(PlanStep(day=day, commitment_idx=idx, action=action, minutes=chunk))
            remaining[idx] -= chunk
            capacity -= chunk
            progressed = True

            if capacity <= 0:
                break

        if all(r <= 0 for r in remaining):
            break

        day += timedelta(days=1)
        if not progressed and day > start + timedelta(days=max_days):
            break

    return plan


def anti_forgetting_triggers(commitments: Iterable[Commitment]) -> list[str]:
    triggers = []
    for c in commitments:
        days_left = (c.due - date.today()).days
        urgency = "today" if days_left <= 0 else f"in {days_left} day(s)"
        triggers.append(
            f"If it's 9:00 PM and '{c.text[:45]}' has no progress, block 25 minutes before sleep ({urgency})."
        )
    return triggers


def load_commitments(path: Path) -> list[Commitment]:
    raw = json.loads(path.read_text())
    lines = raw.get("commitments", [])
    if not isinstance(lines, list):
        raise ValueError("Input JSON must include a list field named 'commitments'.")

    default_due = date.today() + timedelta(days=7)
    return [parse_commitment(str(line), default_due) for line in lines]


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert commitments into an executable anti-forgetting plan.")
    parser.add_argument("input", type=Path, help="Path to JSON with a 'commitments' list")
    parser.add_argument("--daily-minutes", type=int, default=120, help="Daily planning capacity in minutes")
    args = parser.parse_args()

    commitments = load_commitments(args.input)
    if not commitments:
        print("No commitments found.")
        return 0

    risk = collision_score(commitments)
    plan = build_plan(commitments, start=date.today(), daily_capacity_minutes=args.daily_minutes)
    triggers = anti_forgetting_triggers(commitments)

    output = {
        "software": "Intent Weaver",
        "generated_on": str(date.today()),
        "collision_risk_score": risk,
        "commitments": [
            {
                "text": c.text,
                "due": str(c.due),
                "estimated_hours": c.est_hours,
                "energy": c.energy,
            }
            for c in commitments
        ],
        "first_actions": [first_action(c.text) for c in commitments],
        "anti_forgetting_triggers": triggers,
        "plan": [
            {
                "date": str(step.day),
                "commitment": commitments[step.commitment_idx].text,
                "minutes": step.minutes,
                "action": step.action,
            }
            for step in plan
        ],
    }

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

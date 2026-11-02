"""Optional written fit summary. Sends only the job description and your skills list, never the resume."""
from __future__ import annotations

import os

import httpx

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def fit_summary(job: dict, skills: list[str], years: float) -> str:
    if not available():
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
    jd = (job.get("description") or "")[:6000]
    prompt = (
        "You are helping an analytics professional decide whether to apply.\n"
        f"Candidate skills: {', '.join(skills)}\nCandidate experience: {years:g} years\n\n"
        f"Job: {job.get('title')} at {job.get('company')}\nJob description:\n{jd}\n\n"
        "In at most 70 words: say how well the candidate fits, the two strongest matching points, and the main gap. "
        "Plain sentences, no headings, no bullet points.")
    r = httpx.post(
        "https://api.anthropic.com/v1/messages", timeout=40,
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": 220, "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic API returned HTTP {r.status_code}: {r.text[:200]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()

#!/usr/bin/env python3
"""
Grow the per-lane training data by running a batch of real, lane-specific directives
against the running FINESSE server. Each run writes a grounded deliverable into the
vault, which export_dataset.py then turns into a per-lane SFT example.

Re-runnable — run it whenever you want more data, then re-export:
    python training/generate_data.py                 # full default batch
    python training/generate_data.py --per-lane 3    # quick, fewer per lane
    python training/generate_data.py --lanes coding,security

Uses /api/agent/run so each deliverable is cleanly tagged to ONE lane. Sequential +
polite (free-tier NIM); the F2 retry keeps it alive through timeouts.
"""
from __future__ import annotations
import argparse
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

B = "http://localhost:8600"

# agent_key -> diverse, Sastrava-relevant tasks (each produces one lane-tagged deliverable)
TASKS: dict[str, list[str]] = {
    "coding": [
        "Write a Python FastAPI endpoint that accepts a webhook and validates an HMAC signature.",
        "Design a token-bucket rate-limiter middleware for FastAPI; show the code and how to test it.",
        "Implement an async retry decorator with exponential backoff for httpx calls.",
        "Write a SQL schema plus core queries for a student progress tracker (courses, lessons, completions).",
        "Write a Python function that chunks long transcripts into overlapping windows for RAG.",
        "Build a small CLI that exports a folder of Obsidian notes to a static HTML site.",
        "Write a script to batch-resize and watermark a folder of course thumbnails.",
    ],
    "marketing": [
        "Create a 4-email nurture sequence for a new 'AI for business' course launch.",
        "Write 5 LinkedIn post hooks for Sastrava targeting SME owners exploring AI.",
        "Draft an SEO content plan: 10 article titles with target keywords for 'AI automation for small business'.",
        "Write 3 Google Ads copy variations promoting an AI bootcamp, with the KPIs to track.",
        "Write a landing-page outline and hero copy for an AI consulting offer.",
        "Create a 7-day Instagram content calendar for an AI education brand.",
        "Design a webinar promotion plan across email, LinkedIn, and WhatsApp.",
    ],
    "prompt": [
        "Turn 'help me write better emails' into a precise, reusable prompt with variables and eval criteria.",
        "Write a system prompt for a support agent that never invents policy; include guardrails.",
        "Design a few-shot prompt template for extracting action items from meeting notes.",
        "Create a parameterized prompt that rewrites copy into a specified brand voice.",
        "Write an evaluation rubric and prompt to grade a summary's faithfulness to its source.",
        "Write a prompt that converts a vague feature request into a structured PRD.",
    ],
    "bizdev": [
        "Draft a cold outreach email proposing an AI workshop to a mid-size edtech company (invent no facts).",
        "Create a discovery-call question script for qualifying AI-consulting leads.",
        "Write a one-page proposal template for an AI automation pilot engagement.",
        "Design a lead-scoring rubric for inbound AI-course inquiries.",
        "Write a follow-up sequence for leads who attended a webinar but didn't book.",
        "Create an ICP definition plus objection-handling notes for Sastrava's AI services.",
    ],
    "security_audit": [
        "Review a JWT auth design for token-forgery and expiry risks; recommend concrete fixes.",
        "Audit an RBAC model for privilege-escalation paths and missing tier checks.",
        "Produce a checklist to harden a FastAPI app for production (headers, rate limits, secrets).",
        "Assess prompt-injection risks in an LLM tool-calling agent and list mitigations.",
        "Explain safe secret management: what to keep out of code and how to rotate keys.",
        "Threat-model a file-upload data gateway for path traversal and malware, with mitigations.",
    ],
    "general": [
        "Summarize best practices for onboarding a new AI engineer at a small startup.",
        "Draft an SOP for handling a client data-deletion request.",
        "Write a concise explainer of RAG for a non-technical executive.",
        "Outline a weekly operations cadence for a 10-person AI services company.",
        "Draft a knowledge-base article on how a multi-agent orchestra works.",
    ],
}


def main():
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-lane", type=int, default=99, help="cap tasks per lane")
    ap.add_argument("--lanes", default="", help="comma list of agent keys; blank = all")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()
    email = os.environ.get("CEO_EMAIL", "")
    password = os.environ.get("CEO_PASSWORD", "")
    if not email or not password:
        ap.error("set CEO_EMAIL and CEO_PASSWORD in the local .env file")

    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + s.post(
        f"{B}/api/login", json={"email": email, "password": password}, timeout=15
    ).json()["token"]

    want = [x.strip() for x in args.lanes.split(",") if x.strip()] or list(TASKS)
    total = ok = fail = 0
    t_start = time.time()
    for agent_key in want:
        tasks = TASKS.get(agent_key, [])[: args.per_lane]
        for i, task in enumerate(tasks, 1):
            total += 1
            t0 = time.time()
            try:
                r = s.post(f"{B}/api/agent/run",
                           json={"agent_key": agent_key, "task": task}, timeout=args.timeout)
                d = r.json()
                dt = time.time() - t0
                if r.status_code == 200:
                    ok += 1
                    print(f"[OK ] {agent_key:14} {i}/{len(tasks)} {dt:5.0f}s "
                          f"{len(d.get('output','')):5} chars | {task[:52]}", flush=True)
                else:
                    fail += 1
                    print(f"[ERR] {agent_key:14} {r.status_code} | {task[:52]}", flush=True)
            except Exception as e:  # noqa: BLE001
                fail += 1
                print(f"[ERR] {agent_key:14} {type(e).__name__} | {task[:52]}", flush=True)
            time.sleep(1)

    mins = (time.time() - t_start) / 60
    print(f"\nDONE: {ok}/{total} deliverables in {mins:.1f} min ({fail} failed).")
    print("Next: python training/export_dataset.py   # re-export to refresh per-lane counts")


if __name__ == "__main__":
    main()

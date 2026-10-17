#!/usr/bin/env python3
"""
Export the FINESSE brain into instruction-tuning datasets for LoRA / QLoRA.

Writes a unified set AND per-lane sets (for per-lane adapters):
  training/data/finesse_sft.jsonl              everything
  training/data/finesse_sft_<lane>.jsonl       one per lane (coding/marketing/security/...)

Each line is {"messages":[system, user, assistant]}. Sources (human-in-the-loop content
already in the vault — never .env/data/):
  09_Projects/_Deliverables    directive -> deliverable   (task pairs; lane from `agents:`)
  11_Knowledge_Base/_Injected  injected docs              (lane from `role:`)
  04_AI_Agents/_Engine         agent mandates             (lane from `lane:`)
  13_AI_Memory                 learned patterns           (lane = shared)

    python training/export_dataset.py
    python training/export_dataset.py --min-chars 200 --max-chars 6000
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
OUTDIR = Path(__file__).resolve().parent / "data"

SYSTEM = ("You are a Sastrava FINESSE agent — precise, grounded, and production-grade. "
          "Use only facts you are given; never invent. End substantial work with a short "
          "'Needs human review:' note.")

# agent-key / role -> lane
_LANE = {"coding": "coding", "prompt": "prompt", "marketing": "marketing", "bizdev": "bizdev",
         "leadgen": "bizdev", "general": "general", "security_audit": "security",
         "security": "security", "synth": "exec", "orchestrator_planner": "exec",
         "shared": "shared", "exec": "exec"}
_FRONT = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_JUNK = ("OFFLINE MODE", "Would answer:", "set NVIDIA_API_KEY", "[agent error",
         "APITimeoutError", "LLM analysis unavailable", "TOOL ERROR", "offline-stub")


def _is_junk(text: str) -> bool:
    return any(m in text for m in _JUNK)


def _strip_front(text: str) -> tuple[dict, str]:
    fm: dict[str, str] = {}
    m = _FRONT.match(text)
    body = text
    if m:
        for line in m.group(0).splitlines():
            if ":" in line and not line.startswith("---"):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        body = text[m.end():]
    return fm, body


def _clean(s: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", s.strip())


def _lane_from_agents(fm: dict) -> str:
    raw = (fm.get("agents") or "").strip("[] ")
    first = raw.split(",")[0].strip() if raw else ""
    return _LANE.get(first, "general")


def _ex(user: str, assistant: str) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user.strip()},
                         {"role": "assistant", "content": assistant.strip()}]}


def deliverables():
    d = VAULT / "09_Projects" / "_Deliverables"
    for md in (d.rglob("*.md") if d.is_dir() else []):
        fm, body = _strip_front(md.read_text(encoding="utf-8", errors="ignore"))
        directive = fm.get("title") or (body.splitlines()[0].lstrip("# ").strip() if body else "")
        content = _clean(body.rsplit("\n---\n\n", 1)[-1] if "\n---\n\n" in body else body)
        if directive and content:
            yield _lane_from_agents(fm), _ex(directive, content)


def injected():
    d = VAULT / "11_Knowledge_Base" / "_Injected"
    for md in (d.rglob("*.md") if d.is_dir() else []):
        fm, body = _strip_front(md.read_text(encoding="utf-8", errors="ignore"))
        title = fm.get("title") or md.stem
        body = _clean(body)
        if body:
            yield _LANE.get(fm.get("role", "shared"), "shared"), \
                _ex(f"What does Sastrava know about: {title}? Summarize the source faithfully.", body)


def agents():
    d = VAULT / "04_AI_Agents" / "_Engine"
    for md in (d.rglob("*.md") if d.is_dir() else []):
        text = md.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"## Mandate\n```\n(.*?)\n```", text, re.DOTALL)
        if m:
            fm, _ = _strip_front(text)
            title = fm.get("title") or md.stem.replace("_", " ")
            yield _LANE.get(fm.get("lane", "general"), "general"), \
                _ex(f"Describe your mandate and how you operate as the {title}.", _clean(m.group(1)))


def memory():
    p = VAULT / "13_AI_Memory" / "Shared_Consciousness.md"
    if not p.exists():
        return
    for m in re.finditer(r"\*\*\[[^\]]+\]\s*(\w+)\*\*.*?\n\s*>\s*(.+)",
                         p.read_text(encoding="utf-8", errors="ignore")):
        snippet = _clean(m.group(2))
        if len(snippet) > 60:
            yield "shared", _ex(f"Recall a learned {m.group(1)} from the org's shared memory.", snippet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-chars", type=int, default=120)
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--outdir", type=Path, default=OUTDIR)
    args = ap.parse_args()

    seen: set[str] = set()
    all_rows: list[dict] = []
    by_lane: dict[str, list[dict]] = defaultdict(list)
    by_src: dict[str, int] = defaultdict(int)

    for src, gen in (("deliverable", deliverables), ("injected", injected),
                     ("agent", agents), ("memory", memory)):
        for lane, ex in gen():
            ans = ex["messages"][-1]["content"]
            if len(ans) < args.min_chars or _is_junk(ans):
                continue
            if len(ans) > args.max_chars:
                ex["messages"][-1]["content"] = ans[:args.max_chars]
            h = hashlib.md5(ex["messages"][-1]["content"][:400].encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            all_rows.append(ex)
            by_lane[lane].append(ex)
            by_src[src] += 1

    args.outdir.mkdir(parents=True, exist_ok=True)

    def _write(path: Path, rows: list[dict]):
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _write(args.outdir / "finesse_sft.jsonl", all_rows)
    for lane, rows in by_lane.items():
        _write(args.outdir / f"finesse_sft_{lane}.jsonl", rows)

    print(f"wrote {len(all_rows)} SFT examples -> {args.outdir}")
    print("  by source:", dict(by_src))
    print("  by lane  :")
    for lane, rows in sorted(by_lane.items(), key=lambda x: -len(x[1])):
        flag = "  <- thin, grow before a per-lane adapter" if len(rows) < 60 else ""
        print(f"    {lane:10} {len(rows):4}{flag}")


if __name__ == "__main__":
    main()

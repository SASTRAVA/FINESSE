#!/usr/bin/env python3
"""
Merge the QLoRA adapter back into the base weights -> a standalone model you can
serve at an OpenAI-compatible endpoint (vLLM / llama.cpp). Runs on CPU (slow but fine).

    python training/merge_adapter.py
    python training/merge_adapter.py --base Qwen/Qwen2.5-7B-Instruct --adapter training/adapters/finesse-qlora

Then serve it and point .env at it:
    python -m vllm.entrypoints.openai.api_server --model training/merged/finesse-merged --port 8000
    # .env:
    #   LOCAL_LLM_BASE_URL=http://localhost:8000/v1
    #   LOCAL_LLM_MODEL=finesse-merged
The provider auto-routes the heavy (coding/orchestrator) roles to it; NIM stays as fallback.
"""
from __future__ import annotations
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--adapter", type=Path, default=HERE / "adapters" / "finesse-qlora")
    ap.add_argument("--out", type=Path, default=HERE / "merged" / "finesse-merged")
    args = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    if not args.adapter.exists():
        raise SystemExit(f"[merge] adapter not found: {args.adapter} — train it first.")

    print(f"[merge] {args.base}  +  {args.adapter}")
    base = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16,
                                                device_map="cpu")
    merged = PeftModel.from_pretrained(base, str(args.adapter)).merge_and_unload()
    args.out.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(args.out), safe_serialization=True)
    AutoTokenizer.from_pretrained(str(args.adapter)).save_pretrained(str(args.out))
    print(f"[merge] merged model -> {args.out}")
    print("[merge] serve:  python -m vllm.entrypoints.openai.api_server "
          f"--model {args.out} --port 8000")


if __name__ == "__main__":
    main()

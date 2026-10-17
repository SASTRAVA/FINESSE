#!/usr/bin/env python3
"""
QLoRA fine-tune on the FINESSE brain (4-bit — quantization all the way, per the
turboquant ethos). Trains a small LoRA adapter on training/data/finesse_sft.jsonl.

Needs a CUDA GPU (bitsandbytes 4-bit). ~8-12 GB VRAM for a 7-8B base at seq 1024.
No GPU? Run this same file on a free Colab/Kaggle T4 — the dataset is portable.

    python training/train_qlora.py                         # sane defaults
    python training/train_qlora.py --base meta-llama/Llama-3.1-8B-Instruct --epochs 3

Output: an adapter in training/adapters/<name>/. Merge + serve it with
merge_adapter.py, then point .env LOCAL_LLM_* at it — the provider auto-routes the
heavy (coding/orchestrator) roles to your local model, keeping NIM as fallback.
"""
from __future__ import annotations
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DATA = HERE / "data" / "finesse_sft.jsonl"
DEFAULT_OUT = HERE / "adapters" / "finesse-qlora"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct", help="base instruct model")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--r", type=int, default=16, help="LoRA rank")
    ap.add_argument("--alpha", type=int, default=32, help="LoRA alpha")
    ap.add_argument("--dropout", type=float, default=0.05)
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, prepare_model_for_kbit_training
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        raise SystemExit("[train] no CUDA GPU visible. QLoRA needs one — run on a GPU box/Colab.")
    if not args.data.exists():
        raise SystemExit(f"[train] dataset missing: {args.data} — run export_dataset.py first.")

    print(f"[train] base={args.base}  data={args.data}  epochs={args.epochs}  r={args.r}")

    # --- 4-bit quantized base (QLoRA) ---
    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.base, quantization_config=bnb, device_map="auto", torch_dtype=torch.bfloat16)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        r=args.r, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])

    ds = load_dataset("json", data_files=str(args.data), split="train")

    def fmt(batch):
        # render each example's chat messages with the base model's own template
        return [tok.apply_chat_template(m, tokenize=False, add_generation_prompt=False)
                for m in batch["messages"]]

    cfg = SFTConfig(
        output_dir=str(args.out), num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr, warmup_ratio=0.03, lr_scheduler_type="cosine",
        logging_steps=5, save_strategy="epoch", bf16=True, optim="paged_adamw_8bit",
        max_seq_length=args.max_seq, gradient_checkpointing=True, report_to="none")

    trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds,
                         peft_config=lora, formatting_func=fmt, processing_class=tok)
    trainer.train()

    args.out.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(args.out))
    tok.save_pretrained(str(args.out))
    print(f"[train] adapter saved -> {args.out}\n[train] next: python training/merge_adapter.py")


if __name__ == "__main__":
    main()

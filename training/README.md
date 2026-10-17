# FINESSE — LoRA / QLoRA fine-tuning

Teach small **local** models the Sastrava house style + the vault's knowledge, then serve
them so the orchestra runs on *your* models (cheaper, faster, private) with NIM as fallback.
QLoRA = 4-bit base + a tiny LoRA adapter — quantization end to end (turboquant ethos).

```
export_dataset.py  ->  finesse_qlora_colab.ipynb  ->  merge_adapter.py  ->  vLLM  ->  .env LOCAL_LLM_*
   (local, done)          (free Colab T4)               (local/CPU)         (GPU)     (auto-routes)
```

## Your chosen plan
- **Train on:** free **Colab / Kaggle T4** → use [`finesse_qlora_colab.ipynb`](finesse_qlora_colab.ipynb).
- **Base models:** *all of them* — the notebook is parameterized; re-run cells 3–5 with
  `BASE =` `Qwen/Qwen2.5-7B-Instruct`, then `meta-llama/Llama-3.1-8B-Instruct`, then
  `Qwen/Qwen2.5-3B-Instruct`. (Llama needs a HF token + license.)
- **Scope:** *per-lane adapters* — the exporter already writes one file per lane.

## ⚠️ Read this first — the data isn't ready for per-lane yet
Current export (`python training/export_dataset.py`):

| lane | examples | | lane | examples |
|---|---|---|---|---|
| shared | 160 | | prompt | 12 |
| coding | 24 | | exec | 5 |
| general | 16 | | marketing / bizdev | 3 |
| | | | security | 1 |

A LoRA needs ~**200+ quality examples per lane** to learn a lane's style. Right now only
`shared` qualifies. **So:**
1. **Now:** train ONE **unified** adapter on `finesse_sft.jsonl` (224 ex) to prove the loop.
2. **Grow:** keep running directives per lane + injecting lane docs; re-export — the per-lane
   files fill up automatically.
3. **Then:** train `finesse_sft_coding.jsonl`, `_marketing`, `_security`, … as they cross ~200.

## Steps
1. **Export (local, no GPU):**
   ```powershell
   python training/export_dataset.py
   ```
   → `training/data/finesse_sft.jsonl` + `finesse_sft_<lane>.jsonl` (skips offline-stub junk).
2. **Train (Colab T4):** open `finesse_qlora_colab.ipynb`, set T4 runtime, upload the jsonl,
   run. Download the adapter zip.
3. **Merge + serve (local):**
   ```powershell
   # unzip adapter into training/adapters/<name>/ first
   python training/merge_adapter.py --adapter training/adapters/<name>
   python -m vllm.entrypoints.openai.api_server --model training/merged/finesse-merged --port 8000
   ```
4. **Wire it in:**
   ```dotenv
   LOCAL_LLM_BASE_URL=http://localhost:8000/v1
   LOCAL_LLM_MODEL=finesse-merged
   ```
   `provider._route()` already sends the heavy roles here, NIM as fallback — no code change.

> `train_qlora.py` / `merge_adapter.py` are the local-GPU equivalents of the notebook, if you
> ever attach a CUDA card here. `requirements-training.txt` pins the versions the code targets.

## Serving per-lane adapters (later, once you have them)
vLLM can serve multiple LoRAs at once (`--enable-lora --lora-modules coding=... marketing=...`)
and pick one per request by `model=`. When you have real per-lane adapters, ping me — I'll add
a `LANE_ADAPTERS` map + make each agent request its lane's adapter (a small `provider` change).
Building that now would be speculative — the data has to exist first.

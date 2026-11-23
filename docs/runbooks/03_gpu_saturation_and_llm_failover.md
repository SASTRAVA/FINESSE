# GPU saturation and local model failover

1. Check `/healthz`, `/readyz`, container health, host memory, GPU/VRAM usage,
   and Ollama process logs. Record model name, concurrency, queue depth, and
   timestamp; avoid recording prompts.
2. In portable Compose, FINESSE local inference concurrency defaults to 2,
   `OLLAMA_NUM_PARALLEL` defaults to 2, and `OLLAMA_MAX_LOADED_MODELS` defaults
   to 1. Reduce those values in the operator's env file and restart during a
   maintenance window if memory pressure persists.
3. Let the local admission semaphore and provider timeout/circuit handling shed
   excess work. Do not enable external cloud fallback for confidential or
   restricted data. If required, disable new inference with the applicable
   tenant/global kill switch and inform active users.
4. After recovery, verify the requested model is loaded, run a small synthetic
   prompt, and check readiness plus error/latency metrics before resuming work.

GPU exporters, distributed queue depth, and model-specific performance SLOs are
not deployed in this repository. CPU/GPU throughput must be measured on target
hardware.

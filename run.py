#!/usr/bin/env python3
"""
SASTRAVA FINESSE — universal launcher.

    python run.py            # start the API + dashboard  (http://localhost:8600)
    python run.py --index    # (re)index the vault into the brain, then exit
    python run.py --seed     # create a few demo employees, then exit

One process, fully async, handles concurrent users. No Node required — the
dashboard is served by FastAPI itself.
"""
import sys
import asyncio


def _index(argv=None):
    from scripts.index_vault import main as index_main
    asyncio.run(index_main(argv))


def _seed():
    from scripts.seed_users import main as seed_main
    seed_main()


def _reweave():
    from engine.obsidian.weave import reweave
    print("[reweave] reconnecting the vault…")
    stats = reweave()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("[reweave] done. Open Obsidian on FINESSE/vault to see the graph.")


def _manifest():
    from engine.obsidian.manifest import write_manifest
    print("[manifest] generating the Karpathy wiring layer…")
    stats = write_manifest()
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("[manifest] wrote vault/vault_manifest.json + vault/00_Home/FINESSE_System_Map.md")


def _serve():
    import os
    import uvicorn
    from engine.config import cfg, validate_startup_config
    validate_startup_config()
    os.chdir(cfg.ROOT)   # ensure relative paths resolve to the FINESSE project root
    print("=" * 56)
    print("  SASTRAVA · FINESSE")
    print("=" * 56)
    print(f"  Dashboard : http://{cfg.APP_HOST}:{cfg.APP_PORT}")
    print(f"  Vault     : {cfg.VAULT}")
    print(f"  NIM key   : {'set' if cfg.has_nim else 'NOT SET (offline stub)'}")
    print(f"  Local GPU : {'set' if cfg.has_local_llm else 'not attached'}")
    print("  Tip: run  python run.py --index  once to load the brain.")
    print("=" * 56)
    uvicorn.run("engine.main:app", host=cfg.HOST, port=cfg.PORT, workers=1)


if __name__ == "__main__":
    if "--index" in sys.argv:
        _index([arg for arg in sys.argv[1:] if arg != "--index"])
    elif "--seed" in sys.argv:
        _seed()
    elif "--reweave" in sys.argv:
        _reweave()
    elif "--manifest" in sys.argv:
        _manifest()
    else:
        _serve()

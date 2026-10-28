"""Run a training module under a hard per-process VRAM cap (gojo GPU shared with Dizzy, 2026-10-28)."""
import os, runpy, sys
import torch
cap_gb = float(os.environ.get("SV_VRAM_CAP_GB", "4.3"))
if torch.cuda.is_available():
    total = torch.cuda.get_device_properties(0).total_memory / 1e9
    torch.cuda.set_per_process_memory_fraction(min(1.0, cap_gb / total))
    print(f"VRAM cap {cap_gb} GB of {total:.1f} GB", flush=True)
sys.path.insert(0, os.getcwd())  # services/worker, for the training package
mod = sys.argv[1]
sys.argv = [mod] + sys.argv[2:]
runpy.run_module(mod, run_name="__main__")

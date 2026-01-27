import sys
import platform

try:
    import torch
except Exception as e:
    print("ERROR: Could not import torch:", e)
    sys.exit(1)

print("=== PYTHON & TORCH ENV CHECK ===")
print("Python:", sys.version.replace("\n", " "))
print("Platform:", platform.platform())
print("Torch version:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())

if torch.cuda.is_available():
    print("CUDA device count:", torch.cuda.device_count())
    for i in range(torch.cuda.device_count()):
        print(f" - Device {i}: {torch.cuda.get_device_name(i)}")
else:
    print("No GPU detected. Will run on CPU (much slower).")

print("=== DONE ===")

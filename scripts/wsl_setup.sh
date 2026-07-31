#!/bin/bash
# =============================================================================
# WSL2 Setup Script for InstaDeepAI Nucleotide Transformer
# =============================================================================
# Run this inside Ubuntu WSL2 shell after running the PowerShell setup commands
# Usage: bash /mnt/c/Users/ushni/Documents/SYNTH VEDA/scripts/wsl_setup.sh
# =============================================================================

set -e  # Exit on error

REPO_PATH="/mnt/c/Users/ushni/Documents/SYNTH VEDA"
VENV_NAME="wsl_env"

echo "=============================================="
echo "WSL2 Setup for InstaDeepAI Nucleotide Transformer"
echo "=============================================="

# 1. Update apt and install prerequisites
echo ""
echo "[1/7] Installing apt prerequisites..."
sudo apt update
sudo apt install -y build-essential curl git ca-certificates wget software-properties-common

# 2. Install Python 3.10
echo ""
echo "[2/7] Ensuring Python 3.10..."
if ! command -v python3.10 &> /dev/null; then
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt update
    sudo apt install -y python3.10 python3.10-venv python3.10-dev
fi
python3.10 --version

# 3. Verify NVIDIA drivers and CUDA in WSL
echo ""
echo "[3/7] Verifying NVIDIA GPU access in WSL..."
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi
    echo "[OK] nvidia-smi works in WSL"
else
    echo "[WARNING] nvidia-smi not found. NVIDIA drivers may not be installed."
    echo "Please install NVIDIA drivers on Windows and ensure 'nvidia-smi' works in WSL."
    echo "Download: https://developer.nvidia.com/cuda/wsl"
fi

# 4. Create virtual environment
echo ""
echo "[4/7] Creating Python virtual environment..."
cd "$REPO_PATH"

if [ -d "$VENV_NAME" ]; then
    echo "Virtual environment '$VENV_NAME' already exists. Removing..."
    rm -rf "$VENV_NAME"
fi

python3.10 -m venv "$VENV_NAME"
source "$VENV_NAME/bin/activate"

echo "Python: $(which python)"
echo "Version: $(python --version)"

# 5. Upgrade pip
echo ""
echo "[5/7] Upgrading pip..."
pip install --upgrade pip wheel setuptools

# 6. Install PyTorch with CUDA support (CUDA 11.8 for RTX 3070 compatibility)
echo ""
echo "[6/7] Installing PyTorch with CUDA 11.8..."
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Verify CUDA
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# 7. Install transformers and dependencies
echo ""
echo "[7/7] Installing transformers, accelerate, and dependencies..."

# Core dependencies
pip install transformers==4.40.0  # Use 4.40.x which has better ESM support
pip install accelerate
pip install datasets
pip install biopython
pip install scikit-learn
pip install pandas
pip install numpy
pip install tqdm

# ESM model support (required for InstaDeepAI nucleotide-transformer)
pip install fair-esm || echo "[WARNING] fair-esm install may have failed, but transformers ESM should work"

echo ""
echo "=============================================="
echo "Verifying installation..."
echo "=============================================="

# Verify imports
python -c "
import torch
print(f'PyTorch: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')

from transformers import AutoModel, AutoTokenizer, AutoConfig
print('transformers imports OK')

# Try loading InstaDeepAI model config
config = AutoConfig.from_pretrained('InstaDeepAI/nucleotide-transformer-500m-human-ref', trust_remote_code=True)
print(f'InstaDeepAI config loaded: hidden_size={config.hidden_size}')

# Try loading the full model
print('Loading InstaDeepAI model (this may take a few minutes on first run)...')
model = AutoModel.from_pretrained('InstaDeepAI/nucleotide-transformer-500m-human-ref', trust_remote_code=True)
print(f'SUCCESS! Model type: {type(model).__name__}')
print(f'Parameters: {sum(p.numel() for p in model.parameters()):,}')
"

echo ""
echo "=============================================="
echo "WSL2 SETUP COMPLETE!"
echo "=============================================="
echo ""
echo "Next steps:"
echo "  1. Run training: bash $REPO_PATH/scripts/wsl_train_nt.sh"
echo "  2. Run inference: bash $REPO_PATH/scripts/wsl_infer_nt.sh"
echo ""

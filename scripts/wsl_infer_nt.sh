#!/bin/bash
# =============================================================================
# WSL2 Inference Script for InstaDeepAI Nucleotide Transformer
# =============================================================================
# Run this inside Ubuntu WSL2 shell after training completes
# Usage: bash /mnt/c/Users/ushni/Documents/SYNTH VEDA/scripts/wsl_infer_nt.sh
# =============================================================================

set -e

REPO_PATH="/mnt/c/Users/ushni/Documents/SYNTH VEDA"
VENV_NAME="wsl_env"
MODEL_PATH="$REPO_PATH/models/trained_nt"

echo "=============================================="
echo "WSL2 Inference: InstaDeepAI Nucleotide Transformer"
echo "=============================================="

cd "$REPO_PATH"

# Activate virtual environment
echo "[*] Activating virtual environment..."
source "$VENV_NAME/bin/activate"

echo "Model path: $MODEL_PATH"
echo ""

# Verify model files exist
echo "[*] Checking model files..."
ls -lh "$MODEL_PATH/"

# Run inference
echo ""
echo "[*] Running inference test..."
echo ""

python -c "
import json
from src.species_identification.nt_inference import predict_batch, get_model_info

# Test sequences
test_sequences = [
    'ATGCGTACGTAGCTAGCTGACTGATCGTAGCTAGCTAGCTAG',
    'GGGGCCCCAAAATTTTCCCCGGGGAAAATTTTCCCC',
    'TTTTAAAACCCGGGGAAAATTTTCCCCGGGGAAAATTTT'
]

print('Testing predict_batch...')
print('')

results = predict_batch(test_sequences)

print('Results:')
print(json.dumps(results, indent=2))

print('')
print('Model Info:')
info = get_model_info()
for k, v in info.items():
    if k != 'config':
        print(f'  {k}: {v}')
"

echo ""
echo "=============================================="
echo "INFERENCE COMPLETE!"
echo "=============================================="
echo ""
echo "The model is ready for use with FastAPI on Windows."
echo "Start the server with:"
echo "  cd \"C:\\Users\\ushni\\Documents\\SYNTH VEDA\""
echo "  .\\gpu_env\\Scripts\\activate"
echo "  uvicorn src.web_api.main:app --host 127.0.0.1 --port 8000"
echo ""

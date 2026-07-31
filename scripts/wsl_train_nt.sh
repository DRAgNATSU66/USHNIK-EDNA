#!/bin/bash
# =============================================================================
# WSL2 Training Script for InstaDeepAI Nucleotide Transformer
# =============================================================================
# Run this inside Ubuntu WSL2 shell after running wsl_setup.sh
# Usage: bash /mnt/c/Users/ushni/Documents/SYNTH VEDA/scripts/wsl_train_nt.sh
# =============================================================================

set -e

REPO_PATH="/mnt/c/Users/ushni/Documents/SYNTH VEDA"
VENV_NAME="wsl_env"
MODEL_NAME="InstaDeepAI/nucleotide-transformer-500m-human-ref"
OUTPUT_DIR="$REPO_PATH/models/trained_nt"
LOG_FILE="$REPO_PATH/scripts/wsl_train_logs.txt"

echo "=============================================="
echo "WSL2 Training: InstaDeepAI Nucleotide Transformer"
echo "=============================================="

cd "$REPO_PATH"

# Activate virtual environment
echo "[*] Activating virtual environment..."
source "$VENV_NAME/bin/activate"

echo "Python: $(which python)"
echo "Model: $MODEL_NAME"
echo "Output: $OUTPUT_DIR"
echo ""

# Verify CUDA
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"CPU\"}')"

# Step 1: Data conversion (if needed)
echo ""
echo "[1/3] Checking/creating processed data..."
if [ ! -f "$REPO_PATH/data/processed/train.jsonl" ]; then
    echo "Running data conversion..."
    python src/data/convert.py \
        --input data/reference_db/reference_small_aug10.csv \
        --output data/processed \
        --min-length 30
else
    echo "Processed data already exists."
fi

# Verify data files
echo "Data files:"
ls -la "$REPO_PATH/data/processed/"

# Step 2: Training
echo ""
echo "[2/3] Starting training..."
echo "Full output will be saved to: $LOG_FILE"
echo ""

# Clear output directory to ensure fresh training
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

# Run training with output to both console and log file
python src/species_identification/train_nt.py \
    --train data/processed/train.jsonl \
    --val data/processed/val.jsonl \
    --label_map data/processed/label_map.json \
    --model_name "$MODEL_NAME" \
    --output_dir "$OUTPUT_DIR" \
    --epochs 1 \
    --batch_size 2 \
    --accumulation_steps 4 \
    --lr 2e-3 \
    --max_length 512 \
    2>&1 | tee "$LOG_FILE"

# Step 3: Verify output
echo ""
echo "[3/3] Verifying trained model..."
echo ""
echo "Model files in $OUTPUT_DIR:"
ls -lh "$OUTPUT_DIR/"

echo ""
echo "training_config.json contents:"
cat "$OUTPUT_DIR/training_config.json"

echo ""
echo "=============================================="
echo "TRAINING COMPLETE!"
echo "=============================================="
echo ""
echo "Model saved to: $OUTPUT_DIR"
echo "This path is accessible from Windows at:"
echo "  C:\\Users\\ushni\\Documents\\SYNTH VEDA\\models\\trained_nt\\"
echo ""
echo "Next: Run inference test with:"
echo "  bash $REPO_PATH/scripts/wsl_infer_nt.sh"
echo ""

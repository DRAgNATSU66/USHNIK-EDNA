# src/species_identification/train_dnabert.py
"""
GPU Training Script for DNABERT-2 Fine-tuning on eDNA Species Classification

Uses HuggingFace Transformers + PEFT (LoRA) for efficient fine-tuning.
Designed for RTX 3070 (8GB VRAM) with fp16 and gradient accumulation.

Usage:
  python src/species_identification/train_dnabert.py \
    --train data/processed/train.jsonl \
    --val data/processed/val.jsonl \
    --label_map data/processed/label_map.json \
    --output_dir models/trained_dnabert \
    --epochs 10 --batch_size 4 --accumulation_steps 2
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# ============================================================================
# Note: If using DNABERT-2 on Linux, you may need to install triton.
# On Windows, use bert-base-uncased (default) or another model without triton deps.
# ============================================================================

import torch
import numpy as np
from torch.utils.data import Dataset

# HuggingFace imports
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    AutoConfig,
    TrainingArguments,
    Trainer,
    EarlyStoppingCallback,
    DataCollatorWithPadding
)
from peft import LoraConfig, get_peft_model, TaskType

# Metrics
from sklearn.metrics import accuracy_score, f1_score


def load_jsonl(path: str) -> List[Dict]:
    """Load JSONL file into list of dicts."""
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def load_label_map(path: str) -> Dict[str, int]:
    """Load label_map.json (label -> int ID)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class DNASequenceDataset(Dataset):
    """PyTorch Dataset for DNA sequences with labels."""
    
    def __init__(self, data: List[Dict], tokenizer, label_map: Dict[str, int], max_length: int = 512):
        self.data = data
        self.tokenizer = tokenizer
        self.label_map = label_map
        self.max_length = max_length
    
    def __len__(self):
        return len(self.data)
    
    def __getitem__(self, idx):
        item = self.data[idx]
        sequence = item["sequence"]
        label = item["label"]
        
        # Tokenize the DNA sequence
        encoding = self.tokenizer(
            sequence,
            truncation=True,
            max_length=self.max_length,
            padding=False,  # DataCollator will handle padding
            return_tensors=None
        )
        
        # Add label
        encoding["labels"] = self.label_map[label]
        
        return encoding


def compute_metrics(eval_pred):
    """Compute accuracy and F1 for evaluation."""
    predictions, labels = eval_pred
    preds = np.argmax(predictions, axis=-1)
    
    acc = accuracy_score(labels, preds)
    f1 = f1_score(labels, preds, average="weighted")
    
    return {"accuracy": acc, "f1": f1}


def main():
    parser = argparse.ArgumentParser(description="Fine-tune DNABERT-2 for species classification")
    parser.add_argument("--train", required=True, help="Path to train.jsonl")
    parser.add_argument("--val", required=True, help="Path to val.jsonl")
    parser.add_argument("--label_map", required=True, help="Path to label_map.json")
    parser.add_argument("--model_name", default="bert-base-uncased", help="HuggingFace model name (default: bert-base-uncased, use zhihan1996/DNABERT-2-117M on Linux)")
    parser.add_argument("--output_dir", default="models/trained_dnabert", help="Output directory")
    parser.add_argument("--epochs", type=int, default=10, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=4, help="Batch size per device")
    parser.add_argument("--accumulation_steps", type=int, default=2, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--max_length", type=int, default=512, help="Max sequence length")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--patience", type=int, default=3, help="Early stopping patience")
    args = parser.parse_args()
    
    print("=" * 60)
    print("DNABERT-2 FINE-TUNING FOR SPECIES CLASSIFICATION")
    print("=" * 60)
    
    # Device check
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if device == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    
    # Load label map
    print(f"\n📂 Loading label map: {args.label_map}")
    label_map = load_label_map(args.label_map)
    num_labels = len(label_map)
    id2label = {v: k for k, v in label_map.items()}
    label2id = label_map
    print(f"   Classes: {num_labels} -> {list(label_map.keys())}")
    
    # Load data
    print(f"\n📂 Loading training data: {args.train}")
    train_data = load_jsonl(args.train)
    print(f"   Train samples: {len(train_data)}")
    
    print(f"\n📂 Loading validation data: {args.val}")
    val_data = load_jsonl(args.val)
    print(f"   Val samples: {len(val_data)}")
    
    # Load tokenizer
    print(f"\n🔧 Loading tokenizer: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    
    # Ensure tokenizer has pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or "[PAD]"
    
    # Load config and set pad_token_id
    print(f"\n🔧 Loading config: {args.model_name}")
    config = AutoConfig.from_pretrained(args.model_name, trust_remote_code=True)
    config.pad_token_id = tokenizer.pad_token_id
    config.num_labels = num_labels
    config.id2label = id2label
    config.label2id = label2id
    
    # Load base model (disable flash attention for Windows compatibility)
    print(f"\n🔧 Loading base model: {args.model_name}")
    print("   (Flash Attention disabled for Windows compatibility)")
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        config=config,
        trust_remote_code=True,
        attn_implementation="eager",
        ignore_mismatched_sizes=True
    )
    
    # Apply LoRA
    print(f"\n🔧 Applying LoRA (r={args.lora_r}, alpha={args.lora_alpha})")
    
    # Get target modules dynamically
    target_modules = []
    for name, _ in model.named_modules():
        if any(x in name.lower() for x in ["query", "key", "value", "dense", "q_proj", "k_proj", "v_proj", "o_proj"]):
            target_modules.append(name.split(".")[-1])
    target_modules = list(set(target_modules))
    if not target_modules:
        target_modules = ["query", "key", "value"]
    print(f"   Target modules: {target_modules[:5]}...")
    
    lora_config = LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.1,
        target_modules=target_modules,
        bias="none"
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    
    # Create datasets
    print("\n📊 Creating datasets...")
    train_dataset = DNASequenceDataset(train_data, tokenizer, label_map, max_length=args.max_length)
    val_dataset = DNASequenceDataset(val_data, tokenizer, label_map, max_length=args.max_length)
    
    # Data collator for dynamic padding
    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)
    
    # Output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Training arguments
    print("\n⚙️ Training configuration:")
    print(f"   Epochs: {args.epochs}")
    print(f"   Batch size: {args.batch_size}")
    print(f"   Gradient accumulation: {args.accumulation_steps}")
    print(f"   Effective batch size: {args.batch_size * args.accumulation_steps}")
    print(f"   Learning rate: {args.lr}")
    print(f"   FP16: True")
    
    training_args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.accumulation_steps,
        learning_rate=args.lr,
        weight_decay=0.01,
        fp16=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        save_total_limit=2,
        logging_dir=str(output_dir / "logs"),
        logging_steps=10,
        report_to="none",
        dataloader_num_workers=0,  # Windows compatibility
    )
    
    # Early stopping
    early_stopping = EarlyStoppingCallback(early_stopping_patience=args.patience)
    
    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
        compute_metrics=compute_metrics,
        callbacks=[early_stopping]
    )
    
    # Train
    print("\n" + "=" * 60)
    print("🚀 STARTING TRAINING...")
    print("=" * 60 + "\n")
    
    train_result = trainer.train()
    
    # Final evaluation
    print("\n" + "=" * 60)
    print("📊 FINAL EVALUATION")
    print("=" * 60)
    
    eval_result = trainer.evaluate()
    print(f"   Accuracy: {eval_result['eval_accuracy']:.4f}")
    print(f"   F1 Score: {eval_result['eval_f1']:.4f}")
    
    # Save model
    print("\n" + "=" * 60)
    print("💾 SAVING MODEL...")
    print("=" * 60)
    
    # Merge LoRA weights and save
    merged_model = model.merge_and_unload()
    merged_model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    
    # Save label_map.json in model directory
    label_map_path = output_dir / "label_map.json"
    with open(label_map_path, "w", encoding="utf-8") as f:
        json.dump(label_map, f, indent=2)
    print(f"   Saved: label_map.json")
    
    # Save training config
    training_config = {
        "model_name": args.model_name,
        "num_labels": num_labels,
        "labels": list(label_map.keys()),
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "accumulation_steps": args.accumulation_steps,
        "learning_rate": args.lr,
        "max_length": args.max_length,
        "train_samples": len(train_data),
        "val_samples": len(val_data),
        "final_accuracy": eval_result["eval_accuracy"],
        "final_f1": eval_result["eval_f1"],
        "trained_at": datetime.now().isoformat()
    }
    config_path = output_dir / "training_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(training_config, f, indent=2)
    print(f"   Saved: training_config.json")
    
    # List output files
    print(f"\n📁 Output directory: {output_dir.resolve()}")
    print("   Files:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            if size > 1e6:
                print(f"     {f.name}: {size/1e6:.1f} MB")
            else:
                print(f"     {f.name}: {size/1e3:.1f} KB")
    
    print("\n" + "=" * 60)
    print("✅ TRAINING COMPLETE!")
    print("=" * 60)
    print(f"\nModel saved to: {output_dir.resolve()}")
    print(f"Use with: HF_MODEL_PATH={output_dir}")


if __name__ == "__main__":
    main()

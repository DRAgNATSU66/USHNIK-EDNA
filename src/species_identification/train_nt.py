# src/species_identification/train_nt.py
"""
Windows-Safe Training Script for InstaDeepAI Nucleotide Transformer

Strategy: FREEZE base transformer weights + train small classification head
- Avoids PEFT/LoRA/bitsandbytes Windows issues
- Uses fp32 for stability (fp16 can be unstable on Windows)
- Designed for RTX 3070 (8GB VRAM) with gradient accumulation

Usage:
  python src/species_identification/train_nt.py \
    --train data/processed/train.jsonl \
    --val data/processed/val.jsonl \
    --label_map data/processed/label_map.json \
    --output_dir models/trained_nt \
    --epochs 10 --batch_size 2 --accumulation_steps 4 --lr 1e-3
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from collections import Counter

import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import Dataset, DataLoader
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR

# HuggingFace imports
from transformers import AutoTokenizer, AutoModel, AutoConfig

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
            padding="max_length",
            return_tensors="pt"
        )
        
        # Squeeze to remove batch dimension
        encoding = {k: v.squeeze(0) for k, v in encoding.items()}
        
        # Add label
        encoding["labels"] = torch.tensor(self.label_map[label], dtype=torch.long)
        
        return encoding


class NTClassifier(nn.Module):
    """
    Nucleotide Transformer with frozen base + trainable classification head.
    
    Base transformer weights are frozen. Only the classification head is trained.
    """
    
    def __init__(self, base_model, hidden_size: int, num_labels: int, dropout: float = 0.1):
        super().__init__()
        self.base_model = base_model
        self.dropout = nn.Dropout(dropout)
        self.classifier = nn.Linear(hidden_size, num_labels)
        
        # Freeze all base model parameters
        for param in self.base_model.parameters():
            param.requires_grad = False
        
        # Classifier head is trainable by default
        
    def forward(self, input_ids, attention_mask=None, **kwargs):
        # Forward through frozen base model (no grad)
        with torch.no_grad():
            outputs = self.base_model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                output_hidden_states=True
            )
        
        # Use last hidden state, take [CLS] token or mean pooling
        if hasattr(outputs, 'last_hidden_state'):
            hidden_states = outputs.last_hidden_state
        else:
            hidden_states = outputs[0]
        
        # Mean pooling over sequence length (more robust than [CLS])
        if attention_mask is not None:
            mask = attention_mask.unsqueeze(-1).float()
            pooled = (hidden_states * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        else:
            pooled = hidden_states.mean(dim=1)
        
        # Classification head (trainable)
        pooled = self.dropout(pooled)
        logits = self.classifier(pooled)
        
        return logits


def train_epoch(model, dataloader, optimizer, device, accumulation_steps: int = 1):
    """Train for one epoch with gradient accumulation."""
    model.train()
    # But keep base model in eval mode (frozen)
    model.base_model.eval()
    
    total_loss = 0.0
    all_preds = []
    all_labels = []
    
    criterion = nn.CrossEntropyLoss()
    optimizer.zero_grad()
    
    for step, batch in enumerate(dataloader):
        input_ids = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels = batch["labels"].to(device)
        
        logits = model(input_ids=input_ids, attention_mask=attention_mask)
        loss = criterion(logits, labels)
        loss = loss / accumulation_steps  # Scale for accumulation
        
        loss.backward()
        
        if (step + 1) % accumulation_steps == 0:
            optimizer.step()
            optimizer.zero_grad()
        
        total_loss += loss.item() * accumulation_steps
        
        preds = torch.argmax(logits, dim=-1).cpu().numpy()
        all_preds.extend(preds)
        all_labels.extend(labels.cpu().numpy())
    
    # Handle remaining gradients
    if (step + 1) % accumulation_steps != 0:
        optimizer.step()
        optimizer.zero_grad()
    
    avg_loss = total_loss / len(dataloader)
    accuracy = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="weighted")
    
    return avg_loss, accuracy, f1


def evaluate(model, dataloader, device):
    """Evaluate model on validation set."""
    model.eval()
    
    total_loss = 0.0
    all_preds = []
    all_labels = []
    
    criterion = nn.CrossEntropyLoss()
    
    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)
            
            logits = model(input_ids=input_ids, attention_mask=attention_mask)
            loss = criterion(logits, labels)
            
            total_loss += loss.item()
            
            preds = torch.argmax(logits, dim=-1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(labels.cpu().numpy())
    
    avg_loss = total_loss / len(dataloader)
    accuracy = accuracy_score(all_labels, all_preds)
    f1 = f1_score(all_labels, all_preds, average="weighted")
    
    return avg_loss, accuracy, f1


def main():
    parser = argparse.ArgumentParser(description="Train Nucleotide Transformer for species classification (freeze+head)")
    parser.add_argument("--train", required=True, help="Path to train.jsonl")
    parser.add_argument("--val", required=True, help="Path to val.jsonl")
    parser.add_argument("--label_map", required=True, help="Path to label_map.json")
    parser.add_argument("--model_name", default="InstaDeepAI/nucleotide-transformer-500m-1000g", 
                        help="HuggingFace model name")
    parser.add_argument("--output_dir", default="models/trained_nt", help="Output directory")
    parser.add_argument("--epochs", type=int, default=10, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=2, help="Batch size per device")
    parser.add_argument("--accumulation_steps", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate for classification head")
    parser.add_argument("--max_length", type=int, default=512, help="Max sequence length")
    parser.add_argument("--patience", type=int, default=3, help="Early stopping patience")
    parser.add_argument("--dropout", type=float, default=0.1, help="Dropout rate")
    args = parser.parse_args()
    
    print("=" * 60)
    print("NUCLEOTIDE TRANSFORMER TRAINING (FREEZE + HEAD)")
    print("Windows-Safe: No PEFT/LoRA, fp32, frozen base")
    print("=" * 60)
    
    # Device check
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\nDevice: {device}")
    if device.type == "cuda":
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    
    # Load label map
    print(f"\n[*] Loading label map: {args.label_map}")
    label_map = load_label_map(args.label_map)
    num_labels = len(label_map)
    id2label = {v: k for k, v in label_map.items()}
    print(f"   Classes: {num_labels} -> {list(label_map.keys())}")
    
    # Load data
    print(f"\n[*] Loading training data: {args.train}")
    train_data = load_jsonl(args.train)
    print(f"   Train samples: {len(train_data)}")
    
    print(f"\n[*] Loading validation data: {args.val}")
    val_data = load_jsonl(args.val)
    print(f"   Val samples: {len(val_data)}")
    
    # Load tokenizer
    print(f"\n[*] Loading tokenizer: {args.model_name}")
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, trust_remote_code=True)
    
    # Ensure tokenizer has pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token or "[PAD]"
        if tokenizer.pad_token_id is None:
            tokenizer.add_special_tokens({'pad_token': '[PAD]'})
    
    # Load base model (frozen)
    print(f"\n[*] Loading base model: {args.model_name}")
    print("   Strategy: FREEZE base weights, train classification head only")
    
    config = AutoConfig.from_pretrained(args.model_name, trust_remote_code=True)
    base_model = AutoModel.from_pretrained(
        args.model_name,
        config=config,
        trust_remote_code=True
    )
    
    # Get hidden size
    hidden_size = config.hidden_size if hasattr(config, 'hidden_size') else 1024
    print(f"   Hidden size: {hidden_size}")
    
    # Create classifier model
    model = NTClassifier(base_model, hidden_size, num_labels, dropout=args.dropout)
    model = model.to(device)
    
    # Count trainable params
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"   Total params: {total_params:,}")
    print(f"   Trainable params: {trainable_params:,} ({100*trainable_params/total_params:.2f}%)")
    
    # Create datasets
    print("\n[*] Creating datasets...")
    train_dataset = DNASequenceDataset(train_data, tokenizer, label_map, max_length=args.max_length)
    val_dataset = DNASequenceDataset(val_data, tokenizer, label_map, max_length=args.max_length)
    
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)
    
    # Output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Training configuration
    print("\n[*] Training configuration:")
    print(f"   Epochs: {args.epochs}")
    print(f"   Batch size: {args.batch_size}")
    print(f"   Gradient accumulation: {args.accumulation_steps}")
    print(f"   Effective batch size: {args.batch_size * args.accumulation_steps}")
    print(f"   Learning rate: {args.lr}")
    print(f"   Precision: fp32 (Windows-safe)")
    print(f"   Early stopping patience: {args.patience}")
    
    # Optimizer (only for classifier head)
    optimizer = AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=args.lr, weight_decay=0.01)
    scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs)
    
    # Training loop
    print("\n" + "=" * 60)
    print("STARTING TRAINING...")
    print("=" * 60 + "\n")
    
    best_val_f1 = 0.0
    best_epoch = 0
    patience_counter = 0
    
    for epoch in range(args.epochs):
        print(f"Epoch {epoch + 1}/{args.epochs}")
        
        # Train
        train_loss, train_acc, train_f1 = train_epoch(
            model, train_loader, optimizer, device, args.accumulation_steps
        )
        
        # Validate
        val_loss, val_acc, val_f1 = evaluate(model, val_loader, device)
        
        scheduler.step()
        
        print(f"  Train - Loss: {train_loss:.4f}, Acc: {train_acc:.4f}, F1: {train_f1:.4f}")
        print(f"  Val   - Loss: {val_loss:.4f}, Acc: {val_acc:.4f}, F1: {val_f1:.4f}")
        
        # Check for improvement
        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            best_epoch = epoch + 1
            patience_counter = 0
            
            # Save best model
            print(f"  [+] New best! Saving checkpoint...")
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_f1': val_f1,
                'val_acc': val_acc
            }, output_dir / "best_checkpoint.pt")
        else:
            patience_counter += 1
            if patience_counter >= args.patience:
                print(f"\n[!] Early stopping triggered at epoch {epoch + 1}")
                break
        
        print()
    
    # Load best model
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"   Best epoch: {best_epoch}")
    print(f"   Best val F1: {best_val_f1:.4f}")
    
    # Reload best checkpoint
    checkpoint = torch.load(output_dir / "best_checkpoint.pt")
    model.load_state_dict(checkpoint['model_state_dict'])
    
    # Final evaluation
    val_loss, val_acc, val_f1 = evaluate(model, val_loader, device)
    print(f"   Final Accuracy: {val_acc:.4f}")
    print(f"   Final F1 Score: {val_f1:.4f}")
    
    # Save model in HuggingFace-loadable format
    print("\n" + "=" * 60)
    print("SAVING MODEL (HuggingFace-loadable format)...")
    print("=" * 60)
    
    # Save the classifier weights
    classifier_state = {
        'classifier.weight': model.classifier.weight,
        'classifier.bias': model.classifier.bias,
        'dropout': args.dropout
    }
    torch.save(classifier_state, output_dir / "classifier_head.pt")
    
    # Save full model for easy loading
    torch.save(model.state_dict(), output_dir / "model.pt")
    
    # Save tokenizer
    tokenizer.save_pretrained(str(output_dir))
    print(f"   Saved: tokenizer files")
    
    # Save config with modifications for our setup
    config.num_labels = num_labels
    config.id2label = id2label
    config.label2id = label_map
    config.save_pretrained(str(output_dir))
    print(f"   Saved: config.json")
    
    # Save label_map.json in model directory
    label_map_path = output_dir / "label_map.json"
    with open(label_map_path, "w", encoding="utf-8") as f:
        json.dump(label_map, f, indent=2)
    print(f"   Saved: label_map.json")
    
    # Save training config
    training_config = {
        "model_name": args.model_name,
        "strategy": "freeze_base_train_head",
        "num_labels": num_labels,
        "labels": list(label_map.keys()),
        "hidden_size": hidden_size,
        "dropout": args.dropout,
        "epochs_trained": best_epoch,
        "epochs_requested": args.epochs,
        "batch_size": args.batch_size,
        "accumulation_steps": args.accumulation_steps,
        "effective_batch_size": args.batch_size * args.accumulation_steps,
        "learning_rate": args.lr,
        "max_length": args.max_length,
        "train_samples": len(train_data),
        "val_samples": len(val_data),
        "final_accuracy": val_acc,
        "final_f1": val_f1,
        "precision": "fp32",
        "windows_safe": True,
        "trained_at": datetime.now().isoformat()
    }
    config_path = output_dir / "training_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(training_config, f, indent=2)
    print(f"   Saved: training_config.json")
    
    # List output files
    print(f"\n[*] Output directory: {output_dir.resolve()}")
    print("   Files:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            if size > 1e6:
                print(f"     {f.name}: {size/1e6:.1f} MB")
            else:
                print(f"     {f.name}: {size/1e3:.1f} KB")
    
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE!")
    print("=" * 60)
    print(f"\nModel saved to: {output_dir.resolve()}")
    print(f"Use with: HF_MODEL_PATH={output_dir}")
    print("\nWindows Compatibility Notes:")
    print("  - Base transformer weights: FROZEN (no PEFT/LoRA needed)")
    print("  - Precision: fp32 (stable on Windows)")
    print("  - Flash attention: Not used (Windows-safe)")
    print("  - DataLoader workers: 0 (Windows multiprocessing safe)")


if __name__ == "__main__":
    main()

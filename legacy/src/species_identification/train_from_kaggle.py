# src\species_identification\train_from_kaggle.py
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
import joblib
import sys
import os
from collections import Counter

# Path config
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "reference_db", "reference_small.csv")
MODEL_OUT = os.path.join("models", "species_clf.pkl")
K = 6

def seq_to_kmers(seq, k=K):
    seq = str(seq).upper().strip()
    if len(seq) < k:
        return seq
    return " ".join(seq[i:i+k] for i in range(len(seq)-k+1))

def main():
    if not os.path.exists(CSV_PATH):
        print(f"CSV not found: {CSV_PATH}")
        print(r"Place a reference CSV at data\reference_db\reference_small.csv or run script with your CSV path as an argument")
        return

    df = pd.read_csv(CSV_PATH)
    if 'sequence' not in df.columns or 'species' not in df.columns:
        print("CSV must contain 'sequence' and 'species' columns. Exiting.")
        print("Columns found:", df.columns.tolist())
        return

    df = df.dropna(subset=['sequence', 'species']).reset_index(drop=True)
    if len(df) < 2:
        print("Too few rows in CSV to train a model. Need at least 2 samples.")
        return

    # Prepare features
    texts = df['sequence'].map(seq_to_kmers)
    vec = TfidfVectorizer(max_features=5000)
    X = vec.fit_transform(texts)
    y = df['species']

    # Decide whether stratify is possible
    class_counts = Counter(y)
    min_count = min(class_counts.values())
    stratify_param = y if min_count >= 2 and len(class_counts) > 1 else None
    if stratify_param is None:
        print("Warning: stratified split is not possible (a class has <2 samples) — using non-stratified split.")

    # Train/test split
    try:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=stratify_param, random_state=42)
    except Exception as e:
        print("Warning: train_test_split with stratify failed, falling back to non-stratified split. Error:", e)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Fit classifier
    clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
    clf.fit(X_train, y_train)

    # Evaluate if possible
    try:
        acc = clf.score(X_test, y_test)
        print(f"Test accuracy: {acc:.4f}")
    except Exception:
        print("Could not compute accuracy with current split (probably too small dataset).")

    os.makedirs("models", exist_ok=True)
    joblib.dump({"vec": vec, "clf": clf, "k": K}, MODEL_OUT)
    print(f"Model saved to {MODEL_OUT}")

if __name__ == "__main__":
    main()

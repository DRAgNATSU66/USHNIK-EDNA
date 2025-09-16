# scripts/create_toy_sklearn_model.py
"""
Create a tiny sklearn pipeline classifier and dump it to models/species_clf.pkl
This is purely for local/demo/testing use — not a real biological model.
"""

import os
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB

# Example training data (sequence-like strings -> fake labels)
X = [
    "ATGCGTACGTA", "ATGCGTACGTT", "ATGCGTACGAA",  # class A
    "TTGACGATCG", "TTGACGATCGA", "TTGACGATCGT",   # class B
    "GGGCCCAAAT", "GGGCCCAAAG", "GGGCCCAAAC",     # class C
]
y = [
    "SpeciesA", "SpeciesA", "SpeciesA",
    "SpeciesB", "SpeciesB", "SpeciesB",
    "SpeciesC", "SpeciesC", "SpeciesC",
]

pipeline = make_pipeline(
    CountVectorizer(analyzer="char", ngram_range=(3, 3)),  # k-mer-ish features (3-mer)
    MultinomialNB()
)

pipeline.fit(X, y)

# Ensure models/ exists
os.makedirs("models", exist_ok=True)
out_path = os.path.join("models", "species_clf.pkl")

# Save as a simple model object; we can also dump dict with 'model' key for compatibility
joblib.dump(pipeline, out_path)
print(f"Wrote demo sklearn model to: {out_path}")

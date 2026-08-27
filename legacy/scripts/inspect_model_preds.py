import joblib
import pandas as pd
import os

MODEL_PATH = os.path.join("models", "species_clf.pkl")
CSV_PATH = os.path.join("data", "reference_db", "reference_small.csv")

print("Loading model:", MODEL_PATH)
mdl = joblib.load(MODEL_PATH)
vec, clf = mdl["vec"], mdl["clf"]

df = pd.read_csv(CSV_PATH)
def kmers(s, k=mdl.get("k", 6)):
    s = str(s).upper().strip()
    if len(s) < k:
        return s
    return " ".join(s[i:i+k] for i in range(len(s)-k+1))

texts = df['sequence'].map(kmers)
X = vec.transform(texts)
preds = clf.predict(X)
df['predicted'] = preds
print("\nTraining-data predictions:")
print(df.to_string(index=False))

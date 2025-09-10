from pathlib import Path
import pickle, traceback
p = Path("models/species_clf.pkl")
print("exists:", p.exists())
if not p.exists():
    raise SystemExit("no file")
try:
    data = pickle.load(open(p, "rb"))
    print("type:", type(data))
    if isinstance(data, dict):
        print("dict keys:", list(data.keys()))
    else:
        attrs = [a for a in dir(data) if not a.startswith('_')]
        print("sample attrs:", attrs[:20])
except Exception:
    print("LOAD ERROR (traceback):")
    traceback.print_exc()

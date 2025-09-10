from pathlib import Path
import pickle, traceback
p = Path('models/species_clf.pkl')
print('path:', p)
print('exists:', p.exists())
if not p.exists():
    raise SystemExit('file missing')

b = p.read_bytes()
print('filesize (bytes):', len(b))
print('first 128 bytes repr:')
print(repr(b[:128]))
print('first 32 bytes hex:')
print(b[:32].hex())
def try_pickle(byts):
    try:
        obj = pickle.loads(byts)
        print('PICKLE loads: OK ->', type(obj))
        return True
    except Exception as e:
        print('PICKLE loads: FAILED ->', repr(e))
        return False

def try_joblib(path):
    try:
        import joblib
        obj = joblib.load(path)
        print('JOBLIB load: OK ->', type(obj))
        return True
    except Exception as e:
        print('JOBLIB load: FAILED ->', repr(e))
        return False

def try_gzip_pickle(byts):
    try:
        import gzip, pickle
        obj = pickle.loads(gzip.decompress(byts))
        print('GZIP+PICKLE: OK ->', type(obj))
        return True
    except Exception as e:
        print('GZIP+PICKLE: FAILED ->', repr(e))
        return False

print('\\n--- Try pickle.loads on raw bytes ---')
try_pickle(b)

print('\\n--- Try joblib.load(path) ---')
try_joblib(p)

print('\\n--- Try gzip.decompress + pickle.loads ---')
try_gzip_pickle(b)

print('\\n(End of inspection)')

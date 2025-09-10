import pandas as pd
import os
inpath = os.path.join("data", "reference_db", "reference_small.csv")
outpath = os.path.join("data", "reference_db", "reference_small_aug10.csv")
df = pd.read_csv(inpath)
df2 = pd.concat([df]*10, ignore_index=True)
df2.to_csv(outpath, index=False)
print(f"Saved augmented file: {outpath} with {len(df2)} rows")

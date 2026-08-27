from dotenv import load_dotenv
import os

load_dotenv()

print("MONGO_URI startswith:", os.getenv("MONGO_URI", "")[:30])
print("MONGO_DB_NAME:", os.getenv("MONGO_DB_NAME"))
print("HF_TOKEN present?", bool(os.getenv("HF_TOKEN")))

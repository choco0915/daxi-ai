import os
from app import SERVER_HOST, SERVER_PORT, app

print("FastAPI app:", app.title)
print("HOST:", SERVER_HOST)
print("PORT:", SERVER_PORT)
print("OPENAI_API_KEY:", "configured" if os.getenv("OPENAI_API_KEY") else "not configured")
print("Public binding ready:", SERVER_HOST == "0.0.0.0")

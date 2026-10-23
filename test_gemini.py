import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=30000)
)

try:
    print("Sending request...", flush=True)

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents="Say hello"
    )

    print("\nGemini response:")
    print(response.text)

except Exception as e:
    print("\nError:", type(e).__name__)
    print(str(e))
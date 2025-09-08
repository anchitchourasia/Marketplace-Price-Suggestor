import os
from dotenv import load_dotenv
from groq import Groq
import google.generativeai as genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GEMINI_API_KEY or not GROQ_API_KEY:
    raise ValueError("Please set GEMINI_API_KEY and GROQ_API_KEY in .env file.")

genai.configure(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY)

def suggest_price(title, category, brand, condition, age_months, asking_price):
    prompt = f"""
You are an expert in second-hand marketplace pricing.
Suggest a fair market price range for this product and explain the reasoning in detail.
Return output strictly in JSON format with keys:
- price_range (string)
- reasoning (object with keys: base_price_depreciation, condition_adjustment, age_consideration, brand_factor, market_trends, conclusion)

Example JSON:
{{
  "price_range": "₹60000-₹70000",
  "reasoning": {{
    "base_price_depreciation": "...",
    "condition_adjustment": "...",
    "age_consideration": "...",
    "brand_factor": "...",
    "market_trends": "...",
    "conclusion": "..."
  }}
}}

Product Details:
Title: {title}
Category: {category}
Brand: {brand}
Condition: {condition}
Age (months): {age_months}
Asking Price: ₹{asking_price}
"""

    try:
        # First try Gemini
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception:
        # Fallback to Groq
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a pricing assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        return completion.choices[0].message.content

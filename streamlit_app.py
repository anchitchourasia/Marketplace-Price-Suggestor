# streamlit_app.py
import os
import re
import json
import requests
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

# ---------------------------
# Load env & keys
# ---------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GEMINI_API_KEY or not GROQ_API_KEY:
    st.error("Please set GEMINI_API_KEY and GROQ_API_KEY in your .env file.")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)

# ---------------------------
# Helpers
# ---------------------------
def extract_json_from_text(text: str):
    """
    Extract JSON substring from AI output robustly.
    Handles cases where the model returns triple-backtick blocks or surrounding text.
    Returns (json_obj, json_text) or (None, None) on failure.
    """
    if not text:
        return None, None

    # Remove leading/trailing whitespace
    t = text.strip()

    # If code fence present, strip code fences first
    # remove ```json or ``` markers
    t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)

    # Now find first '{' and last '}' and attempt to parse that substring
    first = t.find('{')
    last = t.rfind('}')
    if first != -1 and last != -1 and last > first:
        candidate = t[first:last+1]
        try:
            obj = json.loads(candidate)
            return obj, candidate
        except Exception:
            # sometimes AI returns trailing commas or small invalid JSON; try cleaning common issues
            cleaned = candidate
            # remove trailing commas before closing braces/brackets
            cleaned = re.sub(r",\s*}", "}", cleaned)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                obj = json.loads(cleaned)
                return obj, cleaned
            except Exception:
                return None, candidate

    # fallback: try to find a {...} via regex (first balanced-ish match)
    match = re.search(r"\{[\s\S]*\}", t)
    if match:
        candidate = match.group(0)
        try:
            obj = json.loads(candidate)
            return obj, candidate
        except Exception:
            cleaned = re.sub(r",\s*}", "}", candidate)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                obj = json.loads(cleaned)
                return obj, cleaned
            except Exception:
                return None, candidate

    return None, None


def parse_price_range(price_range_str: str):
    """
    Parse price range string like "₹60000-₹70000" into (min_int, max_int)
    Returns (None, None) on failure.
    """
    if not price_range_str:
        return None, None
    s = price_range_str.replace("₹", "").replace(",", "").strip()
    # common separators
    for sep in ["-", "–", "to", "TO", "To"]:
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) >= 2:
                try:
                    min_v = int(re.sub(r"[^\d]", "", parts[0]))
                    max_v = int(re.sub(r"[^\d]", "", parts[1]))
                    return min_v, max_v
                except:
                    continue
    # fallback find all numbers
    nums = re.findall(r"\d+", s)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        v = int(nums[0])
        return v, v
    return None, None

# ---------------------------
# UI & Layout
# ---------------------------
st.set_page_config(page_title="💰 Marketplace Price Suggestor", layout="wide", page_icon="💰")

# Simple dark styling (keeps contrast for result card)
st.markdown(
    """
    <style>
    body { background-color: #0f1316; color: #e6eef6; }
    .stButton>button { background-color: #0072ff; color: white; border-radius:8px; padding:8px 12px; }
    .input-box { background: #111418; padding: 18px; border-radius: 12px; }
    .result-card { background: linear-gradient(180deg,#0b1720,#0b1b1f); padding: 18px; border-radius:12px; box-shadow: 0 8px 30px rgba(0,0,0,0.6); }
    .price-highlight { font-size: 22px; color: #7fffd4; font-weight:700; }
    .reason-box { background: #0d1619; padding: 12px; border-radius:8px; color: #dbeefb; }
    </style>
    """, unsafe_allow_html=True
)

# Sidebar
with st.sidebar:
    st.title("💰 Price Suggestor")
    st.write("AI-powered price suggestions (Gemini 2.0 Flash + Groq fallback)")
    st.markdown("---")
    st.write("Examples:")
    st.write("• iPhone 13 Pro Max — Like New — 10 months — ₹90,000")
    st.write("• MacBook Air M1 — Good — 18 months — ₹75,000")
    st.markdown("---")
    st.caption("Make sure your .env contains GEMINI_API_KEY and GROQ_API_KEY")

# Main
st.header("Get a fair market price for your second-hand product")

col1, col2 = st.columns([2, 1])
with col1:
    st.markdown('<div class="input-box">', unsafe_allow_html=True)
    product_title = st.text_input("📦 Product Title", placeholder="e.g. iPhone 13 Pro Max")
    # simplified brand detection from title (quick auto-fill)
    auto_brand = ""
    if product_title:
        t = product_title.lower()
        if "iphone" in t or "macbook" in t:
            auto_brand = "Apple"
        elif "samsung" in t:
            auto_brand = "Samsung"
        elif "oneplus" in t:
            auto_brand = "OnePlus"
        elif "xiaomi" in t or "redmi" in t:
            auto_brand = "Xiaomi"
    category = st.selectbox("📂 Category", ["Mobile", "Laptop", "Tablet", "TV", "Electronics", "Furniture", "Other"])
    brand = st.text_input("🏷 Brand", value=auto_brand)
    condition = st.selectbox("✅ Condition", ["Like New", "Good", "Average", "Below Average"])
    age_months = st.slider("📅 Age (months)", 0, 120, 12)
    asking_price = st.number_input("💵 Asking Price (INR)", min_value=0, step=100, value=asking_price if 'asking_price' in locals() else 1000)
    st.markdown("</div>", unsafe_allow_html=True)
    submit = st.button("🔍 Suggest Price")

with col2:
    st.markdown("<div class='result-card'>", unsafe_allow_html=True)
    st.write("### Result")
    placeholder_price = st.empty()
    placeholder_reason = st.empty()
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------
# Action: call AI
# ---------------------------
if submit:
    if not product_title or not brand:
        st.error("Please enter Product Title and Brand.")
    else:
        st.info("⏳ Contacting AI and calculating suggestion...")

        prompt = f"""
You are an expert second-hand marketplace pricing assistant.
Given the product details, suggest a fair price range in INR and give structured reasoning.
Return ONLY a JSON object (no extra commentary). Example format:

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

Product:
Title: {product_title}
Category: {category}
Brand: {brand}
Condition: {condition}
Age (months): {age_months}
Asking Price: ₹{asking_price}
"""

        ai_raw = ""
        # Try Gemini 2.0 Flash first
        try:
            model = genai.GenerativeModel("models/gemini-2.0-flash")
            # generate_content accepts a list of prompts for this wrapper — use list to be safe
            response = model.generate_content([prompt])
            ai_raw = response.text if hasattr(response, "text") else str(response)
        except Exception as e_g:
            # fallback to Groq if Gemini fails
            st.warning("Primary model (Gemini) failed — using Groq fallback.")
            try:
                groq_url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
                data = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "system", "content": "You are a pricing assistant."},
                                 {"role": "user", "content": prompt}],
                    "temperature": 0.3
                }
                r = requests.post(groq_url, headers=headers, json=data, timeout=30)
                r.raise_for_status()
                ai_raw = r.json()["choices"][0]["message"]["content"]
            except Exception as e_groq:
                st.error("Both Gemini and Groq failed. See console for details.")
                st.exception(e_groq)
                ai_raw = ""

        if not ai_raw:
            st.error("No response received from AI.")
        else:
            # Extract JSON robustly
            parsed_json, json_text = extract_json_from_text(ai_raw)
            if parsed_json is None:
                # show raw output and attempt small fallback parse
                st.warning("Couldn't reliably extract JSON from model output. Showing raw output below.")
                st.code(ai_raw, language="json")
                placeholder_price.markdown("**Suggested Price Range:** Not available")
                placeholder_reason.markdown("No structured reasoning available.")
            else:
                # show price and reasoning nicely
                price_range = parsed_json.get("price_range", "Not available")
                placeholder_price.markdown(f"<p class='price-highlight'>💰 Suggested Price Range: {price_range}</p>", unsafe_allow_html=True)

                reasoning = parsed_json.get("reasoning", {})
                # show collapsible reasoning
                with st.expander("🔍 Detailed reasoning"):
                    if isinstance(reasoning, dict) and reasoning:
                        for k, v in reasoning.items():
                            st.markdown(f"**{k.replace('_',' ').title()}:** {v}")
                    else:
                        # if reasoning is string or other format, print raw
                        st.write(reasoning)

                # attempt numeric parsing for comparison
                try:
                    min_v, max_v = parse_price_range(price_range)
                    if min_v and max_v:
                        if asking_price < min_v:
                            comp_msg = "🟢 Your asking price is below suggested range — great deal for buyers."
                        elif min_v <= asking_price <= max_v:
                            comp_msg = "✅ Your asking price is within the suggested range."
                        else:
                            comp_msg = "🔴 Your asking price is above suggested range — consider lowering for a faster sale."
                        st.info(comp_msg)
                except Exception:
                    pass

        # done

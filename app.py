import json
import os
import streamlit as st
import google.generativeai as genai

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LEED Credit Selector",
    page_icon="🌿",
    layout="wide"
)

# ── Gemini config ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    st.error("⚠️ Set your GEMINI_API_KEY environment variable before running.")
    st.code("export GEMINI_API_KEY=your_key_here")
    st.stop()

genai.configure(api_key=GEMINI_API_KEY)
model = "gemini-2.0-flash"
#model = genai.GenerativeModel("gemini-1.5-flash-latest")
#model = genai.GenerativeModel("gemini-1.5-flash")  # free tier, 1500 req/day

# ── Load credit database ──────────────────────────────────────────────────────
@st.cache_data
def load_credits():
    with open("leed_credits.json", "r") as f:
        return json.load(f)["credits"]

ALL_CREDITS = load_credits()

# ── Gemini helper ─────────────────────────────────────────────────────────────
def gemini_chat(prompt: str, history: list = []) -> str:
    try:
        chat     = model.start_chat(history=history)
        response = chat.send_message(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Gemini error: {str(e)}"

# ── Scoring logic (pure Python — no AI) ──────────────────────────────────────
def filter_credits(project: dict) -> list:
    filtered = []
    for c in ALL_CREDITS:
        if project["rating_system"] not in c["applicable_rating_systems"]:
            continue
        if c["applicable_building_types"] != ["all"]:
            if project["building_type"] not in c["applicable_building_types"]:
                continue
        if c["climate_zone_relevance"] != ["all"]:
            if project["climate_zone"] not in c["climate_zone_relevance"]:
                continue
        filtered.append(c)
    return filtered

def score_credit(credit: dict, project: dict) -> float:
    score = 0

    score += (credit["points_available"] / 20) * 10

    budget_map = {
        "tight":    {"low": 3,  "medium": 0,  "high": -5},
        "medium":   {"low": 3,  "medium": 2,  "high":  0},
        "flexible": {"low": 3,  "medium": 3,  "high":  2},
    }
    score += budget_map[project["budget"]][credit["cost_tier"]]
    score += {"low": 3, "medium": 2, "high": 1}[credit["effort_tier"]] * 0.5
    score += {"low": 3, "medium": 2, "high": 1}[credit["documentation_complexity"]] * 0.5

    matching = [t for t in credit["owner_priority_tags"] if t in project["owner_priorities"]]
    score += len(matching) * 2
    score += len(credit["synergizes_with"]) * 0.3

    if credit["is_prerequisite"]:
        score = 999

    return round(score, 2)

def select_credits(project: dict):
    filtered = filter_credits(project)
    scored   = [(c, score_credit(c, project)) for c in filtered]
    scored.sort(key=lambda x: x[1], reverse=True)
    prereqs  = [(c, s) for c, s in scored if c["is_prerequisite"]]
    credits  = [(c, s) for c, s in scored if not c["is_prerequisite"]]
    return prereqs, credits

# ── AI explanation ────────────────────────────────────────────────────────────
def get_ai_explanation(project: dict, recommended: list) -> str:
    summary = "\n".join([
        f"- {c['credit_id']}: {c['name']} ({c['points_available']} pts, "
        f"cost={c['cost_tier']}, effort={c['effort_tier']})"
        for c, _ in recommended[:10]
    ])
    prompt = f"""You are a LEED consultant helping an early-stage building designer.

Project:
- Building type: {project['building_type']}
- Climate zone: {project['climate_zone']}
- Target certification: {project['target_certification']}
- Budget: {project['budget']}
- Owner priorities: {', '.join(project['owner_priorities'])}
- Rating system: {project['rating_system']}

Recommended credits:
{summary}

In 150-200 words explain:
1. Why these credits suit this project
2. Which 3 to focus on first and why
3. One key risk to watch out for

Write as a knowledgeable advisor in plain paragraphs. No bullet points."""

    return gemini_chat(prompt)

# ── Session state ─────────────────────────────────────────────────────────────
if "project"      not in st.session_state: st.session_state.project      = None
if "results"      not in st.session_state: st.session_state.results      = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "gemini_hist"  not in st.session_state: st.session_state.gemini_hist  = []

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🌿 LEED Credit Selection Helper")
st.caption("Early-stage green building design assistant • Powered by Gemini 1.5 Flash (free)")

col1, col2 = st.columns([1, 1.6], gap="large")

# ── LEFT: Intake Form ─────────────────────────────────────────────────────────
with col1:
    st.subheader("📋 Project Details")

    building_type = st.selectbox("Building Type",
        ["office", "school", "healthcare", "retail", "residential", "warehouse"])

    rating_system = st.selectbox("LEED Rating System", ["BD+C", "ID+C", "O+M"])

    climate_zone = st.selectbox("Climate Zone (ASHRAE)",
        ["1A","2A","2B","3A","3B","3C","4A","4B","4C","5A","5B","6A","6B","7","8"],
        help="Find your zone at energycodes.gov")

    target_cert = st.selectbox("Target Certification Level",
        ["Certified (40-49 pts)", "Silver (50-59 pts)", "Gold (60-79 pts)", "Platinum (80+ pts)"])

    budget = st.select_slider("Budget Flexibility", options=["tight", "medium", "flexible"])

    priorities = st.multiselect("Owner's Top Priorities",
        ["energy", "water", "wellness", "materials", "site", "indoor_air"],
        default=["energy", "wellness"],
        help="Select all that apply")

    if st.button("🔍 Find Best Credits", use_container_width=True, type="primary"):
        if not priorities:
            st.warning("Please select at least one owner priority.")
        else:
            project = {
                "building_type":        building_type,
                "rating_system":        rating_system,
                "climate_zone":         climate_zone,
                "target_certification": target_cert,
                "budget":               budget,
                "owner_priorities":     priorities,
            }
            with st.spinner("Analysing credits and generating recommendation..."):
                prereqs, credits = select_credits(project)
                explanation      = get_ai_explanation(project, credits)

            st.session_state.project      = project
            st.session_state.results      = {"prereqs": prereqs, "credits": credits, "explanation": explanation}
            st.session_state.chat_history = []
            st.session_state.gemini_hist  = []

# ── RIGHT: Results ────────────────────────────────────────────────────────────
with col2:
    if st.session_state.results:
        results = st.session_state.results
        project = st.session_state.project
        top10   = results["credits"][:10]
        color   = {"low": "🟢", "medium": "🟡", "high": "🔴"}

        st.subheader("💡 Advisor Recommendation")
        st.info(results["explanation"])

        st.subheader("✅ Prerequisites (Mandatory)")
        for c, _ in results["prereqs"]:
            with st.expander(f"{c['credit_id']} — {c['name']}"):
                st.write(c["description"])
                for req in c["key_requirements"]:
                    st.markdown(f"- {req}")

        total_pts = sum(c["points_available"] for c, _ in top10)
        st.subheader(f"⭐ Recommended Credits — up to {total_pts} points")

        for c, score in top10:
            with st.expander(
                f"{c['credit_id']} — {c['name']}  |  **{c['points_available']} pts**  |  "
                f"Cost {color[c['cost_tier']]}  Effort {color[c['effort_tier']]}"
            ):
                st.write(c["description"])
                st.markdown("**Key Requirements:**")
                for req in c["key_requirements"]:
                    st.markdown(f"- {req}")
                if c["synergizes_with"]:
                    st.markdown(f"**Synergizes with:** `{'`, `'.join(c['synergizes_with'])}`")
                if c["requires_credits"]:
                    st.markdown(f"**Requires:** `{'`, `'.join(c['requires_credits'])}`")

        st.divider()
        st.subheader("💬 Ask a Follow-up Question")

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        user_q = st.chat_input("e.g. How do I achieve EA-c2 on a tight budget?")

        if user_q:
            st.session_state.chat_history.append({"role": "user", "content": user_q})

            credit_context = json.dumps([c for c, _ in top10], indent=2)
            full_prompt = f"""You are a LEED expert helping an early-stage building designer.

Project:
{json.dumps(project, indent=2)}

Top recommended credits:
{credit_context}

Answer the designer's question in under 150 words. Be direct and practical.

Question: {user_q}"""

            with st.spinner("Thinking..."):
                answer = gemini_chat(full_prompt, history=st.session_state.gemini_hist)

            st.session_state.gemini_hist.append({"role": "user",  "parts": [full_prompt]})
            st.session_state.gemini_hist.append({"role": "model", "parts": [answer]})
            st.session_state.chat_history.append({"role": "assistant", "content": answer})
            st.rerun()

    else:
        st.markdown("""
        ### How this works
        1. Fill in your project details on the left
        2. Click **Find Best Credits** for a personalised recommendation
        3. Ask follow-up questions about any credit in the chat

        ---
        *Gemini 1.5 Flash — free tier, 1,500 requests/day*
        """)

# ============================================================
# 🚀 Mirroring Chatbot (Cloud Safe + 유사도 유지 완전 버전)
# ============================================================
import streamlit as st
import json
from datetime import datetime
import time
import uuid
import os
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import openai

# ============================================================
# ✅ 1️⃣ 기본 설정
# ============================================================
st.set_page_config(page_title="Mirroring Chatbot", layout="centered")

# ✅ Google Sheets 인증
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    gcp_info = st.secrets["GCP_SERVICE_ACCOUNT"]
    creds = Credentials.from_service_account_info(gcp_info, scopes=scope)
    gc = gspread.authorize(creds)

    openai.api_key = st.secrets["OPENAI_API_KEY"]
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
except Exception as e:
    st.error(f"❌ 인증 오류: {e}")

# ✅ 구글 시트 연결
try:
    spreadsheet = gc.open_by_key("1TSfKYISlyU7tweTqIIuwXbgY43xt1POckUa4DSbeHJo")
except Exception as e:
    st.error(f"❌ 시트 연결 실패: {e}")

# ============================================================
# ✅ 2️⃣ 시트 초기화 및 헤더 생성
# ============================================================
def insert_headers_if_empty(worksheet, headers):
    try:
        if not worksheet.get_all_values():
            worksheet.append_row(headers)
    except Exception as e:
        st.error(f"헤더 추가 중 오류 발생: {e}")

if "spreadsheet" not in st.session_state:
    st.session_state.spreadsheet = spreadsheet
    st.session_state.survey_ws = spreadsheet.worksheet("survey")
    st.session_state.conversation_ws = spreadsheet.worksheet("conversation")

survey_ws = st.session_state.survey_ws
conversation_ws = st.session_state.conversation_ws

insert_headers_if_empty(survey_ws, [
    "timestamp", "user_id", "mode", "gender", "age", "education", "job",
    "similarity", "trust", "enjoyment", "humanness", "reuse_intent", "usefulness",
    "style_prompt", "tone", "formality", "emotion_intensity", "politeness",
    "emoji_use", "sentence_structure"
])

insert_headers_if_empty(conversation_ws, [
    "timestamp", "user_id", "role", "message", "turn_similarity"
])

# ============================================================
# ✅ 3️⃣ 세션 변수 초기화
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_history" not in st.session_state:
    st.session_state.user_history = []
if st.session_state.get("phase") == "mode_selection":
    st.session_state.user_history = []
    st.session_state.style_prompt = ""
if "style_prompt" not in st.session_state:
    st.session_state.style_prompt = ""
if "phase" not in st.session_state:
    st.session_state.phase = "mode_selection"
if "consent_given" not in st.session_state:
    st.session_state.consent_given = False
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]

# ============================================================
# ✅ 4️⃣ 유사도 계산 (Cloud-safe Lazy import)
# ============================================================
@st.cache_resource
def load_embed_model():
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    model = SentenceTransformer("all-MiniLM-L6-v2")
    return model, cosine_similarity

embed_model, cosine_similarity = load_embed_model()

def calc_style_similarity(user_text, bot_text):
    try:
        user_vec = embed_model.encode([user_text])
        bot_vec = embed_model.encode([bot_text])
        sim = cosine_similarity(user_vec, bot_vec)[0][0]
        return round(float(sim), 3)
    except Exception as e:
        st.error(f"❌ 유사도 계산 오류: {e}")
        return None

# ============================================================
# ✅ 5️⃣ 말투 분석 함수 (JSON 형태 + 7개 항목 수치화)
# ============================================================
def update_style_prompt():
    history = "\n".join(st.session_state.user_history[-3:])
    prompt = f"""
    Analyze the user's writing style from the following messages:
    {history}

    Evaluate and summarize the style across the following 7 dimensions (in Korean):
    1. Tone (감정적 분위기)
    2. Formality (격식 수준)
    3. Personality (성향)
    4. Emotion intensity (감정 표현 강도)
    5. Politeness (공손함 수준)
    6. Use of emojis or informal markers (이모티콘, ㅋㅋ, ~ 등)
    7. Sentence length and structure (문장 길이와 형태)

    Provide a concise summary and a JSON output with scores from 1~5 for each dimension.
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        style_json = json.loads(response.choices[0].message.content)
        st.session_state.style_prompt = json.dumps(style_json, ensure_ascii=False)
        st.session_state.style_scores = style_json
    except:
        st.session_state.style_prompt = response.choices[0].message.content
        st.session_state.style_scores = {}

# ============================================================
# ✅ 6️⃣ 단계별 챗봇 흐름
# ============================================================

# 1️⃣ 모드 선택
if st.session_state.phase == "mode_selection":
    st.subheader("시작하기 전에 한 가지를 선택해 주세요:")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("옵션 A (고정형)"):
            st.session_state.chatbot_mode = "fixed"
            st.session_state.mirror_level = "low"
            st.session_state.phase = "style_collection"
            st.rerun()
    with col2:
        if st.button("옵션 B (미러링형)"):
            st.session_state.chatbot_mode = "mirroring"
            st.session_state.mirror_level = st.selectbox(
                "Mirroring 강도 선택", ["low", "moderate", "high"]
            )
            st.session_state.phase = "style_collection"
            st.rerun()

# 2️⃣ 말투 수집
elif st.session_state.get("phase") == "style_collection":
    if "collection_index" not in st.session_state:
        st.session_state.collection_index = 0
    if st.session_state.collection_index == 0:
        st.session_state.messages = []
        initial_prompt = "안녕하세요! 오늘 하루 어땠는지 궁금해요. 날씨나 기분 같은 걸 말해줘요 :)"
        st.session_state.messages.append({"role": "assistant", "content": initial_prompt})

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("챗봇과 대화해보세요")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        st.session_state.user_history.append(user_input)
        with st.chat_message("user"):
            st.markdown(user_input)

        if st.session_state.collection_index < 2:
            system_prompt = "You are a friendly chatbot collecting natural language samples from the user. Ask a casual, personal question each time."
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": system_prompt}, *st.session_state.messages]
            )
            bot_reply = response.choices[0].message.content
            st.session_state.messages.append({"role": "assistant", "content": bot_reply})
            with st.chat_message("assistant"):
                st.markdown(bot_reply)
            st.session_state.collection_index += 1
        else:
            update_style_prompt()
            st.session_state.phase = "pre_task_notice"
            st.rerun()

# 3️⃣ 과업 안내
elif st.session_state.get("phase") == "pre_task_notice":
    st.markdown(f"📝 **당신의 말투 분석 결과:** {st.session_state.style_prompt}")
    if st.session_state.chatbot_mode == "fixed":
        notice_text = "안녕하세요. 챗봇과 함께 3분 동안 여행 계획을 세워보세요. 궁금한 점이 있으면 언제든지 물어보세요."
    else:
        prompt = f"다음 말투에 맞춰 사용자에게 3분간 여행 계획을 시작하도록 제안하는 문장을 만들어줘.\n말투 요약: {st.session_state.style_prompt}"
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        notice_text = response.choices[0].message.content.strip()

    st.session_state.notice_text = notice_text
    st.session_state.phase = "task_conversation"
    st.session_state.start_time = time.time()
    st.rerun()

# 4️⃣ 본 대화
elif st.session_state.get("phase") == "task_conversation":
    if "notice_inserted" not in st.session_state:
        st.session_state.messages.append({"role": "assistant", "content": st.session_state.notice_text})
        st.session_state.notice_inserted = True

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("여행 계획에 대해 대화해보세요")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Mirroring 강도 조절
        if st.session_state.chatbot_mode == "fixed":
            system_instruction = "You are a polite Korean chatbot. Use formal language."
        else:
            system_instruction = f"""
            You are a Korean chatbot that mirrors the user's style.
            Here is the style guide:
            {st.session_state.style_prompt}

            Mirror level: {st.session_state.mirror_level}
            - low: 유지하되 표현 일부만 반영
            - moderate: 문장 길이, 감정, 이모티콘 일부 반영
            - high: 말투, 리듬, 감정 강도, 이모티콘 모두 반영
            """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_instruction}, *st.session_state.messages[-6:]]
        )
        bot_reply = response.choices[0].message.content
        st.session_state.messages.append({"role": "assistant", "content": bot_reply})
        with st.chat_message("assistant"):
            st.markdown(bot_reply)

        # ✅ 유사도 계산 및 표시
        sim = calc_style_similarity(user_input, bot_reply)
        if sim is not None:
            st.write(f"🔹 말투 유사도 점수: {sim}")
        conversation_ws.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            st.session_state.user_id,
            "turn",
            f"{user_input} ↔ {bot_reply}",
            sim
        ], value_input_option="USER_ENTERED")

    if st.session_state.start_time and time.time() - st.session_state.start_time > 180:
        st.markdown("⏰ 시간이 다 되어 챗봇 대화를 종료합니다. 설문지로 이동합니다.")
        time.sleep(5)
        st.session_state.phase = "consent"
        st.rerun()

# 5️⃣ 설문 저장
elif st.session_state.get("phase") == "consent":
    st.subheader("🔒 설문 응답")
    st.write("아래 항목에 응답해 주세요. 응답은 자동 저장됩니다.")
    demo_gender = st.radio("성별:", ["선택 안 함", "남성", "여성", "기타"])
    demo_age = st.selectbox("연령대:", ["선택 안 함", "10대", "20대", "30대", "40대", "50대 이상"])
    demo_edu = st.selectbox("최종 학력:", ["선택 안 함", "고등학교 이하", "대학교", "대학원"])
    demo_job = st.text_input("직업:")

    scale = ["선택 안 함", "전혀 아니다", "아니다", "보통이다", "그렇다", "매우 그렇다"]
    q1 = st.radio("말투가 비슷하다고 느꼈나요?", scale)
    q2 = st.radio("챗봇이 믿을 만했나요?", scale)
    q3 = st.radio("대화가 즐거웠나요?", scale)
    q4 = st.radio("사람처럼 느껴졌나요?", scale)
    q5 = st.radio("다시 사용하고 싶나요?", scale)
    q6 = st.radio("여행 계획에 도움이 되었나요?", scale)

    if st.button("제출 및 저장"):
        if "선택 안 함" in [demo_gender, demo_age, demo_edu, q1, q2, q3, q4, q5, q6] or demo_job.strip() == "":
            st.warning("⚠️ 모든 항목을 입력해 주세요.")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mode_label = "A" if st.session_state.chatbot_mode == "fixed" else "B"

            tone = st.session_state.style_scores.get("Tone", "")
            formality = st.session_state.style_scores.get("Formality", "")
            emotion_intensity = st.session_state.style_scores.get("Emotion intensity", "")
            politeness = st.session_state.style_scores.get("Politeness", "")
            emoji_use = st.session_state.style_scores.get("Use of emojis or informal markers", "")
            sentence_structure = st.session_state.style_scores.get("Sentence length and structure", "")

            survey_row = [
                timestamp, st.session_state.user_id, mode_label,
                demo_gender, demo_age, demo_edu, demo_job,
                q1, q2, q3, q4, q5, q6,
                st.session_state.style_prompt,
                tone, formality, emotion_intensity, politeness, emoji_use, sentence_structure
            ]
            survey_ws.append_row(survey_row, value_input_option="USER_ENTERED")
            st.success("✅ 설문과 분석 결과가 Google Sheets에 저장되었습니다!")

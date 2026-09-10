import os
import asyncio
import base64
import sqlite3
import uuid
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic
from elevenlabs import ElevenLabs
from dotenv import load_dotenv
from prompt_versions import build_prompt
import json

# Load API keys from .env
load_dotenv()


def resolve_api_key(env_name: str, value: Optional[str]) -> Optional[str]:
    """Ignore placeholder / unset values so demo mode stays safe."""
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    placeholders = {
        "ANTHROPIC_API_KEY": {"your_anthropic_api_key_here", "your_api_key_here", "test-api-key"},
        "ELEVENLABS_API_KEY": {"your_elevenlabs_api_key_here", "your_api_key_here", "test-tts-key"},
    }

    if cleaned.lower().startswith("sk-test"):
        return None

    if cleaned.lower() in {item.lower() for item in placeholders.get(env_name, set())}:
        return None

    return cleaned



def should_use_demo_mode() -> bool:
    """Docker defaults to demo mode; local runs use live mode when valid keys exist."""
    override = os.getenv("USE_DEMO_MODE")
    if override is not None:
        return override.lower() == "true"

    if os.path.exists("/.dockerenv"):
        return True

    anthropic_key = resolve_api_key("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
    elevenlabs_key = resolve_api_key("ELEVENLABS_API_KEY", os.getenv("ELEVENLABS_API_KEY"))
    if anthropic_key and elevenlabs_key:
        return False

    return True


# Initialize FastAPI app
app = FastAPI(title="AI Interview Coach")

USE_DEMO_MODE = should_use_demo_mode()
DB_PATH = os.getenv("INTERVIEW_DB_PATH", os.path.join(os.path.dirname(__file__), "interviews.db"))
print(f"AI Interview Coach starting in {'demo' if USE_DEMO_MODE else 'live'} mode")

# Allow frontend to make requests from localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production: specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            topic TEXT NOT NULL,
            persona_type TEXT NOT NULL,
            candidate_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            final_report TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_answers (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            question_number INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            evaluation TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES interview_sessions(id)
        )
        """
    )
    conn.commit()
    conn.close()


def create_interview_session(
    role: str,
    difficulty: str,
    topic: str,
    persona_type: str,
    candidate_name: str,
) -> str:
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO interview_sessions (
            id, role, difficulty, topic, persona_type, candidate_name, status,
            created_at, updated_at, final_report
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, role, difficulty, topic, persona_type, candidate_name, "in_progress", now, now, None),
    )
    conn.commit()
    conn.close()
    return session_id


def save_answer_record(
    session_id: str,
    question_number: int,
    question: str,
    answer: str,
    evaluation: Optional[Dict] = None,
) -> None:
    answer_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO interview_answers (
            id, session_id, question_number, question, answer, evaluation, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            answer_id,
            session_id,
            question_number,
            question,
            answer,
            json.dumps(evaluation) if evaluation is not None else None,
            now,
        ),
    )
    conn.execute(
        "UPDATE interview_sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def update_session_status(session_id: str, status: str, final_report: Optional[Dict] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE interview_sessions
        SET status = ?, updated_at = ?, final_report = ?
        WHERE id = ?
        """,
        (status, now, json.dumps(final_report) if final_report is not None else None, session_id),
    )
    conn.commit()
    conn.close()


def get_interview_session(session_id: str) -> Optional[Dict]:
    conn = get_db_connection()
    session_row = conn.execute(
        "SELECT * FROM interview_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if session_row is None:
        conn.close()
        return None

    answer_rows = conn.execute(
        "SELECT * FROM interview_answers WHERE session_id = ? ORDER BY question_number ASC",
        (session_id,),
    ).fetchall()

    session = {
        "id": session_row["id"],
        "role": session_row["role"],
        "difficulty": session_row["difficulty"],
        "topic": session_row["topic"],
        "persona_type": session_row["persona_type"],
        "candidate_name": session_row["candidate_name"],
        "status": session_row["status"],
        "created_at": session_row["created_at"],
        "updated_at": session_row["updated_at"],
        "final_report": json.loads(session_row["final_report"]) if session_row["final_report"] else None,
        "answers": [],
    }

    for row in answer_rows:
        session["answers"].append({
            "id": row["id"],
            "question_number": row["question_number"],
            "question": row["question"],
            "answer": row["answer"],
            "evaluation": json.loads(row["evaluation"]) if row["evaluation"] else None,
            "created_at": row["created_at"],
        })

    conn.close()
    return session


init_db()

# Initialize API clients. Public or demo deployments should never require live
# Anthropic or ElevenLabs credentials. The app will fall back to canned demo data
# when USE_DEMO_MODE is enabled or when keys are missing.
anthropic_api_key = resolve_api_key("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
elevenlabs_api_key = resolve_api_key("ELEVENLABS_API_KEY", os.getenv("ELEVENLABS_API_KEY"))
anthropic_client = Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
elevenlabs_client = ElevenLabs(api_key=elevenlabs_api_key) if elevenlabs_api_key else None

# Voice configuration
VOICE_IDS = {
    "male": os.getenv("MALE_VOICE_ID", "onwK4e9ZLuTAKqWW03F9"),
    "female": os.getenv("FEMALE_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
}

# Interviewer personality templates
INTERVIEWER_PERSONAS = {
    "friendly_mentor": {
        "name": "Alex Morgan",
        "gender": "male",
        "style": "encouraging, patient, wants to help candidate succeed",
        "voice_settings": {"stability": 0.7, "similarity_boost": 0.75}
    },
    "tough_tech_lead": {
        "name": "Dr. James Chen",
        "gender": "male",
        "style": "rigorous, detail-oriented, tests deep technical knowledge",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    },
    "practical_pm": {
        "name": "Sarah Williams",
        "gender": "female",
        "style": "pragmatic, focuses on system design and trade-offs",
        "voice_settings": {"stability": 0.6, "similarity_boost": 0.75}
    },
    "supportive_coach": {
        "name": "Jordan Lee",
        "gender": "female",
        "style": "warm, motivating, and focused on helping candidates build confidence",
        "voice_settings": {"stability": 0.75, "similarity_boost": 0.75}
    },
    "behavioral_specialist": {
        "name": "Maya Patel",
        "gender": "female",
        "style": "thoughtful, empathetic, and focused on communication and collaboration",
        "voice_settings": {"stability": 0.7, "similarity_boost": 0.75}
    },
    "systems_architect": {
        "name": "David Kim",
        "gender": "male",
        "style": "strategic, structured, and focused on architecture and scalability",
        "voice_settings": {"stability": 0.65, "similarity_boost": 0.75}
    },
    "startup_founder": {
        "name": "Riley Brooks",
        "gender": "male",
        "style": "curious, energetic, and focused on ownership, impact, and practical decisions",
        "voice_settings": {"stability": 0.55, "similarity_boost": 0.75}
    },
    "rapid_fire_interviewer": {
        "name": "Taylor Reed",
        "gender": "female",
        "style": "direct, fast-paced, and focused on concise technical reasoning",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}
    }
}

# Difficulty levels determine question depth
DIFFICULTY_LEVELS = {
    "junior": {
        "focus": "fundamentals, basic problem-solving",
        "rounds": 3,  # 3 questions for junior
        "scoring_rubric": "Correctness, explanation clarity, willingness to learn"
    },
    "mid": {
        "focus": "system design, optimization, trade-offs",
        "rounds": 4,
        "scoring_rubric": "Technical depth, communication, problem-solving approach"
    },
    "senior": {
        "focus": "architecture, scalability, mentorship mindset",
        "rounds": 5,
        "scoring_rubric": "Strategic thinking, leadership, technical vision"
    }
}

DIFFICULTY_LABELS = {
    "junior": "Junior",
    "mid": "Mid-Level",
    "senior": "Senior"
}

def clean_feedback_text(value: str) -> str:
    """Remove markdown artifacts before feedback is sent to the browser."""
    return value.replace("#", "").strip()


def generate_demo_question(role: str, difficulty: str, topic: str, question_number: int) -> str:
    """Return a static question when running in demo mode without external AI APIs."""
    template_map = {
        "junior": [
            "Describe a time when you improved reliability for a service that users depended on.",
            "How would you explain a system bottleneck to a teammate who is new to the project?",
            "What would you check first if a production API started returning 500 errors?",
        ],
        "mid": [
            "Design a way to scale a read-heavy service while keeping latency predictable under sudden traffic spikes.",
            "How would you troubleshoot a database bottleneck when the app is slow but CPU usage looks normal?",
            "What trade-offs would you consider when choosing between async processing and synchronous requests?",
        ],
        "senior": [
            "Design a resilient architecture for a global product with high availability, regional failover, and minimal downtime.",
            "How would you structure teams and systems to balance delivery speed with operational safety at scale?",
            "What would you change in an organization if two critical services had repeated outages caused by weak ownership boundaries?",
        ],
    }
    choices = template_map.get(difficulty, template_map["mid"])
    return choices[(question_number - 1) % len(choices)]


def generate_demo_evaluation(role: str, difficulty: str, question: str, candidate_answer: str) -> Dict[str, any]:
    """Return deterministic scores and feedback for demo deployments."""
    base_score = 8.5 if difficulty == "mid" else 7.8 if difficulty == "junior" else 9.1
    return {
        "overall_score": round(base_score, 1),
        "correctness": round(base_score - 0.2, 1),
        "clarity": round(base_score + 0.2, 1),
        "approach": round(base_score - 0.1, 1),
        "communication": round(base_score + 0.3, 1),
        "strengths": [
            "You explain trade-offs clearly and are structured in your reasoning.",
            "You prioritize user impact and system reliability in your approach.",
        ],
        "weaknesses": [
            "You could strengthen the operational details of your rollout plan.",
            "You may want to talk more explicitly about failure modes and mitigation.",
        ],
        "follow_up_needed": False,
    }


def generate_demo_final_report(role: str, difficulty: str, candidate_name: str, topic: str) -> Dict:
    """Return a static final report for deployed demo mode."""
    report = {
        "candidate_name": candidate_name,
        "role": role,
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS.get(difficulty, "Mid-Level"),
        "overall_score": 8.7,
        "correctness": 8.5,
        "clarity": 9.0,
        "approach": 8.6,
        "communication": 8.8,
        "total_questions": DIFFICULTY_LEVELS[difficulty]["rounds"],
        "recommendation": "YES",
        "summary": "**Overall Assessment**\nYou show a strong systems mindset and clear communication.\n\n**Key Strengths**\nYou explain trade-offs well and stay grounded in product impact.\n\n**Areas to Improve**\nYou could add more operational detail around rollout, observability, and failure recovery.\n\n**Recommendation**\nYES",
        "all_evaluations": [],
    }
    return report


def validate_interview_config(config: Dict) -> Dict:
    """Validate interview configuration before starting a session."""
    if not isinstance(config, dict):
        raise ValueError("Invalid interview request: request body must be a JSON object.")

    role = str(config.get("role", "")).strip()
    difficulty = str(config.get("difficulty", "")).strip()
    topic = str(config.get("topic", "")).strip()
    persona_type = str(config.get("persona", "friendly_mentor")).strip() or "friendly_mentor"
    candidate_name = str(config.get("candidate_name", "Candidate")).strip() or "Candidate"

    if not role:
        raise ValueError("Invalid interview request: role is required.")
    if difficulty not in DIFFICULTY_LEVELS:
        raise ValueError(f"Invalid interview request: difficulty '{difficulty}' is not supported.")
    if not topic:
        raise ValueError("Invalid interview request: topic is required.")
    if persona_type not in INTERVIEWER_PERSONAS:
        raise ValueError(f"Invalid interview request: persona '{persona_type}' is not supported.")
    if not candidate_name:
        candidate_name = "Candidate"

    return {
        "role": role,
        "difficulty": difficulty,
        "topic": topic,
        "persona": persona_type,
        "candidate_name": candidate_name,
    }


async def generate_interview_question(
    role: str,
    difficulty: str,
    persona_type: str,
    question_number: int,
    total_questions: int,
    previous_answers: List[Dict] = None,
    topic: str = ""
) -> str:
    """
    Generate the next interview question using Claude.
    
    Args:
        role: Job title (e.g., "Backend Engineer", "Product Manager")
        difficulty: "junior", "mid", or "senior"
        persona_type: Interviewer personality
        question_number: Which question is this (1, 2, 3, etc.)
        total_questions: Total questions in this interview
        previous_answers: Candidate's previous answers for context
    
    Returns:
        The interview question as a string
    """
    
    persona = INTERVIEWER_PERSONAS[persona_type]
    difficulty_info = DIFFICULTY_LEVELS[difficulty]
    
    # Build context from previous answers
    history = ""
    if previous_answers:
        history = "\n\nCandidate's previous answers:\n"
        for i, answer in enumerate(previous_answers, 1):
            history += f"Q{i}: {answer['question'][:100]}...\n"
            history += f"A{i}: {answer['answer'][:150]}...\n\n"
    
    # System prompt: tells Claude how to act as an interviewer
    prompt_version = os.getenv("PROMPT_VERSION_INTERVIEW_QUESTION", "v2")
    prompt_context = {
        "role": role,
        "difficulty": difficulty,
        "topic": topic,
        "question_number": question_number,
        "total_questions": total_questions,
        "persona_name": persona["name"],
        "persona_style": persona["style"],
        "focus": difficulty_info["focus"],
        "history": history,
    }
    system_prompt = build_prompt(
        "interview_question",
        version=prompt_version,
        **prompt_context,
    )
    
    user_prompt = f"Generate a {difficulty} level interview question for a {role} candidate specifically about {topic}.{history}"
    
    if USE_DEMO_MODE or anthropic_client is None:
        return generate_demo_question(role, difficulty, topic, question_number)

    # Call Claude to generate the question
    response = anthropic_client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        max_tokens=300,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    # Extract the question text
    question = response.content[0].text.strip()
    return question

async def evaluate_answer(
    role: str,
    difficulty: str,
    question: str,
    candidate_answer: str,
    question_number: int
) -> Dict[str, any]:
    """
    Use Claude to score the candidate's answer and provide feedback.
    
    Args:
        role: Job position
        difficulty: Skill level
        question: The question asked
        candidate_answer: The candidate's spoken/typed response
        question_number: Which question this is
    
    Returns:
        Dictionary with score, strengths, weaknesses, and suggested follow-up
    """
    
    difficulty_info = DIFFICULTY_LEVELS[difficulty]
    rubric = difficulty_info["scoring_rubric"]
    prompt_version = os.getenv("PROMPT_VERSION_ANSWER_EVALUATION", "v1")
    system_prompt = build_prompt(
        "answer_evaluation",
        version=prompt_version,
        role=role,
        difficulty=difficulty,
        question=question,
        candidate_answer=candidate_answer,
    )
    system_prompt = f"""You are an expert technical interviewer evaluating a candidate's answer.

Job Role: {role}
Difficulty Level: {difficulty}
Scoring Rubric: {rubric}

    Evaluate the candidate's answer on:
1. Correctness (1-10)
2. Clarity of explanation (1-10)
3. Problem-solving approach (1-10)
4. Communication quality (1-10)

The candidate transcript below is the answer being graded. An empty transcript or
an answer such as "I don't know" must receive the lowest scores, not a neutral score.
Do not infer an answer that is not present in the transcript.

Respond in JSON format:
{{
    "overall_score": <average of above 4 scores, from 1 to 10>,
    "correctness": <1-10>,
    "clarity": <1-10>,
    "approach": <1-10>,
    "communication": <1-10>,
    "strengths": ["strength 1", "strength 2"],
    "weaknesses": ["weakness 1", "weakness 2"],
    "follow_up_needed": true/false
}}

For strengths and weaknesses, address the candidate directly using "you". Return each
item as one short plain-text bullet point without markdown symbols or hash characters.
Use simple actionable concepts, such as "You should improve your understanding of..."
or "You should strengthen your fundamentals of...". Do not use generic feedback when
the transcript contains a real answer. Be fair but rigorous. A senior engineer should
score higher than a junior for the same answer."""
    
    user_prompt = f"""Question asked: "{question}"

Candidate's answer: "{candidate_answer}"

Evaluate this answer according to the rubric above."""
    
    if USE_DEMO_MODE or anthropic_client is None:
        return generate_demo_evaluation(role, difficulty, question, candidate_answer)

    # Call Claude to evaluate
    response = anthropic_client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        max_tokens=600,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    # Parse the JSON response
    try:
        response_text = response.content[0].text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0].strip()
        evaluation = json.loads(response_text)

        def normalize_score(value):
            score = float(value)
            if score > 10:
                score /= 10
            return round(max(1, min(10, score)), 1)

        for key in ("correctness", "clarity", "approach", "communication"):
            evaluation[key] = normalize_score(evaluation.get(key, 1))
        evaluation["overall_score"] = round(
            sum(evaluation[key] for key in ("correctness", "clarity", "approach", "communication")) / 4,
            1
        )
        evaluation["strengths"] = [clean_feedback_text(item) for item in evaluation.get("strengths", [])[:3]]
        evaluation["weaknesses"] = [clean_feedback_text(item) for item in evaluation.get("weaknesses", [])[:3]]
        return evaluation
    except json.JSONDecodeError:
        # Fallback if Claude doesn't return valid JSON
        return {
            "overall_score": 1,
            "correctness": 1,
            "clarity": 1,
            "approach": 1,
            "communication": 1,
            "strengths": [],
            "weaknesses": ["You should provide a complete response tied to the question."],
            "follow_up_needed": False
        }

def generate_demo_audio() -> bytes:
    """Generate a tiny silent WAV payload so the browser can play the demo flow without external TTS."""
    import struct
    import wave
    from io import BytesIO

    sample_rate = 8000
    duration = 0.2
    frames = int(sample_rate * duration)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for _ in range(frames):
            wav_file.writeframes(struct.pack("<h", 0))
    return buffer.getvalue()


async def text_to_speech(text: str, voice_id: str, voice_settings: dict = None) -> bytes:
    """
    Convert interviewer's speech to audio using ElevenLabs.
    
    Args:
        text: The text to speak (interview question)
        voice_id: Which voice to use (male/female preset)
        voice_settings: Stability and similarity settings
    
    Returns:
        Audio bytes (MP3 format)
    """
    if USE_DEMO_MODE or elevenlabs_client is None:
        return generate_demo_audio()
    
    try:
        if voice_settings:
            # Use custom voice settings for personality
            audio = elevenlabs_client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_turbo_v2_5",
                voice_settings=voice_settings
            )
        else:
            # Use default settings
            audio = elevenlabs_client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id="eleven_turbo_v2_5"
            )
    except Exception as e:
        print(f"TTS error: {e}")
        # Fallback to simplest call
        audio = elevenlabs_client.text_to_speech.convert(
            voice_id=voice_id,
            text=text
        )
    
    # ElevenLabs returns an iterable of audio chunks; collect them
    audio_bytes = b""
    for chunk in audio:
        audio_bytes += chunk
    
    return audio_bytes

async def speech_to_text(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Transcribe a candidate's recorded answer with ElevenLabs Scribe."""
    if USE_DEMO_MODE or elevenlabs_client is None:
        return "I would start by identifying the bottleneck, measuring the failure mode, and then I would design the smallest safe fix before scaling the system."

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    extension = "webm" if "webm" in mime_type else "wav"
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            files={"file": (f"interview-answer.{extension}", audio_bytes, mime_type)},
            data={"model_id": "scribe_v1"}
        )
        response.raise_for_status()
        transcription = response.json().get("text", "").strip()

    return transcription

async def generate_final_report(
    role: str,
    difficulty: str,
    all_evaluations: List[Dict],
    candidate_name: str,
    topic: str
) -> Dict:
    """
    Generate a comprehensive interview feedback report.
    
    Args:
        role: The position being interviewed for
        difficulty: Skill level
        all_evaluations: Scores and feedback from all questions
        candidate_name: Candidate's name
    
    Returns:
        Detailed report with recommendation
    """
    
    # Calculate aggregate scores
    avg_score = sum(e["overall_score"] for e in all_evaluations) / len(all_evaluations)
    avg_clarity = sum(e.get("clarity", 1) for e in all_evaluations) / len(all_evaluations)
    avg_correctness = sum(e.get("correctness", 1) for e in all_evaluations) / len(all_evaluations)
    avg_approach = sum(e.get("approach", 1) for e in all_evaluations) / len(all_evaluations)
    avg_communication = sum(e.get("communication", 1) for e in all_evaluations) / len(all_evaluations)
    
    # Collect all feedback
    all_strengths = []
    all_weaknesses = []
    for e in all_evaluations:
        all_strengths.extend(e.get("strengths", []))
        all_weaknesses.extend(e.get("weaknesses", []))
    
    if USE_DEMO_MODE or anthropic_client is None:
        return generate_demo_final_report(role, difficulty, candidate_name, topic)

    # Use Claude to write the final summary
    prompt_version = os.getenv("PROMPT_VERSION_FINAL_REPORT", "v1")
    system_prompt = build_prompt(
        "final_report",
        version=prompt_version,
        candidate_name=candidate_name,
        role=role,
        difficulty=difficulty,
        topic=topic,
    )
    system_prompt = f"""You are a hiring manager writing a final interview summary.

Position: {role}
Interview topic: {topic}
Level: {difficulty}
Overall Score: {avg_score:.1f}/10

Write a concise, professional summary in short readable paragraphs. Use exactly these
bold section headings on separate lines: **Overall Assessment**, **Key Strengths**,
**Areas to Improve**, and **Recommendation**. Keep each section brief and easy to scan.
Include the recommendation STRONG YES, YES, MAYBE, or NO under Recommendation.

Address the candidate directly using "you". Be direct and fair."""
    
    strengths_text = ", ".join(set(all_strengths[:3]))  # Top unique strengths
    weaknesses_text = ", ".join(set(all_weaknesses[:3]))  # Top unique weaknesses
    
    user_prompt = f"""Candidate: {candidate_name}

Key Strengths (maximum 3): {strengths_text}
Areas for Development (maximum 3): {weaknesses_text}

Average Performance:
- Correctness: {avg_correctness:.1f}/10
- Clarity: {avg_clarity:.1f}/10
- Approach: {avg_approach:.1f}/10
- Communication: {avg_communication:.1f}/10
- Overall: {avg_score:.1f}/10

Write the final summary."""
    
    response = anthropic_client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    summary = clean_feedback_text(response.content[0].text)
    
    # Determine recommendation based on score
    if avg_score >= 8:
        recommendation = "STRONG YES"
    elif avg_score >= 6.5:
        recommendation = "YES"
    elif avg_score >= 5:
        recommendation = "MAYBE"
    else:
        recommendation = "NO"
    
    return {
        "candidate_name": candidate_name,
        "role": role,
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS[difficulty],
        "overall_score": round(avg_score, 1),
        "correctness": round(avg_correctness, 1),
        "clarity": round(avg_clarity, 1),
        "approach": round(avg_approach, 1),
        "communication": round(avg_communication, 1),
        "total_questions": len(all_evaluations),
        "recommendation": recommendation,
        "summary": summary,
        "all_evaluations": all_evaluations
    }

@app.websocket("/ws/interview")
async def interview_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for conducting the interview.
    
    Flow:
    1. Client sends interview config (role, difficulty, persona)
    2. Server generates questions 1 by 1
    3. Client records candidate's answer
    4. Server evaluates answer and sends feedback
    5. Repeat until N questions answered
    6. Send final report
    """
    
    await websocket.accept()
    
    try:
        # Step 1: Receive interview configuration from client
        config = await websocket.receive_json()
        validated = validate_interview_config(config)

        role = validated["role"]
        difficulty = validated["difficulty"]
        topic = validated["topic"]
        persona_type = validated["persona"]
        candidate_name = validated["candidate_name"]

        # Get persona and difficulty details
        persona = INTERVIEWER_PERSONAS[persona_type]
        gender = persona["gender"]
        voice_id = VOICE_IDS[gender]
        voice_settings = persona["voice_settings"]
        
        difficulty_info = DIFFICULTY_LEVELS[difficulty]
        total_questions = difficulty_info["rounds"]
        
        session_id = create_interview_session(
            role=role,
            difficulty=difficulty,
            topic=topic,
            persona_type=persona_type,
            candidate_name=candidate_name,
        )

        # Send acknowledgement
        await websocket.send_json({
            "type": "interview_start",
            "session_id": session_id,
            "interviewer_name": persona["name"],
            "role": role,
            "difficulty": difficulty,
            "difficulty_label": DIFFICULTY_LABELS[difficulty],
            "topic": topic,
            "total_questions": total_questions
        })
        
        # Step 2: Conduct the interview (loop through questions)
        all_answers = []
        all_evaluations = []
        
        for question_num in range(1, total_questions + 1):
            await websocket.send_json({
                "type": "status",
                "message": f"Generating question {question_num} of {total_questions}...",
                "phase": "generation",
                "question_number": question_num,
                "total_questions": total_questions
            })

            # Generate the next question
            question = await generate_interview_question(
                role=role,
                difficulty=difficulty,
                persona_type=persona_type,
                question_number=question_num,
                total_questions=total_questions,
                previous_answers=all_answers,
                topic=topic
            )
            
            # Convert question to speech
            audio = await text_to_speech(question, voice_id, voice_settings)
            audio_base64 = base64.b64encode(audio).decode("utf-8")

            # Send the question
            await websocket.send_json({
                "type": "question",
                "question_number": question_num,
                "total_questions": total_questions,
                "text": question,
                "audio": audio_base64  # Client plays this
            })
            
            # Step 3: Wait for the candidate's recorded answer.
            answer_message = await websocket.receive_json()
            while answer_message.get("type") != "answer" or not answer_message.get("audio_base64"):
                await websocket.send_json({
                    "type": "status",
                    "message": "Record an answer before continuing."
                })
                answer_message = await websocket.receive_json()

            await websocket.send_json({
                "type": "status",
                "message": "Processing audio and evaluating your response..."
            })
            audio_bytes = base64.b64decode(answer_message["audio_base64"])
            candidate_answer = await speech_to_text(
                audio_bytes,
                answer_message.get("mime_type", "audio/webm")
            )
            if not candidate_answer:
                candidate_answer = "[No audible answer was transcribed.]"
            
            # Step 4: Evaluate the answer
            evaluation = await evaluate_answer(
                role=role,
                difficulty=difficulty,
                question=question,
                candidate_answer=candidate_answer,
                question_number=question_num
            )
            
            # Store for final report
            all_answers.append({
                "question": question,
                "answer": candidate_answer,
                "number": question_num
            })
            all_evaluations.append(evaluation)
            save_answer_record(
                session_id=session_id,
                question_number=question_num,
                question=question,
                answer=candidate_answer,
                evaluation=evaluation,
            )

            pending_report = None
            if question_num == total_questions:
                pending_report = await generate_final_report(
                    role=role,
                    difficulty=difficulty,
                    all_evaluations=all_evaluations,
                    candidate_name=candidate_name,
                    topic=topic
                )
                update_session_status(
                    session_id=session_id,
                    status="completed",
                    final_report=pending_report,
                )
            else:
                update_session_status(session_id=session_id, status="in_progress")
            
            # Send evaluation feedback to client
            await websocket.send_json({
                "type": "evaluation",
                "question_number": question_num,
                "total_questions": total_questions,
                "transcript": candidate_answer,
                "score": evaluation["overall_score"],
                "correctness": evaluation["correctness"],
                "clarity": evaluation["clarity"],
                "strengths": evaluation["strengths"],
                "weaknesses": evaluation["weaknesses"],
                "approach": evaluation["approach"],
                "communication": evaluation["communication"],
                "final_report": pending_report,
                "follow_up_needed": evaluation.get("follow_up_needed", False)
            })

            expected_action = "continue" if question_num < total_questions else "complete"
            next_action = await websocket.receive_json()
            while next_action.get("type") != expected_action:
                next_action = await websocket.receive_json()

            if question_num < total_questions:
                pass
            
            # Small pause between questions
            await asyncio.sleep(1)
        
        # Step 5: Generate and send final report
        await websocket.send_json({
            "type": "interview_complete",
            "report": pending_report
        })
        
    except WebSocketDisconnect:
        print("Candidate disconnected")
    except Exception as e:
        print(f"Interview error: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except Exception:
            pass


@app.get("/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """Return a saved interview session and its answers."""
    session = get_interview_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/")
async def root():
    """Simple health check"""
    return {"message": "AI Interview Coach API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)


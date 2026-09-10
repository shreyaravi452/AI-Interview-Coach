import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("USE_DEMO_MODE", "false")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-live-key-12345")
os.environ.setdefault("ELEVENLABS_API_KEY", "sk-test-live-tts-key-12345")
os.environ.setdefault("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

import main as app_module  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app_module.app) as test_client:
        yield test_client


def test_root_health_check(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "AI Interview Coach API is running"}


def test_placeholder_api_keys_are_ignored():
    assert app_module.resolve_api_key("ANTHROPIC_API_KEY", "your_anthropic_api_key_here") is None
    assert app_module.resolve_api_key("ELEVENLABS_API_KEY", "your_elevenlabs_api_key_here") is None
    assert app_module.resolve_api_key("ANTHROPIC_API_KEY", "sk-live-realkey123") == "sk-live-realkey123"


def test_evaluate_answer_uses_normalized_scores_and_feedback(monkeypatch):
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps({
            "overall_score": 8.5,
            "correctness": 8,
            "clarity": 9,
            "approach": 8,
            "communication": 9,
            "strengths": [
                "You explain trade-offs clearly.",
                "You identify bottlenecks early."
            ],
            "weaknesses": [
                "You should improve your understanding of failure modes."
            ],
            "follow_up_needed": False
        }))]
    )

    fake_anthropic = SimpleNamespace(
        messages=SimpleNamespace(create=MockCreate(fake_response))
    )
    monkeypatch.setattr(app_module, "anthropic_client", fake_anthropic)

    result = asyncio.run(app_module.evaluate_answer(
        role="Backend Engineer",
        difficulty="mid",
        question="How do you scale a database?",
        candidate_answer="I start by identifying the bottleneck, then I use read replicas, caching, and queueing to reduce load.",
        question_number=1,
    ))

    assert result["overall_score"] == 8.5
    assert result["correctness"] == 8.0
    assert result["clarity"] == 9.0
    assert result["approach"] == 8.0
    assert result["communication"] == 9.0
    assert result["strengths"] == [
        "You explain trade-offs clearly.",
        "You identify bottlenecks early."
    ]
    assert result["weaknesses"] == [
        "You should improve your understanding of failure modes."
    ]
    assert result["follow_up_needed"] is False


def test_generate_final_report_returns_summary_and_recommendation(monkeypatch):
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="**Overall Assessment**\nYou have a strong systems mindset and good communication.\n\n**Key Strengths**\nYou explain trade-offs well.\n\n**Areas to Improve**\nYou should deepen your failover strategy.\n\n**Recommendation**\nYES")]
    )

    fake_anthropic = SimpleNamespace(
        messages=SimpleNamespace(create=MockCreate(fake_response))
    )
    monkeypatch.setattr(app_module, "anthropic_client", fake_anthropic)

    evaluations = [
        {
            "overall_score": 8.5,
            "correctness": 8,
            "clarity": 9,
            "approach": 8,
            "communication": 9,
            "strengths": ["You explain trade-offs well."],
            "weaknesses": ["You should deepen your failover strategy."],
        },
        {
            "overall_score": 7.0,
            "correctness": 7,
            "clarity": 6,
            "approach": 8,
            "communication": 7,
            "strengths": ["You communicate clearly."],
            "weaknesses": ["You should improve your testing rigor."],
        },
    ]

    result = asyncio.run(app_module.generate_final_report(
        role="Backend Engineer",
        difficulty="mid",
        all_evaluations=evaluations,
        candidate_name="Jordan",
        topic="Scalable API design",
    ))

    assert result["candidate_name"] == "Jordan"
    assert result["recommendation"] == "YES"
    assert result["overall_score"] >= 7.5
    assert "**Overall Assessment**" in result["summary"]
    assert "**Recommendation**" in result["summary"]


def test_interview_websocket_core_flow(monkeypatch):
    monkeypatch.setitem(app_module.DIFFICULTY_LEVELS["junior"], "rounds", 1)

    monkeypatch.setattr(
        app_module,
        "generate_interview_question",
        AsyncMock(return_value="Describe a time you improved reliability in production."),
    )
    monkeypatch.setattr(
        app_module,
        "text_to_speech",
        AsyncMock(return_value=b"audio-bytes"),
    )
    monkeypatch.setattr(
        app_module,
        "speech_to_text",
        AsyncMock(return_value="I added dashboards, improved alerts, and reduced incident time."),
    )
    monkeypatch.setattr(
        app_module,
        "evaluate_answer",
        AsyncMock(return_value={
            "overall_score": 8.2,
            "correctness": 8,
            "clarity": 9,
            "approach": 8,
            "communication": 8,
            "strengths": ["You explain the impact clearly."],
            "weaknesses": ["You should expand on trade-offs."],
            "follow_up_needed": False,
        }),
    )
    monkeypatch.setattr(
        app_module,
        "generate_final_report",
        AsyncMock(return_value={
            "candidate_name": "Alex",
            "role": "Backend Engineer",
            "difficulty": "junior",
            "difficulty_label": "Junior",
            "overall_score": 8.2,
            "recommendation": "YES",
            "summary": "**Overall Assessment**\nYou performed well.",
        }),
    )

    with TestClient(app_module.app) as test_client:
        with test_client.websocket_connect("/ws/interview") as websocket:
            websocket.send_json({
                "role": "Backend Engineer",
                "difficulty": "junior",
                "topic": "Production reliability",
                "persona": "friendly_mentor",
                "candidate_name": "Alex",
            })

            start = websocket.receive_json()
            assert start["type"] == "interview_start"

            message = None
            while True:
                message = websocket.receive_json()
                if message["type"] == "question":
                    break

            assert message["type"] == "question"
            assert "Describe a time you improved reliability in production." in message["text"]

            websocket.send_json({
                "type": "answer",
                "audio_base64": base64.b64encode(b"fake-audio").decode("utf-8"),
                "mime_type": "audio/wav",
            })

            evaluation = None
            while True:
                evaluation = websocket.receive_json()
                if evaluation["type"] == "evaluation":
                    break

            assert evaluation["score"] == 8.2
            assert evaluation["transcript"] == "I added dashboards, improved alerts, and reduced incident time."

            websocket.send_json({"type": "complete"})

            final = websocket.receive_json()
            assert final["type"] == "interview_complete"
            assert final["report"]["recommendation"] == "YES"


def test_session_persistence_round_trip(monkeypatch, tmp_path):
    db_path = tmp_path / "interviews.db"
    monkeypatch.setenv("INTERVIEW_DB_PATH", str(db_path))
    app_module.init_db()

    session_id = app_module.create_interview_session(
        role="Backend Engineer",
        difficulty="mid",
        topic="Scaling APIs",
        persona_type="friendly_mentor",
        candidate_name="Jordan",
    )

    app_module.save_answer_record(
        session_id=session_id,
        question_number=1,
        question="How would you scale a read-heavy API?",
        answer="I would add caching and read replicas.",
        evaluation={
            "overall_score": 8.5,
            "correctness": 8,
            "clarity": 9,
            "approach": 8,
            "communication": 9,
            "strengths": ["You explain trade-offs clearly."],
            "weaknesses": ["You should expand on failure modes."],
        },
    )

    app_module.update_session_status(
        session_id=session_id,
        status="completed",
        final_report={
            "candidate_name": "Jordan",
            "recommendation": "YES",
            "summary": "Strong candidate performance.",
        },
    )

    stored = app_module.get_interview_session(session_id)

    assert stored["candidate_name"] == "Jordan"
    assert stored["status"] == "completed"
    assert stored["final_report"]["recommendation"] == "YES"
    assert len(stored["answers"]) == 1
    assert stored["answers"][0]["question_number"] == 1
    assert stored["answers"][0]["question"] == "How would you scale a read-heavy API?"


def test_session_detail_endpoint_returns_saved_session(monkeypatch, tmp_path):
    db_path = tmp_path / "interviews.db"
    monkeypatch.setenv("INTERVIEW_DB_PATH", str(db_path))
    app_module.init_db()

    session_id = app_module.create_interview_session(
        role="Backend Engineer",
        difficulty="senior",
        topic="Distributed systems",
        persona_type="systems_architect",
        candidate_name="Sam",
    )

    with TestClient(app_module.app) as test_client:
        response = test_client.get(f"/sessions/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_name"] == "Sam"
    assert payload["role"] == "Backend Engineer"
    assert payload["difficulty"] == "senior"
    assert payload["status"] == "in_progress"


def test_invalid_websocket_config_is_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "anthropic_client", SimpleNamespace())
    monkeypatch.setattr(app_module, "elevenlabs_client", SimpleNamespace())

    with TestClient(app_module.app) as test_client:
        with test_client.websocket_connect("/ws/interview") as websocket:
            websocket.send_json({
                "role": "Backend Engineer",
                "difficulty": "invalid-level",
                "topic": "",
                "persona": "friendly_mentor",
                "candidate_name": "Alex",
            })
            message = websocket.receive_json()

    assert message["type"] == "error"
    assert "Invalid interview request" in message["message"]


class MockCreate:
    def __init__(self, response):
        self.response = response

    def __call__(self, *args, **kwargs):
        return self.response

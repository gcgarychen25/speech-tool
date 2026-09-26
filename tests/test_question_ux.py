import logging

from fastapi.testclient import TestClient
from speech_tool.app import create_app
from speech_tool.pipeline import Pipeline
from speech_tool.polish import PassthroughPolisher, PolishResult
from speech_tool.question import relevant_context_indices, build_question_prompt
from speech_tool.store import EventStore
from tests.fakes import FakeAsr


def test_context_matches_earlier_topic_and_falls_back():
    texts = ["YOLO uses regression to predict bounding boxes", "precision and recall", "end of class"]
    assert relevant_context_indices(texts, "what is YOLO regression?")[0] == [0]
    assert relevant_context_indices(texts, "unseen topic")[0] == [1, 2]
    assert relevant_context_indices(["", " "], "YOLO")[0] == []


def test_prompt_preserves_question_unless_exploration_is_explicit():
    prompt = build_question_prompt("YOLO regression?", "boxes")
    assert "wording-only polish" in prompt
    assert "Do not infer a missing mechanism" in prompt
    assert "do not invent" in prompt
    assert "Explicit exploration request" not in prompt
    assert "one short clarification" in build_question_prompt("what flow?", "", mode="explore")


def test_suggestion_does_not_replace_draft_and_failures_are_logged(tmp_path, monkeypatch, caplog):
    store = EventStore(tmp_path)
    pipe = Pipeline(store, asr=FakeAsr(), polisher=PassthroughPolisher(), auto_start=False)
    client = TestClient(create_app(store, pipe))
    session = client.post("/api/sessions", json={"course": "CV"}).json()["id"]
    endpoint = f"/api/sessions/{session}/questions"
    client.post(endpoint + "/edit", json={"text": "My own wording"})
    response = client.post(endpoint, json={"confusion": "YOLO regression", "preserve_draft": True})
    assert response.status_code == 200
    detail = client.get(f"/api/sessions/{session}").json()
    assert detail["latest_question"] == "My own wording"
    assert detail["latest_question_suggestion"]["question"] == "YOLO regression?"
    assert response.json()["context_source"] == "Your question only"
    assert response.json()["request_id"]
    monkeypatch.setattr("speech_tool.question.draft_question", lambda **kwargs: PolishResult(text="", model="test", version="timeout"))
    with caplog.at_level(logging.WARNING):
        failed = client.post(endpoint, json={"confusion": "private question", "preserve_draft": True})
    assert failed.status_code == 504
    assert "AI took too long" in failed.json()["detail"]
    assert "question timeout" in caplog.text
    assert "private question" not in caplog.text
    assert client.get(f"/api/sessions/{session}").json()["latest_question"] == "My own wording"
    monkeypatch.setattr(
        "speech_tool.question.draft_question",
        lambda **kwargs: PolishResult(text="", model="test", version="provider_unavailable"),
    )
    unavailable = client.post(endpoint, json={"confusion": "still private", "preserve_draft": True})
    assert unavailable.status_code == 502
    assert unavailable.json()["detail"].startswith("Question helper is unavailable right now")
    assert "cleanup" not in unavailable.json()["detail"].lower()
    assert "still private" not in unavailable.json()["detail"]

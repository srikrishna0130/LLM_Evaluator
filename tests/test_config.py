from app.core.config import Settings


def test_candidate_defaults():
    """Candidate (shadow) model settings expose sane defaults."""
    s = Settings(_env_file=None)  # ignore .env so we assert code defaults

    assert s.CANDIDATE_BASE_URL == "https://inference.do-ai.run/v1"
    assert s.CANDIDATE_MODEL == "openai-gpt-5-mini"
    assert s.MODEL_ACCESS_KEY == ""  # secret must come from env, never hardcoded
    assert s.CANDIDATE_TIMEOUT_S == 30.0
    assert s.CANDIDATE_MAX_RETRIES == 2


def test_candidate_settings_from_env(monkeypatch):
    """Settings are overridable via environment variables (12-factor)."""
    monkeypatch.setenv("MODEL_ACCESS_KEY", "doo_v1_test_key")
    monkeypatch.setenv("CANDIDATE_MODEL", "some-org/Some-Model")
    monkeypatch.setenv("CANDIDATE_TIMEOUT_S", "5.5")
    monkeypatch.setenv("CANDIDATE_MAX_RETRIES", "0")

    s = Settings(_env_file=None)

    assert s.MODEL_ACCESS_KEY == "doo_v1_test_key"
    assert s.CANDIDATE_MODEL == "some-org/Some-Model"
    assert s.CANDIDATE_TIMEOUT_S == 5.5
    assert s.CANDIDATE_MAX_RETRIES == 0

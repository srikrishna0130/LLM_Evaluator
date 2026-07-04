import pytest

from app.services.base import BaseModelClient
from app.services.candidate_model import CandidateModelClient
from app.services.mock_model import MockModelClient


def test_clients_implement_base_contract():
    """Both concrete clients satisfy the shared BaseModelClient interface."""
    assert issubclass(MockModelClient, BaseModelClient)
    assert issubclass(CandidateModelClient, BaseModelClient)


def test_base_model_client_is_abstract():
    """BaseModelClient cannot be instantiated without implementing generate()."""
    with pytest.raises(TypeError):
        BaseModelClient()


@pytest.mark.asyncio
async def test_mock_model_generate():
    """Mock model echoes the prompt with a stable shape."""
    result = await MockModelClient().generate("hello world")

    assert result == {"text": "[mock] echo: hello world", "model": "mock-llm-v0"}


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def model_dump(self):
        return {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}


class _FakeResponse:
    def __init__(self, content, model):
        self.choices = [_FakeChoice(content)]
        self.model = model
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, recorder):
        self._recorder = recorder

    async def create(self, *, model, messages):
        self._recorder["model"] = model
        self._recorder["messages"] = messages
        return _FakeResponse("candidate says hi", model)


class _FakeChat:
    def __init__(self, recorder):
        self.completions = _FakeCompletions(recorder)


class _FakeAsyncOpenAI:
    """Stand-in for AsyncOpenAI that records calls and never hits the network."""

    def __init__(self, recorder):
        self.chat = _FakeChat(recorder)
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_candidate_generate_shape(monkeypatch):
    """generate() returns text/model/usage/latency_ms and passes the config model."""
    recorder = {}
    client = CandidateModelClient()
    fake = _FakeAsyncOpenAI(recorder)
    monkeypatch.setattr(client, "_client", fake)

    result = await client.generate("ping")

    assert result["text"] == "candidate says hi"
    assert result["usage"] == {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0
    # The configured candidate model id is forwarded to the SDK.
    assert recorder["model"] == result["model"]
    assert recorder["messages"] == [{"role": "user", "content": "ping"}]


@pytest.mark.asyncio
async def test_candidate_aclose(monkeypatch):
    """aclose() closes the underlying pooled client."""
    client = CandidateModelClient()
    fake = _FakeAsyncOpenAI({})
    monkeypatch.setattr(client, "_client", fake)

    await client.aclose()

    assert fake.closed is True

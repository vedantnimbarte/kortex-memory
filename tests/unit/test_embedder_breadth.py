"""Contract tests for the embedder and LLM adapters.

Each adapter is a translation layer between a vendor's wire format and ours,
and the way it fails is quiet: a mis-parsed response yields *a* vector, just
not the right one, and the symptom is bad retrieval months later rather than an
exception. So these tests exercise the actual request bodies and response
shapes against recorded fixtures, with the ordering and dimension cases spelled
out.

No network: httpx adapters go through respx, and the AWS ones are split so the
request building and response parsing are pure functions.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from kortex_core.embeddings import bedrock as bedrock_embed
from kortex_core.embeddings.dimensions import (
    EMBEDDING_DIM,
    EmbeddingDimensionError,
    check_dimension,
)
from kortex_core.embeddings.ollama import OllamaEmbedder
from kortex_core.embeddings.ollama import parse_response as parse_ollama
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import available_embedders
from kortex_core.embeddings.registry import reset as reset_embedders
from kortex_core.embeddings.voyage import API_URL as VOYAGE_URL
from kortex_core.embeddings.voyage import VoyageEmbedder
from kortex_core.embeddings.voyage import parse_response as parse_voyage
from kortex_core.llm import bedrock as bedrock_llm
from kortex_core.llm.protocol import LlmMessage
from kortex_core.llm.registry import available_providers


def _vec(seed: float, dim: int = EMBEDDING_DIM) -> list[float]:
    return [seed] * dim


@pytest.fixture(autouse=True)
def _clear_embedder_cache():  # type: ignore[no-untyped-def]
    reset_embedders()
    yield
    reset_embedders()


# --- registries ---


def test_every_new_provider_is_registered() -> None:
    embedders = available_embedders()
    assert {"bedrock", "ollama", "voyage"} <= set(embedders)
    assert "bedrock" in available_providers()


def test_unknown_embedder_names_the_alternatives() -> None:
    """A typo in KORTEX_EMBEDDER should not need a source dive to fix."""
    from kortex_core.embeddings.registry import get_embedder

    with pytest.raises(KeyError, match="available:"):
        get_embedder("voyag")


# --- the dimension guard ---


def test_matching_dimension_is_accepted() -> None:
    check_dimension(name="x", model_id="m", dim=EMBEDDING_DIM)


@pytest.mark.parametrize("dim", [384, 768, 1536, 3072])
def test_wrong_dimension_is_rejected_with_a_remedy(dim: int) -> None:
    """Postgres rejects every write at the wrong width, so this must fail loudly
    at construction rather than as a stream of unembedded memories."""
    with pytest.raises(EmbeddingDimensionError) as excinfo:
        check_dimension(name="voyage", model_id="voyage-3-large", dim=dim)
    message = str(excinfo.value)
    assert str(dim) in message
    assert f"VECTOR({EMBEDDING_DIM})" in message
    assert "reindex-embeddings" in message  # tells the operator the way out


def test_an_adapter_refuses_to_construct_at_the_wrong_width() -> None:
    with pytest.raises(EmbeddingDimensionError):
        VoyageEmbedder(model_id="voyage-3-large", dim=2048)


# --- Voyage ---


def test_voyage_parses_vectors_in_the_order_they_were_sent() -> None:
    """Voyage returns an `index` per row and does not promise ordering. Sorting
    by it is what stops every embedding being attached to the wrong memory."""
    payload = {
        "data": [
            {"index": 2, "embedding": _vec(0.3)},
            {"index": 0, "embedding": _vec(0.1)},
            {"index": 1, "embedding": _vec(0.2)},
        ]
    }
    vectors = parse_voyage(payload, 3)
    assert [v[0] for v in vectors] == [0.1, 0.2, 0.3]


def test_voyage_rejects_a_short_response() -> None:
    payload = {"data": [{"index": 0, "embedding": _vec(0.1)}]}
    with pytest.raises(EmbeddingError, match="asked for 2"):
        parse_voyage(payload, 2)


def test_voyage_rejects_a_response_without_data() -> None:
    with pytest.raises(EmbeddingError, match="`data`"):
        parse_voyage({"error": "nope"}, 1)


@respx.mock
async def test_voyage_sends_the_documented_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kortex_core.settings import get_settings
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "voyage_api_key", SecretStr("vk-test"), raising=False)
    route = respx.post(VOYAGE_URL).mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": _vec(0.5)}]})
    )

    vectors = await VoyageEmbedder().embed(["hello"])

    assert vectors == [_vec(0.5)]
    sent = json.loads(route.calls[0].request.content)
    assert sent["input"] == ["hello"]
    assert sent["output_dimension"] == EMBEDDING_DIM
    assert sent["input_type"] == "document"
    assert route.calls[0].request.headers["authorization"] == "Bearer vk-test"


async def test_voyage_without_a_key_says_which_one(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kortex_core.settings import get_settings

    monkeypatch.setattr(get_settings(), "voyage_api_key", None, raising=False)
    with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY"):
        await VoyageEmbedder().embed(["hello"])


async def test_embedding_nothing_makes_no_call() -> None:
    assert await VoyageEmbedder().embed([]) == []


# --- Ollama ---


def test_ollama_accepts_the_batch_response_shape() -> None:
    assert parse_ollama({"embeddings": [_vec(0.1), _vec(0.2)]}, 2) == [_vec(0.1), _vec(0.2)]


def test_ollama_accepts_the_older_single_vector_shape() -> None:
    """Which shape you get depends on the daemon's version, not on anything the
    operator chose."""
    assert parse_ollama({"embedding": _vec(0.4)}, 1) == [_vec(0.4)]


def test_ollama_rejects_an_unrecognised_shape() -> None:
    with pytest.raises(EmbeddingError, match="neither"):
        parse_ollama({"result": []}, 1)


@respx.mock
async def test_ollama_posts_to_the_configured_host() -> None:
    from kortex_core.settings import get_settings

    base = get_settings().ollama_base_url.rstrip("/")
    route = respx.post(f"{base}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [_vec(0.7)]})
    )

    vectors = await OllamaEmbedder().embed(["hi"])

    assert vectors == [_vec(0.7)]
    sent = json.loads(route.calls[0].request.content)
    assert sent["input"] == ["hi"]
    assert sent["model"] == "mxbai-embed-large"


@respx.mock
async def test_ollama_catches_a_model_serving_the_wrong_width() -> None:
    """Ollama serves whatever was pulled, so the declared dimension is a claim
    until a response proves it. A 768-dim model would otherwise have every
    insert rejected by Postgres."""
    from kortex_core.settings import get_settings

    base = get_settings().ollama_base_url.rstrip("/")
    respx.post(f"{base}/api/embed").mock(
        return_value=httpx.Response(200, json={"embeddings": [_vec(0.1, dim=768)]})
    )
    with pytest.raises(EmbeddingError, match="768-dimensional"):
        await OllamaEmbedder().embed(["hi"])


@respx.mock
async def test_ollama_being_down_suggests_the_fix() -> None:
    from kortex_core.settings import get_settings

    base = get_settings().ollama_base_url.rstrip("/")
    respx.post(f"{base}/api/embed").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(EmbeddingError, match="ollama serve"):
        await OllamaEmbedder().embed(["hi"])


# --- Bedrock embeddings ---


def test_bedrock_titan_request_asks_for_the_schema_width() -> None:
    body = json.loads(bedrock_embed.build_request("amazon.titan-embed-text-v2:0", "hi", 1024))
    assert body == {"inputText": "hi", "dimensions": 1024, "normalize": True}


def test_bedrock_cohere_uses_its_own_request_shape() -> None:
    """The two families take different bodies; sending Titan's to Cohere is a
    ValidationException, not a wrong vector."""
    body = json.loads(bedrock_embed.build_request("cohere.embed-english-v3", "hi", 1024))
    assert body == {"texts": ["hi"], "input_type": "search_document"}


def test_bedrock_parses_each_family_response() -> None:
    assert bedrock_embed.parse_response(
        "amazon.titan-embed-text-v2:0", {"embedding": _vec(0.2)}
    ) == _vec(0.2)
    assert bedrock_embed.parse_response(
        "cohere.embed-english-v3", {"embeddings": [_vec(0.3)]}
    ) == _vec(0.3)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        ("amazon.titan-embed-text-v2:0", {"message": "throttled"}),
        ("cohere.embed-english-v3", {"embeddings": []}),
    ],
)
def test_bedrock_rejects_a_response_with_no_vector(model: str, payload: dict) -> None:
    with pytest.raises(EmbeddingError):
        bedrock_embed.parse_response(model, payload)


def test_bedrock_bounds_its_concurrency() -> None:
    """Unbounded fan-out over a 64-item batch is a throttling incident, not a
    speed-up."""
    assert 1 <= bedrock_embed.MAX_CONCURRENCY <= 16


# --- Bedrock LLM ---


def test_converse_takes_the_system_prompt_out_of_the_messages() -> None:
    """Converse rejects a message with role="system"."""
    system, turns = bedrock_llm.split_messages(
        [
            LlmMessage(role="system", content="be terse"),
            LlmMessage(role="user", content="hello"),
        ]
    )
    assert system == [{"text": "be terse"}]
    assert turns == [{"role": "user", "content": [{"text": "hello"}]}]
    assert all(t["role"] != "system" for t in turns)


def test_converse_response_yields_text_and_usage() -> None:
    text, tin, tout = bedrock_llm.parse_response(
        {
            "output": {"message": {"content": [{"text": "part one "}, {"text": "part two"}]}},
            "usage": {"inputTokens": 12, "outputTokens": 34},
        }
    )
    assert text == "part one part two"
    assert (tin, tout) == (12, 34)


def test_converse_response_without_usage_reports_zero_not_a_crash() -> None:
    assert bedrock_llm.parse_response({}) == ("", 0, 0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"correct": true}', {"correct": True}),
        ('```json\n{"correct": true}\n```', {"correct": True}),
        ('Sure! Here you go:\n{"correct": true}', {"correct": True}),
    ],
)
def test_json_is_recovered_from_the_usual_model_wrappers(raw: str, expected: dict) -> None:
    """Converse enforces no schema, so the text arrives however the model felt
    like formatting it."""
    assert bedrock_llm.extract_json(raw) == expected


@pytest.mark.parametrize("raw", ["", "no json here", "[1, 2, 3]", "{broken"])
def test_unparseable_output_is_none_rather_than_an_exception(raw: str) -> None:
    """Callers treat missing structure as "fall back", not "fail"."""
    assert bedrock_llm.extract_json(raw) is None

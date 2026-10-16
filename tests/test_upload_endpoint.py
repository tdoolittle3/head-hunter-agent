"""The upload endpoint takes files from strangers on the internet.

Like the chat endpoint, the id a file is stored under comes only from the verified
token. Beyond that the endpoint has to turn every bad file into a plain refusal,
and has to be cheap to abuse-proof: it is rate limited separately from chat, and
a user's stored uploads are capped.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from test_auth_server import (
    PROJECT,
    WEB_CONFIG,
    FakeRunner,
    bearer,
    claims,
    fake_verifier,
)
from test_doc_text import RESUME_LINES, make_docx, make_pdf

from head_hunter import doc_text, server
from head_hunter.ratelimit import RateLimiter
from head_hunter.schemas import UploadedDocument
from head_hunter.storage import JsonRepository, StorageError

TEXT = "\n".join(RESUME_LINES).encode("utf-8")


@pytest.fixture(autouse=True)
def multi_user_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> JsonRepository:
    return JsonRepository(root=tmp_path)


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


def build(runner: FakeRunner, repo: JsonRepository, **overrides: object) -> TestClient:
    tokens = {
        "alice-token": claims(),
        "bob-token": claims(sub="bob-uid", email="bob@example.com", name="Bob"),
    }
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier(tokens),
        runner=runner,
        web_config=WEB_CONFIG,
        repo_factory=lambda: repo,
        **overrides,  # type: ignore[arg-type]
    )
    return TestClient(app)


@pytest.fixture
def client(runner: FakeRunner, repo: JsonRepository) -> TestClient:
    return build(runner, repo)


def post(
    client: TestClient,
    name: str = "jane.txt",
    data: bytes = TEXT,
    token: str | None = "alice-token",
):
    headers = bearer(token) if token else {}
    return client.post("/api/upload", files={"file": (name, data)}, headers=headers)


# Who is uploading -----------------------------------------------------------


def test_uploading_needs_a_sign_in(client: TestClient, repo: JsonRepository) -> None:
    assert post(client, token=None).status_code == 401
    assert post(client, token="forged").status_code == 401
    assert repo.list_uploads("alice-uid") == []


def test_a_file_is_filed_under_the_user_in_the_token(
    client: TestClient, repo: JsonRepository
) -> None:
    response = post(client, token="bob-token")

    assert response.status_code == 200
    assert [u.filename for u in repo.list_uploads("bob-uid")] == ["jane.txt"]
    assert repo.list_uploads("alice-uid") == []


def test_the_response_says_what_was_stored(
    client: TestClient, repo: JsonRepository
) -> None:
    body = post(client).json()

    (stored,) = repo.list_uploads("alice-uid")
    assert body == {
        "upload_id": stored.id,
        "filename": "jane.txt",
        "characters": len(stored.text),
        "pages": None,
    }
    assert "month-end close" in stored.text


def test_a_client_cannot_claim_to_be_someone_else(
    client: TestClient, repo: JsonRepository
) -> None:
    response = client.post(
        "/api/upload",
        files={"file": ("jane.txt", TEXT)},
        data={"user_id": "alice-uid"},
        headers=bearer("bob-token"),
    )

    assert [u.user_id for u in repo.list_uploads("bob-uid")] == ["bob-uid"]
    assert repo.list_uploads("alice-uid") == []
    assert response.status_code == 200


def test_uploading_does_not_run_the_agent(
    client: TestClient, runner: FakeRunner
) -> None:
    post(client)
    assert runner.calls == []


# Formats ----------------------------------------------------------------------


def test_a_pdf_is_read_with_its_page_count(
    client: TestClient, repo: JsonRepository
) -> None:
    body = post(client, "jane.pdf", make_pdf(RESUME_LINES)).json()

    assert body["pages"] == 1
    assert "billing pipeline" in repo.list_uploads("alice-uid")[0].text


def test_a_word_document_is_read(client: TestClient, repo: JsonRepository) -> None:
    data = make_docx(["Summary of a long career in data engineering at Acme."])

    assert post(client, "jane.docx", data).status_code == 200
    assert "data engineering" in repo.list_uploads("alice-uid")[0].text


def test_the_stored_filename_is_made_safe(
    client: TestClient, repo: JsonRepository
) -> None:
    post(client, "../../etc/jane.txt")
    assert repo.list_uploads("alice-uid")[0].filename == "jane.txt"


# Refusals -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("jane.exe", TEXT, "Upload a PDF"),
        ("jane.doc", TEXT, "docx or PDF"),
        ("jane.pdf", b"MZ\x90\x00" + b"\x00" * 100, "not a PDF"),
        ("jane.pdf", b"%PDF-1.4\n" + b"\x00junk\xff" * 40, "could not be read"),
        ("empty.txt", b"", "empty"),
    ],
)
def test_bad_files_get_a_plain_reason_not_an_error_page(
    client: TestClient,
    repo: JsonRepository,
    name: str,
    data: bytes,
    message: str,
) -> None:
    response = post(client, name, data)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert repo.list_uploads("alice-uid") == []


def test_a_scanned_pdf_explains_what_to_do(client: TestClient) -> None:
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    buffer = io.BytesIO()
    writer.write(buffer)

    detail = post(client, "scan.pdf", buffer.getvalue()).json()["detail"]

    assert "paste the text" in detail


def test_an_oversized_file_is_refused_with_413(
    client: TestClient, repo: JsonRepository
) -> None:
    response = post(client, "big.txt", b"x" * (doc_text.MAX_FILE_BYTES + 1))

    assert response.status_code == 413
    assert "5 MB" in response.json()["detail"]
    assert repo.list_uploads("alice-uid") == []


def test_a_request_with_no_file_is_refused(client: TestClient) -> None:
    response = client.post("/api/upload", headers=bearer("alice-token"))
    assert response.status_code == 422


# Abuse limits -------------------------------------------------------------------


def test_uploads_have_their_own_rate_limit(
    runner: FakeRunner, repo: JsonRepository
) -> None:
    client = build(runner, repo, upload_limiter=RateLimiter([(2, 60)]))
    assert post(client).status_code == 200
    assert post(client).status_code == 200

    over = post(client)

    assert over.status_code == 429
    assert int(over.headers["retry-after"]) >= 1
    assert len(repo.list_uploads("alice-uid")) == 2


def test_uploading_does_not_use_up_the_chat_allowance(
    runner: FakeRunner, repo: JsonRepository
) -> None:
    client = build(runner, repo, limiter=RateLimiter([(1, 60)]))
    post(client)
    post(client)

    chat = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
    )
    assert chat.status_code == 200


def test_one_users_uploads_do_not_use_up_anothers_limit(
    runner: FakeRunner, repo: JsonRepository
) -> None:
    client = build(runner, repo, upload_limiter=RateLimiter([(1, 60)]))
    post(client)

    assert post(client, token="bob-token").status_code == 200


def test_the_number_of_stored_uploads_is_capped(
    client: TestClient, repo: JsonRepository
) -> None:
    for i in range(server.MAX_UPLOADS_PER_USER):
        repo.save_upload(
            UploadedDocument(
                user_id="alice-uid", id=f"up-{i}", filename="x.txt", text="t" * 40
            )
        )

    response = post(client)

    assert response.status_code == 409
    assert "limit" in response.json()["detail"]
    assert len(repo.list_uploads("alice-uid")) == server.MAX_UPLOADS_PER_USER


def test_a_storage_failure_is_reported_without_details(
    runner: FakeRunner,
) -> None:
    class Broken(JsonRepository):
        def __init__(self) -> None:  # no directory needed
            pass

        def list_uploads(self, user_id: str) -> list[UploadedDocument]:
            raise StorageError("disk exploded at /srv/secret/path")

    client = build(runner, Broken())  # type: ignore[arg-type]
    response = post(client)

    assert response.status_code == 500
    assert "secret" not in response.text


# The page ---------------------------------------------------------------------------


def test_the_page_offers_an_upload_button_for_the_supported_types(
    client: TestClient,
) -> None:
    html = client.get("/").text

    assert 'id="attach"' in html
    assert 'accept=".pdf,.docx,.txt,.md"' in html
    assert "innerHTML" not in html


def test_the_page_and_server_agree_on_the_size_limit(client: TestClient) -> None:
    html = client.get("/").text
    assert f"MAX_UPLOAD_BYTES = {doc_text.MAX_FILE_BYTES // (1024 * 1024)} * 1024" in (
        html
    )

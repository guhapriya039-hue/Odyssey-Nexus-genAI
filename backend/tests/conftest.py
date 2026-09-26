"""Shared test fixtures. Environment is configured before app import."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="odyssey-test-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "ENVIRONMENT": "test",
        "LLM_ENABLED": "false",
        "OCR_ENABLED": "false",
        "SPEECH_TO_TEXT_ENABLED": "false",
        "ALLOW_WEB_INGESTION": "false",
        "EMBEDDING_PROVIDER": "local",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SAMPLE_SOURCE = """
Quarterly Threat Intelligence Report - Meridian Financial Group

Executive Summary
Meridian Financial Group observed a sustained campaign of credential-stuffing
attacks against its retail banking portal between 03 April 2026 and 28 April 2026.
The campaign generated 412,000 authentication attempts, of which 9,180 succeeded.
No evidence of lateral movement was found in the reviewed window. Contact the
SOC at soc@example.org for the full indicator set.

Key Findings
1. 61 percent of successful logins originated from three residential proxy
   networks operating in Southeast Asia.
2. The average dwell time between first failed attempt and successful login was
   4.2 minutes, indicating a scripted rather than manual operation.
3. Two compromised third-party integrations were identified as the initial
   access vector for 18 percent of the successful sessions.

Impact Assessment
Estimated exposure is 9,180 customer accounts. No card data was accessed. The
regulatory notification window under RBI guidelines is 72 hours from detection.

Recommended Actions
1. Enforce mandatory multi-factor authentication for all retail accounts.
2. Invalidate the 9,180 affected sessions and require credential reset.
3. Audit the two compromised third-party integrations and rotate their tokens.
4. Notify the compliance team so the 72-hour regulatory window can be met.

Indicators
CVE-2026-21887 was referenced in the intrusion set's tooling. Malicious domains
were observed at 45.77.201.19 and login-verify[.]cloud-access[.]net.
"""


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def analyst() -> dict[str, str]:
    return {"X-Odyssey-User": "analyst@odyssey.team", "X-Odyssey-Role": "analyst"}


@pytest.fixture(scope="session")
def approver() -> dict[str, str]:
    return {"X-Odyssey-User": "approver@odyssey.team", "X-Odyssey-Role": "approver"}


@pytest.fixture(scope="session")
def viewer() -> dict[str, str]:
    return {"X-Odyssey-User": "viewer@odyssey.team", "X-Odyssey-Role": "viewer"}


@pytest.fixture(scope="session")
def indexed_document(client: TestClient, analyst: dict[str, str]) -> dict:
    response = client.post(
        "/api/documents/text",
        headers=analyst,
        json={"title": "Meridian Threat Report", "text": SAMPLE_SOURCE},
    )
    assert response.status_code == 201, response.text
    return response.json()

import os
import tempfile

# Isolated DB + offline mode for tests (set before the app is imported).
_tmp = tempfile.mkdtemp(prefix="signalchain-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["ENABLE_EXTERNAL_APIS"] = "false"
os.environ["LLM_MODE"] = "simulated"
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c

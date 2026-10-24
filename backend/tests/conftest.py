import pytest


@pytest.fixture(autouse=True)
def _auth_cache(request, monkeypatch):
    """Unit tests run with the token cache off (each test controls its own fake gateway); real-service tests use the default."""
    from app import auth
    auth.clear_auth_cache()
    if "/real/" not in request.node.nodeid.replace("\\", "/"):
        monkeypatch.setenv("AUTH_CACHE_SECONDS", "0")
    yield
    auth.clear_auth_cache()

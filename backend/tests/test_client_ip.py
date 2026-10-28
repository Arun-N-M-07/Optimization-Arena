"""Rate limiting must key on an address the CLIENT cannot choose. X-Forwarded-For is only trusted for the entries appended by proxies
we configured (TRUSTED_PROXY_HOPS), counted from the right; everything else falls back to the TCP peer."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import middleware, settings_check
from app.config import Settings
from app.middleware import client_ip, rate_limit_settings

PEER = "203.0.113.9"


def scope(*xff, peer=PEER, client=True):
    return {"type": "http", "path": "/x", "client": (peer, 5000) if client else None,
            "headers": [(b"x-forwarded-for", v.encode()) for v in xff]}


# ---------------- client_ip ----------------
def test_by_default_every_forwarding_header_is_ignored():
    assert client_ip(scope("198.51.100.7"), 0) == PEER
    assert client_ip(scope("1.2.3.4, 5.6.7.8"), 0) == PEER


def test_one_trusted_hop_uses_the_value_the_proxy_wrote_never_what_the_client_prepended():
    assert client_ip(scope("198.51.100.7"), 1) == "198.51.100.7"                      # Vercel overwrites the header with a single address
    assert client_ip(scope("6.6.6.6, 198.51.100.7"), 1) == "198.51.100.7"             # client-supplied prefix is ignored
    assert client_ip(scope("6.6.6.6, 7.7.7.7, 198.51.100.7"), 1) == "198.51.100.7"


def test_two_trusted_hops_skip_the_inner_proxy_and_still_ignore_the_client_prefix():
    assert client_ip(scope("6.6.6.6, 198.51.100.7, 10.0.0.1"), 2) == "198.51.100.7"
    assert client_ip(scope("198.51.100.7, 10.0.0.1"), 2) == "198.51.100.7"


@pytest.mark.parametrize("hops,header", [(1, None), (2, "198.51.100.7"), (3, "1.1.1.1, 2.2.2.2")])
def test_a_header_shorter_than_the_trusted_chain_means_the_request_bypassed_it(hops, header):
    assert client_ip(scope(*([header] if header else [])), hops) == PEER


@pytest.mark.parametrize("junk", ["unknown", "<script>", "198.51.100.7:8080", "999.1.1.1", "198.51.100.7/24", "' or 1=1 --", "a" * 5000, "-"])
def test_a_value_that_is_not_an_ip_address_falls_back_to_the_peer(junk):
    assert client_ip(scope(junk), 1) == PEER and client_ip(scope(f"1.1.1.1, {junk}"), 1) == PEER


def test_repeated_headers_are_joined_in_order_and_blank_entries_ignored():
    assert client_ip(scope("6.6.6.6", "198.51.100.7"), 1) == "198.51.100.7"          # a second header line is a later hop
    assert client_ip(scope("198.51.100.7, , "), 1) == "198.51.100.7"


def test_ipv6_is_keyed_by_64_bit_prefix_and_ipv4_mapped_addresses_by_their_ipv4():
    a, b, c = (client_ip(scope(x), 1) for x in ("2001:db8:1:2::1", "2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:3::1"))
    assert a == b and a != c                                                          # rotating the low 64 bits buys nothing
    assert client_ip(scope("::ffff:198.51.100.7"), 1) == "198.51.100.7"


def test_a_missing_peer_does_not_crash():
    assert client_ip(scope(client=False), 0) == "?" and client_ip(scope(client=False), 1) == "?"


# ---------------- the middleware ----------------
def app_with(**kw):
    a = FastAPI()
    a.add_middleware(middleware.RateLimit, **kw)

    @a.get("/thing")
    def thing():
        return {"ok": 1}

    @a.get("/api/public/state")
    def public():
        return {"ok": 1}

    @a.get("/api/health")
    def health():
        return {"ok": 1}
    return a


def codes(client, path, n, **headers):
    return [client.get(path, headers=headers).status_code for _ in range(n)]


def test_spoofing_x_forwarded_for_cannot_evade_the_limit_when_no_proxy_is_trusted():
    c = TestClient(app_with(anon=5, trusted_hops=0), client=(PEER, 1))
    got = [c.get("/thing", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(10)]    # a new fake address every time
    assert got == [200] * 5 + [429] * 5


def test_rotating_the_client_controlled_prefix_does_not_help_behind_a_trusted_proxy():
    c = TestClient(app_with(anon=5, trusted_hops=1), client=("10.9.9.9", 1))
    got = [c.get("/thing", headers={"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.7"}).status_code for i in range(10)]
    assert got == [200] * 5 + [429] * 5


def test_different_real_clients_behind_the_proxy_have_separate_budgets():
    c = TestClient(app_with(anon=3, trusted_hops=1), client=("10.9.9.9", 1))
    assert codes(c, "/thing", 4, **{"X-Forwarded-For": "198.51.100.7"}) == [200, 200, 200, 429]
    assert codes(c, "/thing", 3, **{"X-Forwarded-For": "198.51.100.8"}) == [200, 200, 200]


def test_a_request_that_bypasses_the_proxy_chain_is_limited_by_its_own_peer_address():
    c = TestClient(app_with(anon=3, trusted_hops=1), client=(PEER, 1))
    assert codes(c, "/thing", 4) == [200, 200, 200, 429]                              # no header at all: keyed by the peer, not by 'unknown'


def test_public_reads_have_their_own_larger_budget_that_does_not_use_up_the_anonymous_one():
    c = TestClient(app_with(anon=3, public=10, trusted_hops=0), client=(PEER, 1))
    assert codes(c, "/api/public/state", 10) == [200] * 10
    assert c.get("/api/public/state").status_code == 429
    assert codes(c, "/thing", 4) == [200, 200, 200, 429]                              # and the reverse is also independent


def test_viewers_collapsed_onto_one_proxy_address_still_fit_the_default_public_budget():
    """If the Vercel-to-Vercel hop shows every visitor as the frontend's egress IP, a lab of viewers shares ONE key."""
    viewers, polls_per_min = 100, 2 * 6                      # state + leaderboard every 10 s
    assert viewers * polls_per_min * 2 < middleware.PUBLIC_PER_MINUTE                 # 2x headroom
    c = TestClient(app_with(public=middleware.PUBLIC_PER_MINUTE, trusted_hops=0), client=("10.9.9.9", 1))
    assert set(codes(c, "/api/public/state", 1300)) == {200}


def test_the_token_not_the_address_identifies_authenticated_callers_and_health_is_exempt():
    c = TestClient(app_with(authed=3, anon=1, trusted_hops=1), client=(PEER, 1))
    same = {"Authorization": "Bearer abc"}
    got = [c.get("/thing", headers={**same, "X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(5)]
    assert got == [200, 200, 200, 429, 429]                                           # changing the address does not reset a token's budget
    assert codes(c, "/api/health", 20) == [200] * 20


# ---------------- configuration ----------------
def test_settings_are_read_from_the_environment_and_bad_values_fall_back_safely(monkeypatch):
    for k in ("TRUSTED_PROXY_HOPS", "RATE_LIMIT_AUTHED_PER_MINUTE", "RATE_LIMIT_ANON_PER_MINUTE", "RATE_LIMIT_PUBLIC_PER_MINUTE"):
        monkeypatch.delenv(k, raising=False)
    assert rate_limit_settings() == {"authed": 600, "anon": 600, "public": 6000, "trusted_hops": 0}
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_PER_MINUTE", "9000")
    assert rate_limit_settings()["trusted_hops"] == 1 and rate_limit_settings()["public"] == 9000
    for bad in ("abc", "-1", "99", ""):
        monkeypatch.setenv("TRUSTED_PROXY_HOPS", bad)
        assert rate_limit_settings()["trusted_hops"] == 0                             # never fails open to 'trust the header'


@pytest.mark.parametrize("name,bad", [("TRUSTED_PROXY_HOPS", "abc"), ("TRUSTED_PROXY_HOPS", "-1"), ("TRUSTED_PROXY_HOPS", "6"),
                                      ("RATE_LIMIT_ANON_PER_MINUTE", "0"), ("RATE_LIMIT_PUBLIC_PER_MINUTE", "lots")])
def test_production_start_up_rejects_nonsense_limits(monkeypatch, name, bad):
    ok = Settings("https://x.supabase.co", "sb_publishable_x", "sb_secret_x", "g", "m", "postgresql://u:p@aws-0-eu.pooler.supabase.com:6543/postgres")
    monkeypatch.delenv(name, raising=False)
    assert settings_check.validate(ok) == []
    monkeypatch.setenv(name, bad)
    assert any(name in p for p in settings_check.validate(ok))
    monkeypatch.setenv(name, "1" if name == "TRUSTED_PROXY_HOPS" else "100")
    assert settings_check.validate(ok) == []


def test_the_container_image_no_longer_lets_uvicorn_trust_any_forwarded_address():
    docker = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "--forwarded-allow-ips" not in docker and "--no-proxy-headers" in docker

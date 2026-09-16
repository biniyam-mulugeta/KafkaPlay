"""OIDC role mapping, PKCE and profile extraction.

No network: these cover the logic that decides who gets which role, which is
the part with security consequences.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.auth.oidc import (
    OidcEndpoints,
    OidcError,
    PkcePair,
    authorization_url,
    map_role,
    profile_from_claims,
)
from app.config import Settings
from app.store.models import Role


def settings(**kwargs: object) -> Settings:
    base: dict[str, object] = {
        "session_secret": "x" * 48,
        "database_url": "sqlite:///:memory:",
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


class TestPkce:
    def test_challenge_is_the_sha256_of_the_verifier(self) -> None:
        pair = PkcePair.generate()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        assert pair.challenge == expected

    def test_pairs_are_unique(self) -> None:
        assert PkcePair.generate().verifier != PkcePair.generate().verifier

    def test_verifier_length_is_within_spec(self) -> None:
        # RFC 7636 requires 43-128 characters.
        verifier = PkcePair.generate().verifier
        assert 43 <= len(verifier) <= 128


class TestAuthorizationUrl:
    def endpoints(self) -> OidcEndpoints:
        return OidcEndpoints(
            authorization_endpoint="https://idp.example.org/auth",
            token_endpoint="https://idp.example.org/token",
            jwks_uri="https://idp.example.org/jwks",
        )

    def test_includes_pkce_and_state(self) -> None:
        pkce = PkcePair.generate()
        url = authorization_url(
            self.endpoints(),
            client_id="console",
            redirect_uri="https://console.example.org/callback",
            state="state123",
            nonce="nonce456",
            pkce=pkce,
        )
        assert "code_challenge_method=S256" in url
        assert f"code_challenge={pkce.challenge}" in url
        assert "state=state123" in url
        assert "nonce=nonce456" in url
        assert "response_type=code" in url

    def test_redirect_uri_is_encoded(self) -> None:
        url = authorization_url(
            self.endpoints(),
            client_id="c",
            redirect_uri="https://console.example.org/callback?x=1",
            state="s",
            nonce="n",
            pkce=PkcePair.generate(),
        )
        assert "redirect_uri=https%3A%2F%2Fconsole.example.org" in url


class TestRoleMapping:
    def config(self) -> Settings:
        return settings(
            oidc_role_claim="groups",
            oidc_admin_value="kafka-admins",
            oidc_operator_value="kafka-operators",
        )

    def test_admin_group_grants_admin(self) -> None:
        assert map_role({"groups": ["kafka-admins"]}, self.config()) is Role.ADMIN

    def test_operator_group_grants_operator(self) -> None:
        assert map_role({"groups": ["kafka-operators"]}, self.config()) is Role.OPERATOR

    def test_unknown_group_falls_back_to_viewer(self) -> None:
        """Least privilege: an unrecognised group must never escalate."""
        assert map_role({"groups": ["some-other-team"]}, self.config()) is Role.VIEWER

    def test_missing_claim_falls_back_to_viewer(self) -> None:
        assert map_role({}, self.config()) is Role.VIEWER

    def test_admin_wins_when_both_groups_are_present(self) -> None:
        claims = {"groups": ["kafka-operators", "kafka-admins"]}
        assert map_role(claims, self.config()) is Role.ADMIN

    def test_matching_is_case_insensitive(self) -> None:
        assert map_role({"groups": ["KAFKA-ADMINS"]}, self.config()) is Role.ADMIN

    def test_string_claim_is_accepted(self) -> None:
        assert map_role({"groups": "kafka-admins"}, self.config()) is Role.ADMIN

    def test_keycloak_nested_roles_are_read(self) -> None:
        claims = {"groups": {"roles": ["kafka-admins"]}}
        assert map_role(claims, self.config()) is Role.ADMIN

    def test_no_mapping_configured_means_everyone_is_a_viewer(self) -> None:
        plain = settings(oidc_role_claim="groups")
        assert map_role({"groups": ["kafka-admins"]}, plain) is Role.VIEWER


class TestProfile:
    def test_uses_the_configured_username_claim(self) -> None:
        profile = profile_from_claims(
            {"preferred_username": "alice", "sub": "123", "email": "a@example.org"},
            settings(),
        )
        assert profile.username == "alice"
        assert profile.email == "a@example.org"

    def test_falls_back_through_email_then_sub(self) -> None:
        assert profile_from_claims({"email": "b@example.org"}, settings()).username == (
            "b@example.org"
        )
        assert profile_from_claims({"sub": "xyz"}, settings()).username == "xyz"

    def test_no_usable_claim_raises(self) -> None:
        with pytest.raises(OidcError, match="username"):
            profile_from_claims({}, settings())


class TestOidcSettingsValidation:
    def test_oidc_mode_requires_issuer_and_client(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="OIDC_ISSUER_URL"):
            settings(auth_mode="oidc")

    def test_oidc_mode_accepts_a_complete_configuration(self) -> None:
        config = settings(
            auth_mode="oidc",
            oidc_issuer_url="https://idp.example.org",
            oidc_client_id="console",
            oidc_redirect_uri="https://console.example.org/callback",
        )
        assert config.oidc_client_id == "console"

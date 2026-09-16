from __future__ import annotations

import pytest

from app.auth.passwords import (
    MAX_PASSWORD_BYTES,
    PasswordError,
    hash_password,
    verify_password,
)
from app.auth.rbac import (
    ANONYMOUS_ADMIN,
    AuthorizationError,
    Principal,
    ReadOnlyError,
    require_role,
    require_writable,
)
from app.auth.sessions import SessionCodec, SessionData, csrf_matches, new_csrf_token
from app.store.models import Role

# Low cost keeps the suite fast; production uses the default 12 rounds.
FAST_ROUNDS = 4


class TestPasswords:
    def test_round_trip(self) -> None:
        digest = hash_password("a-long-enough-password", rounds=FAST_ROUNDS)
        assert verify_password("a-long-enough-password", digest)

    def test_wrong_password_fails(self) -> None:
        digest = hash_password("a-long-enough-password", rounds=FAST_ROUNDS)
        assert not verify_password("not-the-password", digest)

    def test_missing_hash_fails_without_raising(self) -> None:
        assert not verify_password("anything-at-all", None)

    def test_short_password_rejected(self) -> None:
        with pytest.raises(PasswordError, match="at least"):
            hash_password("short", rounds=FAST_ROUNDS)

    def test_overlong_password_rejected_not_truncated(self) -> None:
        # bcrypt silently ignores bytes past 72, which would make these two
        # distinct passwords interchangeable. Refuse instead.
        with pytest.raises(PasswordError, match="at most"):
            hash_password("a" * (MAX_PASSWORD_BYTES + 1), rounds=FAST_ROUNDS)

    def test_multibyte_password_measured_in_bytes(self) -> None:
        # 40 three-byte characters = 120 bytes, over the limit despite being
        # only 40 characters long.
        with pytest.raises(PasswordError, match="at most"):
            hash_password("ééé" * 40, rounds=FAST_ROUNDS)


class TestRoles:
    def test_ranking(self) -> None:
        assert Role.ADMIN.satisfies(Role.VIEWER)
        assert Role.ADMIN.satisfies(Role.OPERATOR)
        assert Role.OPERATOR.satisfies(Role.VIEWER)
        assert not Role.VIEWER.satisfies(Role.OPERATOR)
        assert not Role.OPERATOR.satisfies(Role.ADMIN)

    def test_require_role_allows_higher(self) -> None:
        require_role(Principal("a", Role.ADMIN), Role.OPERATOR)

    def test_require_role_denies_lower(self) -> None:
        with pytest.raises(AuthorizationError, match="requires the operator role"):
            require_role(Principal("v", Role.VIEWER), Role.OPERATOR)

    def test_per_cluster_override(self) -> None:
        principal = Principal("u", Role.VIEWER, cluster_roles={"staging": Role.ADMIN})
        assert principal.has_role(Role.ADMIN, "staging")
        assert not principal.has_role(Role.OPERATOR, "prod")

    def test_anonymous_admin_is_admin(self) -> None:
        assert ANONYMOUS_ADMIN.has_role(Role.ADMIN)


class TestReadOnly:
    def test_global_read_only_beats_admin(self) -> None:
        with pytest.raises(ReadOnlyError, match="read-only mode"):
            require_writable(
                Principal("root", Role.ADMIN),
                Role.OPERATOR,
                global_read_only=True,
            )

    def test_cluster_read_only_beats_admin(self) -> None:
        with pytest.raises(ReadOnlyError, match="read_only: true"):
            require_writable(
                Principal("root", Role.ADMIN),
                Role.OPERATOR,
                cluster="prod",
                global_read_only=False,
                cluster_read_only=True,
            )

    def test_writable_when_permitted(self) -> None:
        require_writable(
            Principal("op", Role.OPERATOR),
            Role.OPERATOR,
            global_read_only=False,
        )

    def test_role_still_enforced_when_writable(self) -> None:
        with pytest.raises(AuthorizationError):
            require_writable(
                Principal("v", Role.VIEWER),
                Role.OPERATOR,
                global_read_only=False,
            )


class TestSessionCodec:
    def _data(self) -> SessionData:
        return SessionData(
            username="admin", role="admin", provider="local", csrf_token=new_csrf_token()
        )

    def test_round_trip(self) -> None:
        codec = SessionCodec("s" * 48, max_age_seconds=600)
        data = self._data()
        restored = codec.loads(codec.dumps(data))
        assert restored == data

    def test_tampered_token_rejected(self) -> None:
        codec = SessionCodec("s" * 48, max_age_seconds=600)
        token = codec.dumps(self._data())
        assert codec.loads(token[:-2] + "xy") is None

    def test_different_secret_rejected(self) -> None:
        token = SessionCodec("s" * 48, max_age_seconds=600).dumps(self._data())
        assert SessionCodec("d" * 48, max_age_seconds=600).loads(token) is None

    def test_expired_token_rejected(self) -> None:
        # itsdangerous expires when age > max_age, so max_age=0 would still
        # accept a token signed in the same second. -1 expires it immediately
        # without making the test sleep.
        codec = SessionCodec("s" * 48, max_age_seconds=-1)
        token = codec.dumps(self._data())
        assert codec.loads(token) is None

    def test_garbage_rejected(self) -> None:
        assert SessionCodec("s" * 48, max_age_seconds=600).loads("not-a-token") is None


class TestCsrf:
    def test_matching(self) -> None:
        token = new_csrf_token()
        assert csrf_matches(token, token)

    def test_mismatch(self) -> None:
        assert not csrf_matches(new_csrf_token(), new_csrf_token())

    def test_absent(self) -> None:
        assert not csrf_matches(new_csrf_token(), None)
        assert not csrf_matches(new_csrf_token(), "")

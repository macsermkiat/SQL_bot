"""
Tests for authentication module.

Tests cover:
- CSV user loading
- Credential verification (success/failure)
- Role assignment (standard vs super user)
- Session token creation, decoding, expiry, and tampering
"""

import json
import tempfile
from pathlib import Path

import pytest

from app.auth import UserStore, create_session_token, decode_session_token
from app.models import UserInfo


@pytest.fixture()
def sample_csv(tmp_path: Path) -> Path:
    """Create a sample users CSV file."""
    csv_path = tmp_path / "users.csv"
    csv_path.write_text(
        "NAME,ID,Department,E-mail\n"
        "Alice Smith,12345,Cardiology,alice@hospital.org\n"
        "Bob Jones,67890,IT,bob@hospital.org\n"
        "Charlie Brown,11111,Nursing,charlie@hospital.org\n"
        "No Email,99999,Lab,\n",
        encoding="utf-8-sig",
    )
    return csv_path


@pytest.fixture()
def super_users_json(tmp_path: Path) -> Path:
    """Create a sample super users JSON file."""
    path = tmp_path / "super_users.json"
    path.write_text(
        json.dumps({"super_users": ["bob@hospital.org"]}),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def store(sample_csv: Path, super_users_json: Path) -> UserStore:
    """Create a UserStore from sample data."""
    return UserStore(csv_path=sample_csv, super_users_path=super_users_json)


class TestUserStoreLoading:
    """Test user loading from CSV."""

    def test_loads_users_from_csv(self, store: UserStore):
        assert store.user_count == 3  # 4th row has no email, skipped

    def test_skips_empty_email(self, store: UserStore):
        """Rows without email should be skipped."""
        result = store.verify("", "99999")
        assert result is None

    def test_missing_csv_does_not_crash(self, tmp_path: Path):
        """Missing CSV file should log error but not crash."""
        store = UserStore(
            csv_path=tmp_path / "nonexistent.csv",
            super_users_path=tmp_path / "nonexistent.json",
        )
        assert store.user_count == 0

    def test_email_normalized_to_lowercase(self, store: UserStore):
        """Emails should be stored lowercase."""
        result = store.verify("Alice@Hospital.ORG", "12345")
        assert result is not None
        assert result.email == "alice@hospital.org"


class TestCredentialVerification:
    """Test login verification."""

    def test_valid_credentials(self, store: UserStore):
        result = store.verify("alice@hospital.org", "12345")
        assert result is not None
        assert result.name == "Alice Smith"
        assert result.department == "Cardiology"

    def test_wrong_password(self, store: UserStore):
        result = store.verify("alice@hospital.org", "wrong")
        assert result is None

    def test_unknown_email(self, store: UserStore):
        result = store.verify("unknown@hospital.org", "12345")
        assert result is None

    def test_password_whitespace_stripped(self, store: UserStore):
        """Password should be stripped of whitespace."""
        result = store.verify("alice@hospital.org", " 12345 ")
        assert result is not None

    def test_email_whitespace_stripped(self, store: UserStore):
        result = store.verify("  alice@hospital.org  ", "12345")
        assert result is not None

    def test_case_insensitive_email(self, store: UserStore):
        result = store.verify("ALICE@HOSPITAL.ORG", "12345")
        assert result is not None


class TestRoleAssignment:
    """Test super_user vs standard_user role assignment."""

    def test_standard_user_default(self, store: UserStore):
        result = store.verify("alice@hospital.org", "12345")
        assert result is not None
        assert result.role == "standard_user"

    def test_super_user_from_config(self, store: UserStore):
        result = store.verify("bob@hospital.org", "67890")
        assert result is not None
        assert result.role == "super_user"

    def test_super_user_case_insensitive(self, store: UserStore):
        """Super user lookup should be case-insensitive."""
        result = store.verify("BOB@HOSPITAL.ORG", "67890")
        assert result is not None
        assert result.role == "super_user"

    def test_non_super_user(self, store: UserStore):
        result = store.verify("charlie@hospital.org", "11111")
        assert result is not None
        assert result.role == "standard_user"


class TestSessionToken:
    """Test session token creation and decoding."""

    def test_create_and_decode_roundtrip(self):
        user = UserInfo(
            email="test@hospital.org",
            name="Test User",
            department="IT",
            role="standard_user",
        )
        token = create_session_token(user)
        decoded = decode_session_token(token)

        assert decoded is not None
        assert decoded.email == "test@hospital.org"
        assert decoded.name == "Test User"
        assert decoded.department == "IT"
        assert decoded.role == "standard_user"

    def test_super_user_role_preserved(self):
        user = UserInfo(
            email="admin@hospital.org",
            name="Admin",
            department="IT",
            role="super_user",
        )
        token = create_session_token(user)
        decoded = decode_session_token(token)

        assert decoded is not None
        assert decoded.role == "super_user"

    def test_invalid_token_returns_none(self):
        result = decode_session_token("completely-invalid-token")
        assert result is None

    def test_tampered_token_returns_none(self):
        user = UserInfo(
            email="test@hospital.org",
            name="Test",
            department="IT",
            role="standard_user",
        )
        token = create_session_token(user)
        # Tamper with token
        tampered = token[:-5] + "XXXXX"
        result = decode_session_token(tampered)
        assert result is None

    def test_empty_token_returns_none(self):
        result = decode_session_token("")
        assert result is None


class TestSuperUsersFileEdgeCases:
    """Test edge cases in super users JSON loading."""

    def test_empty_super_users_list(self, sample_csv: Path, tmp_path: Path):
        path = tmp_path / "empty.json"
        path.write_text(json.dumps({"super_users": []}))
        store = UserStore(csv_path=sample_csv, super_users_path=path)
        result = store.verify("bob@hospital.org", "67890")
        assert result is not None
        assert result.role == "standard_user"

    def test_malformed_json(self, sample_csv: Path, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not json at all")
        store = UserStore(csv_path=sample_csv, super_users_path=path)
        # Should not crash, just no super users
        assert store.user_count == 3

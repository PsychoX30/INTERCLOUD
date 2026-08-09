"""Unit tests for billing email handling and validation."""
from portal.emails import _cc_from_user
from portal.models import UserUpdateIn
from pydantic import ValidationError


def test_cc_from_user_basic():
    """Normalize, dedupe, exclude primary."""
    user = {
        "email": "user@example.com",
        "billing_emails": ["  USER@EXAMPLE.COM  ", "bb@example.com", "BB@example.com", "cc@example.com"]
    }
    assert _cc_from_user(user) == ["bb@example.com", "cc@example.com"]


def test_cc_from_user_empty_and_none():
    """No billing emails or missing field returns empty list."""
    assert _cc_from_user({"email": "a@b.c"}) == []
    assert _cc_from_user({"email": "a@b.c", "billing_emails": None}) == []
    assert _cc_from_user({"email": "a@b.c", "billing_emails": []}) == []


def test_cc_from_user_invalid_entries_ignored():
    """Blank strings and non-strings are ignored."""
    user = {
        "email": "x@y.z",
        "billing_emails": ["", "   ", None, 123, "invalid", "a@b", "valid@test.com"]
    }
    assert _cc_from_user(user) == ["valid@test.com"]


def test_user_update_in_validates_email_str():
    """Billing emails must be valid email strings; invalid entries rejected."""
    # Valid list passes
    upd = UserUpdateIn(billing_emails=["a@b.c", "d@e.f"])
    assert upd.billing_emails == ["a@b.c", "d@e.f"]
    # Invalid email raises
    try:
        UserUpdateIn(billing_emails=["not-an-email"])
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass
    # None allowed (optional field)
    upd2 = UserUpdateIn(billing_emails=None)
    assert upd2.billing_emails is None
    # Empty list allowed
    upd3 = UserUpdateIn(billing_emails=[])
    assert upd3.billing_emails == []


def test_cc_from_user_excludes_primary_case_insensitive():
    """Primary email excluded regardless of case."""
    user = {
        "email": "Admin@Domain.CoM",
        "billing_emails": ["ADMIN@DOMAIN.COM", "billing@domain.com", "ADMIN@domain.com"]
    }
    # All variants of primary should be excluded
    assert _cc_from_user(user) == ["billing@domain.com"]


if __name__ == "__main__":
    # Allow running directly with python
    test_cc_from_user_basic()
    test_cc_from_user_empty_and_none()
    test_cc_from_user_invalid_entries_ignored()
    test_user_update_in_validates_email_str()
    test_cc_from_user_excludes_primary_case_insensitive()
    print("All tests passed")

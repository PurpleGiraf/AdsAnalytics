import pytest

from pganalytics_ingest.errors import MAX_ERROR_LENGTH, REDACTED, redact

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("401 Unauthorized: Authorization: Bearer abc.def-ghi_jkl", "abc.def-ghi_jkl"),
        ("GET /oauth?access_token=EAAB12345xyz&fields=id", "EAAB12345xyz"),
        ('{"refresh_token": "1//0gAbCdEfGhIjKlMnOp", "x": 1}', "1//0gAbCdEfGhIjKlMnOp"),
        ("client_secret='GOCSPX-abc123'", "GOCSPX-abc123"),
        ("developer_token: devtok_9988", "devtok_9988"),
        (f"token was {JWT}", JWT),
        ("google said ya29.a0AfH6SMBxyz-123_abc", "ya29.a0AfH6SMBxyz-123_abc"),
        ("refresh 1//0eXyZaBcDeFgHiJkLmNoP failed", "1//0eXyZaBcDeFgHiJkLmNoP"),
        (
            "meta: EAAGm0PX4ZCpsBAKZCZBZCxyzABCDEFGHIJKLMNOPQRSTUV123 invalid",
            "EAAGm0PX4ZCpsBAKZCZBZCxyzABCDEFGHIJKLMNOPQRSTUV123",
        ),
        ("password=hunter2", "hunter2"),
        ("{'api_key': 'sk-ant-xyz'}", "sk-ant-xyz"),
    ],
)
def test_redacts_secrets(message: str, secret: str) -> None:
    out = redact(message)
    assert secret not in out
    assert REDACTED in out


def test_keeps_useful_detail() -> None:
    message = (
        "Customer 1234567890 not found for connection "
        "3f2b8a64-1c2d-4e5f-8a9b-0c1d2e3f4a5b: USER_PERMISSION_DENIED (status 403)"
    )
    assert redact(message) == message


def test_truncates() -> None:
    out = redact("x " * MAX_ERROR_LENGTH)
    assert len(out) <= MAX_ERROR_LENGTH + len("... [truncated]")


def test_accepts_exceptions() -> None:
    assert JWT not in redact(RuntimeError(f"boom {JWT}"))

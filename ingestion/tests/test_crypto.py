import base64

import pytest
from pydantic import SecretStr

from pganalytics_ingest.crypto import CryptoError, Keyring, generate_key
from pganalytics_ingest.settings import Settings

KEY_1 = generate_key()
KEY_2 = generate_key()


def keyring(version: int = 1, **keys: str) -> Keyring:
    return Keyring.from_keys(version, {int(v[1:]): k for v, k in keys.items()})


def test_round_trip() -> None:
    ring = keyring(1, v1=KEY_1)
    blob, version = ring.encrypt("refresh-token-value")
    assert version == 1
    assert "refresh-token-value" not in blob
    assert ring.decrypt(blob, version) == "refresh-token-value"


def test_format_is_nonce_ciphertext_tag() -> None:
    blob, _ = keyring(1, v1=KEY_1).encrypt("abc")
    raw = base64.b64decode(blob)
    assert len(raw) == 12 + len("abc") + 16


def test_nonce_is_random() -> None:
    ring = keyring(1, v1=KEY_1)
    assert ring.encrypt("same")[0] != ring.encrypt("same")[0]


@pytest.mark.parametrize("position", [0, 12, -1])  # nonce, ciphertext, tag
def test_tampered_ciphertext_fails(position: int) -> None:
    ring = keyring(1, v1=KEY_1)
    blob, version = ring.encrypt("secret")
    raw = bytearray(base64.b64decode(blob))
    raw[position] ^= 0x01
    with pytest.raises(CryptoError):
        ring.decrypt(base64.b64encode(bytes(raw)).decode(), version)


def test_wrong_key_fails() -> None:
    blob, version = keyring(1, v1=KEY_1).encrypt("secret")
    with pytest.raises(CryptoError):
        keyring(1, v1=KEY_2).decrypt(blob, version)


def test_associated_data_binds_ciphertext_to_its_row() -> None:
    ring = keyring(1, v1=KEY_1)
    blob, version = ring.encrypt("secret", associated_data=b"connection-a")
    assert ring.decrypt(blob, version, associated_data=b"connection-a") == "secret"
    with pytest.raises(CryptoError):
        ring.decrypt(blob, version, associated_data=b"connection-b")
    with pytest.raises(CryptoError):
        ring.decrypt(blob, version)


def test_key_rotation_reads_old_writes_new() -> None:
    old_blob, old_version = keyring(1, v1=KEY_1).encrypt("secret")
    rotated = keyring(2, v1=KEY_1, v2=KEY_2)
    assert rotated.decrypt(old_blob, old_version) == "secret"
    assert rotated.needs_reencrypt(old_version)
    new_blob, new_version = rotated.encrypt("secret")
    assert new_version == 2
    assert not rotated.needs_reencrypt(new_version)
    with pytest.raises(CryptoError):
        keyring(1, v1=KEY_1).decrypt(new_blob, new_version)  # unknown version


def test_from_settings_with_previous_keys() -> None:
    settings = Settings(
        _env_file=None,
        pga_encryption_key=SecretStr(KEY_2),
        pga_encryption_key_version=2,
        pga_encryption_keys_previous=SecretStr(f"1:{KEY_1}"),
    )
    ring = Keyring.from_settings(settings)
    assert ring.current_version == 2 and set(ring.keys) == {1, 2}


@pytest.mark.parametrize("bad", ["not base64!!", base64.b64encode(b"short").decode()])
def test_bad_key_errors_never_include_the_key(bad: str) -> None:
    with pytest.raises(CryptoError) as info:
        Keyring.from_keys(1, {1: bad})
    assert bad not in str(info.value)


def test_keyring_repr_hides_keys() -> None:
    ring = keyring(1, v1=KEY_1)
    assert KEY_1 not in repr(ring)
    assert repr(base64.b64decode(KEY_1)) not in repr(ring)


def test_missing_key() -> None:
    with pytest.raises(CryptoError, match="PGA_ENCRYPTION_KEY"):
        Keyring.from_settings(Settings(_env_file=None, pga_encryption_key=None))

"""Web Push message encryption: RFC 8291 content coding + RFC 8188 framing.

Written out rather than pulled in as a dependency because the dependency is not
installed and the alternative -- `pywebpush` -- would be one more thing to trust with
the keys. The whole module is verifiable against the vector the RFC publishes, which is
the point: **the tests assert every intermediate value RFC 8291 Appendix A lists**, not
just "my code agrees with my code". Encrypting and then decrypting with my own
primitives would prove internal consistency and nothing else.

What is proven here: the *encryption*. What is not: that a real push service accepts
the frame, which also depends on VAPID (RFC 8292) and on a subscription from a real
browser. `relay_channels.webpush_channel` therefore stays unconfigured until it can be
tested end to end against a real subscription.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

#: RFC 8188 record size. 4096 is the value the RFC 8291 example uses and the value any
#: push service must accept; the payload limit leaves ~3993 bytes of plaintext.
RECORD_SIZE = 4096

#: A single-record message marks the end of the plaintext with this delimiter (RFC 8188
#: section 2). A receiver MUST reject anything else.
PADDING_DELIMITER = b"\x02"

KEY_INFO_PREFIX = b"WebPush: info\x00"
CEK_INFO = b"Content-Encoding: aes128gcm\x00"
NONCE_INFO = b"Content-Encoding: nonce\x00"


def b64url_encode(raw: bytes) -> str:
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Decode base64url, tolerating missing padding and embedded whitespace."""
    cleaned = "".join(str(text).split())
    return urlsafe_b64decode(cleaned + "=" * (-len(cleaned) % 4))


def hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """RFC 5869 extract: PRK = HMAC-SHA256(salt, IKM)."""
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 expand, single block is enough for every use here (<= 32 bytes)."""
    if length > hashlib.sha256().digest_size:
        raise ValueError("hkdf_expand here only supports one SHA-256 block")
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def private_key_from_b64(text: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64url_decode(text), "big"),
                                 ec.SECP256R1())


def public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    """Uncompressed X9.62 point: 65 octets starting 0x04 (RFC 8291 section 4)."""
    return key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def generate_keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def derive_ikm(ecdh_secret: bytes, auth_secret: bytes, ua_public: bytes,
               as_public: bytes) -> bytes:
    """Combine the ECDH secret with the auth secret into content-encryption IKM.

    RFC 8291 section 3.3: extract with the auth secret as salt, then expand with
    `"WebPush: info" || 0x00 || ua_public || as_public`.
    """
    prk_key = hkdf_extract(auth_secret, ecdh_secret)
    return hkdf_expand(prk_key, KEY_INFO_PREFIX + ua_public + as_public, 32)


def derive_cek_nonce(ikm: bytes, salt: bytes) -> tuple[bytes, bytes]:
    """RFC 8188 key schedule on the combined IKM, for a single record."""
    prk = hkdf_extract(salt, ikm)
    return hkdf_expand(prk, CEK_INFO, 16), hkdf_expand(prk, NONCE_INFO, 12)


def build_header(salt: bytes, *, keyid: bytes, record_size: int = RECORD_SIZE) -> bytes:
    """The `aes128gcm` header: salt || rs(4, big-endian) || idlen(1) || keyid."""
    if len(keyid) > 255:
        raise ValueError("keyid too long for a single-octet length")
    return (salt + int(record_size).to_bytes(4, "big")
            + bytes([len(keyid)]) + keyid)


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *,
            as_private: ec.EllipticCurvePrivateKey | None = None,
            salt: bytes | None = None,
            record_size: int = RECORD_SIZE) -> bytes:
    """Produce the full `aes128gcm` body: header || ciphertext || tag.

    A fresh application-server key pair and salt are generated per message unless both
    are supplied, which exists so the RFC's published vector can be reproduced exactly.
    """
    as_private = as_private or generate_keypair()
    salt = salt or os.urandom(16)
    if len(salt) != 16:
        raise ValueError("salt must be 16 octets")

    as_public = public_bytes(as_private.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = as_private.exchange(ec.ECDH(), ua_key)

    ikm = derive_ikm(ecdh_secret, auth_secret, ua_public, as_public)
    cek, nonce = derive_cek_nonce(ikm, salt)

    # One record, so the plaintext carries the end-of-record delimiter and the nonce is
    # not XORed with a sequence number: the first record's number is zero.
    record = plaintext + PADDING_DELIMITER
    if len(record) + 16 > record_size:
        raise ValueError("plaintext does not fit one record")
    ciphertext = AESGCM(cek).encrypt(nonce, record, None)
    return build_header(salt, keyid=as_public, record_size=record_size) + ciphertext


def decrypt_with_secret(body: bytes, ua_private: ec.EllipticCurvePrivateKey,
                        auth_secret: bytes) -> bytes:
    """Receiver side, used by the tests to round-trip and to prove the framing.

    The auth secret is only known to the user agent, so in production this runs in the
    browser; here it is how the tests show the body is genuinely decryptable rather than
    merely well-formed.
    """
    salt, keyid, payload = parse_body(body)
    ua_public = public_bytes(ua_private.public_key())
    as_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), keyid)
    ecdh_secret = ua_private.exchange(ec.ECDH(), as_key)
    ikm = derive_ikm(ecdh_secret, auth_secret, ua_public, keyid)
    cek, nonce = derive_cek_nonce(ikm, salt)
    record = AESGCM(cek).decrypt(nonce, payload, None)
    if not record.endswith(PADDING_DELIMITER):
        raise ValueError("bad padding delimiter")
    return record[:-1]


def parse_body(body: bytes) -> tuple[bytes, bytes, bytes]:
    if len(body) < 21:
        raise ValueError("body too short to be an aes128gcm message")
    salt = body[:16]
    record_size = int.from_bytes(body[16:20], "big")
    idlen = body[20]
    if len(body) < 21 + idlen + 16:
        raise ValueError("body too short for its keyid and tag")
    keyid = body[21:21 + idlen]
    if not keyid or keyid[0] != 0x04:
        raise ValueError("keyid is not an uncompressed P-256 point")
    return salt, keyid, body[21 + idlen:]


# ---------------------------------------------------------------------------
# VAPID (RFC 8292): the Authorization header that identifies this server to a
# push service. Separate key from the one used for key exchange -- RFC 8292
# section 3.2 requires it, and reusing one key for both is a real weakness
# rather than a style preference.
# ---------------------------------------------------------------------------

#: RFC 8292: exp must be no more than 24 hours ahead. Twelve leaves room for a
#: clock skew the push service tolerates without the token expiring mid-delivery.
VAPID_MAX_AGE = 24 * 3600
VAPID_DEFAULT_AGE = 12 * 3600


def origin_of(url: str) -> str:
    """`scheme://host[:port]` for the push resource -- the RFC's required `aud`.

    The path is deliberately dropped: the audience binds the token to a push
    *service*, and including the subscription path would mint a fresh token per
    subscription for no benefit.
    """
    parts = urlsplit(str(url))
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"not an absolute push endpoint URL: {url!r}")
    return f"{parts.scheme}://{parts.netloc}"


def public_key_from_xy(x_b64: str, y_b64: str) -> ec.EllipticCurvePublicKey:
    numbers = ec.EllipticCurvePublicNumbers(
        int.from_bytes(b64url_decode(x_b64), "big"),
        int.from_bytes(b64url_decode(y_b64), "big"),
        ec.SECP256R1())
    return numbers.public_key()


def _der_to_raw(der: bytes) -> bytes:
    """ECDSA signature DER -> the 64-octet R||S that JWS `ES256` requires.

    This is the classic VAPID bug: `cryptography` emits DER (a variable-length
    SEQUENCE, commonly 70-72 octets) while RFC 7518 requires the fixed-width
    concatenation. A push service rejects a DER signature, and nothing locally
    complains, so the failure looks like "push silently does not work".
    """
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def _raw_to_der(raw: bytes) -> bytes:
    if len(raw) != 64:
        raise ValueError(f"ES256 signature must be 64 octets, got {len(raw)}")
    return encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                int.from_bytes(raw[32:], "big"))


def _segment(obj: dict) -> str:
    """base64url of compact JSON. Compact separators and insertion order, because a
    re-serialised JWT is a different JWT."""
    return b64url_encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def build_vapid_token(endpoint: str, private_key: ec.EllipticCurvePrivateKey, *,
                      subject: str = "mailto:relay@localhost",
                      now: float | None = None,
                      age: int = VAPID_DEFAULT_AGE) -> str:
    """Sign a VAPID JWT for this push endpoint."""
    if age > VAPID_MAX_AGE:
        raise ValueError("exp must not be more than 24 hours ahead (RFC 8292)")
    issued = int(now if now is not None else time.time())
    signing_input = "{}.{}".format(
        _segment({"typ": "JWT", "alg": "ES256"}),
        _segment({"aud": origin_of(endpoint), "exp": issued + int(age),
                  "sub": subject})).encode("ascii")
    der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    return signing_input.decode("ascii") + "." + b64url_encode(_der_to_raw(der))


def vapid_authorization(endpoint: str, private_key: ec.EllipticCurvePrivateKey, *,
                        subject: str = "mailto:relay@localhost",
                        now: float | None = None) -> str:
    """The complete `Authorization` header value (RFC 8292 section 3)."""
    token = build_vapid_token(endpoint, private_key, subject=subject, now=now)
    key = b64url_encode(public_bytes(private_key.public_key()))
    return f"vapid t={token},k={key}"


def verify_vapid_token(token: str, public_key: ec.EllipticCurvePublicKey, *,
                       audience: str | None = None,
                       now: float | None = None) -> dict:
    """Verify a VAPID JWT and return its claims.

    Implemented because a verifier is the only way to check a signature against
    somebody else's artefact. Without it, "my signer works" can only ever mean "my
    signer agrees with my verifier".
    """
    try:
        head_seg, body_seg, sig_seg = token.split(".")
    except ValueError as exc:
        raise ValueError("token is not a three-part JWS") from exc
    raw = b64url_decode(sig_seg)
    public_key.verify(_raw_to_der(raw), f"{head_seg}.{body_seg}".encode("ascii"),
                      ec.ECDSA(hashes.SHA256()))
    claims = json.loads(b64url_decode(body_seg))
    if audience is not None and claims.get("aud") != audience:
        raise ValueError(f"audience mismatch: {claims.get('aud')!r}")
    exp = claims.get("exp")
    if not isinstance(exp, int):
        raise ValueError("missing or non-integer exp")
    current = now if now is not None else time.time()
    if current > exp:
        raise ValueError("token expired")
    if exp - current > VAPID_MAX_AGE:
        raise ValueError("exp is more than 24 hours ahead (RFC 8292)")
    return claims

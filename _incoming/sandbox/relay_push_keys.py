"""Windows current-account DPAPI storage for locally generated VAPID keys.
No plaintext credential files, credentials in argv, logging or ACL changes.
Only an explicitly supplied credential path is loaded; production provisioning
is a separate parent action. This is not portable across Windows accounts.
"""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    raw = ctypes.create_string_buffer(data)
    input_blob = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    if decrypt:
        fn = library.CryptUnprotectData
    else:
        fn = library.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob)):
        raise OSError('Local credential protection failed.')
    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(output_blob.data)


def provision(path):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    data = {
        'public': base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('='),
        'private': base64.urlsafe_b64encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode().rstrip('='),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = protect(json.dumps(data).encode())
    with path.open('xb') as file:
        file.write(encrypted)
    # Exercise same-account readback without returning/printing secret values.
    if load(path) != data:
        raise OSError('Local credential roundtrip failed.')
    return {'created': True, 'protected': True, 'roundtrip': True}


def load(path):
    return json.loads(protect(Path(path).read_bytes(), decrypt=True))


def apply_environment():
    path = os.environ.get('RELAY_PUSH_KEY_FILE')
    if not path:
        return
    data = load(path)
    import relay_push
    os.environ[relay_push.VAPID_PUBLIC_ENV] = data['public']
    os.environ[relay_push.VAPID_PRIVATE_ENV] = data['private']
    # A non-secret, absolute authorization deadline prevents a relaunch from
    # granting another ongoing enrollment window. Default is inactive.
    import time
    deadline = float(os.environ.get('RELAY_PUSH_ENROLL_UNTIL', '0'))
    device = os.environ.get(relay_push.DEVICE_ENV, '')
    if deadline > time.time() and device:
        os.environ[relay_push.TOKEN_ENV] = relay_push.mint_capability(device, expires_in=deadline-time.time())

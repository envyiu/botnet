import json
import base64

from nacl.signing import VerifyKey

try:
    from nacl.exceptions import BadSignature
except ImportError:
    BadSignature = Exception

from .config import MASTER_PUBLIC_KEY, REQUIRE_SIGNATURE


def verify_command(cmd_dict):
    """Xác thực chữ ký Ed25519."""
    if not REQUIRE_SIGNATURE:
        return True
    try:
        sig_b64 = cmd_dict.get("signature")
        if not sig_b64:
            return False
        sig = base64.b64decode(sig_b64)
        body = {k: v for k, v in cmd_dict.items() if k != "signature"}
        msg = json.dumps(body, sort_keys=True).encode()
        VerifyKey(bytes.fromhex(MASTER_PUBLIC_KEY)).verify(msg, sig)
        return True
    except (BadSignature, Exception):
        return False

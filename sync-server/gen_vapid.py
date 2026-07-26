"""One-time VAPID keypair generator. Run:
   docker compose run --rm parkday-sync python gen_vapid.py
Paste the two values into docker-compose.yml, then `docker compose up -d`.
Store both in 1Password."""
from py_vapid import Vapid01, b64urlencode
from cryptography.hazmat.primitives import serialization

v = Vapid01()
v.generate_keys()
priv = b64urlencode(
    v.private_key.private_numbers().private_value.to_bytes(32, "big")
)
pub = b64urlencode(
    v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
)
print("VAPID_PUBLIC_KEY:  " + pub)
print("VAPID_PRIVATE_KEY: " + priv)

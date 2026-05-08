from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class WebAppAuthError(ValueError):
    pass


def _build_data_check_string(data: dict[str, str], exclude_signature: bool = False) -> str:
    excluded = {"hash"}
    if exclude_signature:
        excluded.add("signature")
    return "\n".join(f"{key}={value}" for key, value in sorted(data.items()) if key not in excluded)


def validate_webapp_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict:
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.get("hash")
    if not received_hash:
        raise WebAppAuthError("hash is missing")

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()

    valid = False
    for exclude_signature in (False, True):
        check_string = _build_data_check_string(data, exclude_signature=exclude_signature)
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(calculated, received_hash):
            valid = True
            break

    if not valid:
        raise WebAppAuthError("invalid hash")

    auth_date = int(data.get("auth_date", "0") or "0")
    if auth_date and time.time() - auth_date > max_age_seconds:
        raise WebAppAuthError("init data expired")

    if "user" in data:
        data["user_obj"] = json.loads(data["user"])
    return data

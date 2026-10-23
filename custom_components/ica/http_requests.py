from __future__ import annotations

import json
import logging
from typing import Any

from requests import Session

_LOGGER = logging.getLogger(__name__)

# Seconds to wait for the ICA API before giving up (connect, read)
REQUEST_TIMEOUT = (10, 30)

CONTENT_TYPE = ("Content-Type", "application/json; charset=utf-8")
AUTHORIZATION = ("Authorization", "Bearer %s")
X_REQUEST_ID = ("X-Request-Id", "%s")


def create_headers(
    auth_key: str | None = None,
    with_content: bool = False,
    request_id: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}

    if auth_key:
        headers[AUTHORIZATION[0]] = AUTHORIZATION[1] % auth_key
    if with_content:
        headers[CONTENT_TYPE[0]] = CONTENT_TYPE[1]
    if request_id:
        headers[X_REQUEST_ID[0]] = X_REQUEST_ID[1] % request_id
    return headers


def get(
    session: Session,
    url: str,
    auth_key: str | None = None,
    params: dict[str, Any] | None = None,
    return_none_when_404: bool = False,
):
    _LOGGER.debug("HTTP [GET] Req: %s%s", url, f" | Params: {params}" if params else "")
    response = session.get(
        url,
        params=params,
        headers=create_headers(auth_key=auth_key),
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 200:
        _LOGGER.debug("HTTP [GET] Resp: %s", response.text[:1000])
        return response.json()
    if response.status_code == 404 and return_none_when_404:
        return None

    _raise_for_status("GET", response)
    return response.ok


def post(
    session: Session,
    url: str,
    auth_key: str | None = None,
    data: dict[str, Any] | None = None,
    json_data: Any | None = None,
):
    request_id = data.pop("request_id", None) if data else None

    headers = create_headers(
        auth_key=auth_key, with_content=bool(data), request_id=request_id
    )

    _LOGGER.debug("HTTP [POST] Req: %s", url)
    response = session.post(
        url,
        headers=headers,
        data=json.dumps(data) if data else None,
        json=json_data,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 200:
        _LOGGER.debug("HTTP [POST] Resp: %s", response.text[:1000])
        return response.json()

    _raise_for_status("POST", response)
    return response.ok


def delete(
    session: Session,
    url: str,
    auth_key: str | None = None,
    args: dict[str, Any] | None = None,
):
    request_id = args.pop("request_id", None) if args else None

    headers = create_headers(auth_key=auth_key, request_id=request_id)

    _LOGGER.debug("HTTP [DELETE] Req: %s", url)
    response = session.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)

    _raise_for_status("DELETE", response)
    return response.ok


def _raise_for_status(method: str, response) -> None:
    if response.ok:
        return
    _LOGGER.warning(
        "HTTP [%s] %s -> %s: %s",
        method,
        response.url,
        response.status_code,
        response.text[:500],
    )
    response.raise_for_status()

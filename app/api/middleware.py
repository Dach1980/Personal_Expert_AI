"""ASGI request-body limit for multipart document uploads."""

from __future__ import annotations

class _UploadBodyTooLarge(Exception):
    pass


class UploadBodyLimitMiddleware:
    """Bound multipart bytes before Starlette spools an upload to temporary storage."""

    def __init__(self, app, *, max_bytes: int, multipart_overhead: int = 2 * 1024 * 1024):
        self.app = app
        self.limit = max_bytes + multipart_overhead

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope.get("path", "").endswith("/versions")
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").lower()
        if b"multipart/form-data" not in content_type:
            await self.app(scope, receive, send)
            return

        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send)
                return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise _UploadBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _UploadBodyTooLarge:
            if not response_started:
                await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = b'{"detail":"Multipart request exceeds the configured upload limit"}'
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

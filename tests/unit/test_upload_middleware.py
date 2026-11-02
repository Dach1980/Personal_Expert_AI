import asyncio

from app.api.middleware import UploadBodyLimitMiddleware


def test_multipart_body_limit_rejects_stream_without_content_length():
    async def scenario():
        sent = []
        messages = [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"789012", "more_body": False},
        ]

        async def app(scope, receive, send):
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        middleware = UploadBodyLimitMiddleware(app, max_bytes=10, multipart_overhead=0)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/tenants/t/projects/p/documents/d/versions",
                "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 413
        assert b"exceeds" in sent[1]["body"]

    asyncio.run(scenario())


def test_multipart_body_limit_allows_small_body():
    async def scenario():
        sent = []
        messages = [{"type": "http.request", "body": b"12345", "more_body": False}]

        async def app(scope, receive, send):
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        middleware = UploadBodyLimitMiddleware(app, max_bytes=10, multipart_overhead=0)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/tenants/t/projects/p/documents/d/versions",
                "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 200

    asyncio.run(scenario())

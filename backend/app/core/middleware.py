from starlette.responses import JSONResponse


class UploadTooLarge(Exception):
    pass


class RequestGuard:
    """Bound streaming request bodies before Starlette's multipart parser sees them."""

    def __init__(self, app, max_bytes: int, allowed_origins: list[str]):
        self.app = app
        self.max_bytes = max_bytes
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode("latin1")
        unsafe = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        cross_site = headers.get(b"sec-fetch-site") == b"cross-site"
        if unsafe and ((origin and origin not in self.allowed_origins) or cross_site):
            return await JSONResponse({"detail": "Request origin is not allowed."}, 403)(
                scope, receive, send
            )
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length."}, 400)(
                scope, receive, send
            )
        if length > self.max_bytes:
            return await JSONResponse({"detail": "Upload is too large."}, 413)(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                raise UploadTooLarge
            return message

        async def private_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        try:
            await self.app(scope, bounded_receive, private_send)
        except UploadTooLarge:
            await JSONResponse({"detail": "Upload is too large."}, 413)(
                scope, receive, private_send
            )

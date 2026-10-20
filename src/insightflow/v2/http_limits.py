"""Pre-parse bounded request bodies; streaming response/disconnect semantics stay ASGI-native."""

from fastapi.responses import JSONResponse


class BodyLimit:
    def __init__(self, app, maximum=16384):
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        size = 0
        chunks = []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                return
            size += len(message.get("body", b""))
            if size > self.maximum:
                return await JSONResponse({"error": "request body too large"}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if chunks:
                return chunks.pop(0)
            return await receive()

        return await self.app(scope, replay, send)

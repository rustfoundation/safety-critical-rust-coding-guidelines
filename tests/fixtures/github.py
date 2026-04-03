class FakeGitHubResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.content = b"" if payload is None and not text else b"x"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

__all__ = ["FakeGitHubResponse"]

class Fault(Exception):
    def __init__(self, code, message=None, retryable=False):
        self.code = code
        self.message = message or code
        self.retryable = retryable
        super().__init__(self.message)

    def public(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}

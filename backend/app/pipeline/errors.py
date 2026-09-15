class PipelineError(Exception):
    """An expected failure with a message written for a non-engineer."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

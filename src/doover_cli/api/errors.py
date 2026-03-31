class ControlClientUnavailableError(RuntimeError):
    def __init__(self, command_name: str):
        self.command_name = command_name
        super().__init__(
            "This command requires pydoover.api.control, which is not available in this release."
        )

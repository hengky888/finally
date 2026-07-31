"""The single failure type for the chat pipeline."""


class LLMError(Exception):
    """The assistant could not produce a usable reply.

    Covers a missing API key, an upstream failure and a response that does not
    match the schema. The message is written for the end user and is displayed
    verbatim by the UI.
    """

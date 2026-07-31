"""The single rejection type for the service layer."""


class TradeError(Exception):
    """A requested trade or watchlist change cannot be carried out.

    The message is written for the end user and is displayed verbatim by the
    UI, so it must explain what was rejected and why.
    """

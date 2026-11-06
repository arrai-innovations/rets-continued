class RETSException(Exception):  # noqa: N818
    """The RETS Server Returned an Issue"""

    def __init__(self, reply_text=None, reply_code=None):
        super().__init__(reply_text, reply_code)
        self.reply_code = reply_code
        self.reply_text = reply_text

    def __str__(self):
        # str() must return a string, or the exception cannot even be printed in a traceback.
        if self.reply_text is not None:
            return str(self.reply_text)
        if self.reply_code is not None:
            return f"The RETS server returned reply code {self.reply_code!s}."
        return "The RETS server reported an error."


class HTTPException(Exception):  # noqa: N818
    """The RETS server refused the HTTP request, or answered it with a redirect that was not followed"""

    def __init__(self, *args, status_code=None):
        # Takes any arguments, as a plain Exception does, so code that raised it before status_code was added
        # still works. status_code is keyword-only, so it never shifts the meaning of a positional argument.
        super().__init__(*args)
        self.status_code = status_code


class NotLoggedIn(Exception):  # noqa: N818
    """Authentication Required to Access RETS server"""

    pass


class ParseError(Exception):
    """Could not successfully Parse the RETS Response"""

    pass


class MissingVersion(Exception):  # noqa: N818
    """The RETS Version is required"""

    pass


class MaxrowException(Exception):  # noqa: N818
    """
    The RETS server truncated the search results with a <MAXROWS/>. rows_returned is the number of rows the
    truncated response held.
    """

    def __init__(self, rows_returned):
        super().__init__(rows_returned)
        self.rows_returned = rows_returned

    def __str__(self):
        return f"The RETS server truncated the search response with <MAXROWS/>, after {self.rows_returned!s} rows."

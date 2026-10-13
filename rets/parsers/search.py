import io
import logging

from defusedxml.ElementTree import iterparse

from rets.exceptions import MaxrowException
from rets.exceptions import RETSException
from rets.parsers.base import Base


logger = logging.getLogger("rets")


class ResponseStream(io.RawIOBase):
    """Reads a requests response body as a file, a chunk at a time, so it never has to be held in memory whole"""

    def __init__(self, response, chunk_size=64 * 1024):
        # iter_content undoes any gzip encoding, and still works if the body has already been read.
        self._chunks = response.iter_content(chunk_size=chunk_size)
        self._buffer = b""

    def readable(self):
        return True

    def readinto(self, b):
        while not self._buffer:
            self._buffer = next(self._chunks, None)
            if self._buffer is None:
                self._buffer = b""
                return 0
        size = min(len(b), len(self._buffer))
        b[:size] = self._buffer[:size]
        self._buffer = self._buffer[size:]
        return size


class OneXSearchCursor(Base):
    """Parses Search Result Data"""

    def __init__(self):
        self.parsed_rows = 0

    def generator(self, response):
        """
        Takes a response socket connection and iteratively parses and yields the results as python dictionaries.
        :param response: a Requests response object with stream=True
        :return:
        """

        delim = "\t"  # Default to tab delimited
        columns = []
        root = None
        depth = 0
        events = iterparse(ResponseStream(response), events=("start", "end"))

        for event, elem in events:
            if event == "start":
                depth += 1
                if elem.tag == "RETS":
                    root = elem
                    self._check_reply_code(elem)
                continue
            depth -= 1

            # Analyze search record data
            if elem.tag == "DATA":
                # An empty row still counts, so that the offsets stay aligned with the rows the
                # server actually sent.
                row = elem.text or ""
                data_dict = {column: data for column, data in zip(columns, row.split(delim)) if column != ""}
                self.parsed_rows += 1  # Rows parsed with all requests
                yield data_dict

            # Analyze delimiter
            elif elem.tag == "DELIMITER":
                val = elem.get("value")
                if val:  # keep the tab default when the server sends the tag without a value
                    delim = chr(int(val))

            # Analyze columns
            elif elem.tag == "COLUMNS":
                columns = (elem.text or "").split(delim)

            # handle max rows
            elif elem.tag == "MAXROWS":
                logger.debug("MAXROWS Tag reached in XML")
                logger.debug("This search parser has parsed %s rows in all", self.parsed_rows)
                raise MaxrowException(self.parsed_rows)

            if depth == 1 and root is not None:
                # The element has been dealt with, so drop it rather than keep every row attached to the
                # root until the response ends.
                root.remove(elem)

    @staticmethod
    def _check_reply_code(elem):
        """
        Raise for a reply code that reports an error, as soon as the RETS element opens
        :param elem: The RETS element
        :return: None
        """
        reply_code = elem.get("ReplyCode")
        reply_text = elem.get("ReplyText")

        # RETS Response 20201 - No Records Found. The search simply returns nothing.
        if reply_code not in ("0", "20201"):
            msg = f"RETS Error {reply_code!s}: {reply_text!s}"
            raise RETSException(msg)

import io
import logging

from defusedxml.ElementTree import iterparse

from rets.exceptions import MaxrowException
from rets.exceptions import RETSException
from rets.parsers.base import Base
from rets.parsers.base import reply_code_error


logger = logging.getLogger("rets")


class ResponseStream(io.RawIOBase):
    """Reads a requests response body as a file, a chunk at a time, so it never has to be held in memory whole"""

    def __init__(self, response, chunk_size=64 * 1024):
        # iter_content undoes any gzip encoding, and still works if the body has already been read.
        self._chunks = response.iter_content(chunk_size=chunk_size)
        # The unread rest of the current chunk. Slicing a memoryview shares the chunk's bytes, so handing a
        # chunk out over several reads copies each byte only once, into the reader's buffer.
        self._buffer = memoryview(b"")

    def readable(self):
        return True

    def readinto(self, b):
        while not self._buffer:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._buffer = memoryview(chunk)
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
        rows = 0  # rows in this response, whatever earlier responses this parser has read
        root = None
        depth = 0
        events = iterparse(ResponseStream(response), events=("start", "end"))

        for event, elem in events:
            if event == "start":
                depth += 1
                if depth == 1:
                    root = elem
                self._check_reply_code(elem, depth)
                continue
            depth -= 1

            # Analyze search record data
            if elem.tag == "DATA":
                # An empty row still counts, so that the offsets stay aligned with the rows the
                # server actually sent.
                row = elem.text or ""
                data_dict = {column: data for column, data in zip(columns, row.split(delim)) if column != ""}
                rows += 1
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
                logger.debug("The response held %s rows before MAXROWS", rows)
                raise MaxrowException(rows)

            if depth == 1 and root is not None:
                # The element has been dealt with, so drop it rather than keep every row attached to the
                # root until the response ends.
                root.remove(elem)

    @staticmethod
    def _check_reply_code(elem, depth):
        """
        Raise for a reply code that reports an error, as soon as the element holding it opens
        :param elem: An element that has just opened
        :param depth: How deep the element is in the response, 1 for the root
        :return: None
        """
        # The reply code is on the RETS element, or on a RETS-STATUS element inside it or in its place.
        if elem.tag not in ("RETS", "RETS-STATUS") or depth > 2:
            return
        # RETS Response 20201 - No Records Found. The search simply returns nothing.
        error = reply_code_error(elem.attrib, ignore=("0", "20201"))
        if error:
            # Raised like every other reply code, so callers can tell errors apart by reply_code.
            reply_code, reply_text = error
            raise RETSException(reply_text, reply_code)

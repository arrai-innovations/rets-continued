import logging
from io import BytesIO

from defusedxml.ElementTree import iterparse

from rets.exceptions import RETSException, MaxrowException
from rets.parsers.base import Base

logger = logging.getLogger("rets")


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
        response.raw.decode_content = True
        events = iterparse(BytesIO(response.content))

        for event, elem in events:
            # Analyze search record data
            if "DATA" == elem.tag:
                data_dict = {
                    column: data
                    for column, data in zip(columns, elem.text.split(delim))
                    if column != ""
                }
                self.parsed_rows += 1  # Rows parsed with all requests
                yield data_dict

            # Handle reply code
            elif "RETS" == elem.tag:
                reply_code = elem.get("ReplyCode")
                reply_text = elem.get("ReplyText")

                if reply_code == "20201":
                    # RETS Response 20201 - No Records Found
                    # Generator should continue and return nothing
                    continue
                elif reply_code != "0":
                    msg = f"RETS Error {reply_code!s}: {reply_text!s}"
                    raise RETSException(msg)

            # Analyze delimiter
            elif "DELIMITER" == elem.tag:
                val = elem.get("value")
                delim = chr(int(val))

            # Analyze columns
            elif "COLUMNS" == elem.tag:
                columns = elem.text.split(delim)

            # handle max rows
            elif "MAXROWS" == elem.tag:
                logger.debug("MAXROWS Tag reached in XML")
                logger.debug("Received %(self.parsed_rows)s results from this search")
                raise MaxrowException(self.parsed_rows)

            else:
                # This is a tag we don't process (like COUNT)
                continue

            elem.clear()

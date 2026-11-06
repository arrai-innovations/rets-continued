import logging

import xmltodict

from rets.exceptions import RETSException


logger = logging.getLogger("rets")

NO_REPLY_TEXT = "RETS did not supply a Reply Text."


def reply_code_error(attributes, ignore=("0",)):
    """
    Reads the reply code from the attributes of a RETS or RETS-STATUS element. Every reader of reply codes goes
    through here, so they agree on what counts as an error.
    :param attributes: The element's attributes, as a dict keyed by attribute name
    :param ignore: The reply codes that do not report an error
    :return: The (reply_code, reply_text) of an error reply code, or None
    """
    reply_code = attributes.get("ReplyCode")
    if reply_code is None:
        return None
    reply_text = attributes.get("ReplyText", NO_REPLY_TEXT)
    logger.debug("Received ReplyCode of %s from the RETS Server: %s", reply_code, reply_text)
    if reply_code in ignore:
        return None
    return reply_code, reply_text


class Base:
    """Base Parser Object"""

    @staticmethod
    def get_attributes(input_dict):
        """
        Get attributes of xml tags in input_dict and creates a dictionary with the attribute name as the key and the
        attribute value as the value
        :param input_dict: The xml tag with the attributes and values
        :return: dict
        """
        return {k.lstrip("@"): v for k, v in input_dict.items() if k[0] == "@"}

    @staticmethod
    def data_columns_to_dict(columns_string, dict_string, delimiter=None):
        """
        Turns column names in a single string into a dictionary with the key being the column name and the value
        being the value in that column for each row
        :param columns_string: A string of column names
        :param dict_string: A string of values
        :param delimiter: The delimiter to use to split the column and values
        :return: dict
        """
        if delimiter:
            # COMPACT lines open and close with the delimiter, which leaves an unnamed column at each end.
            return {k: v for k, v in zip(columns_string.split(delimiter), dict_string.split(delimiter)) if k != ""}
        else:
            return {k: v for k, v in zip(columns_string.split(), dict_string.split())}  # noqa: C416

    def analyze_xml_response(self, response):
        """
        Checks the reply code of a response that came back as XML, which is how servers report an error in place
        of the content asked for. A response of any other type is left for the caller to parse.
        :param response: The response from the RETS server
        :return: None
        """
        if "xml" in response.headers.get("Content-Type", ""):
            self.analyze_reply_code(xml_response_dict=xmltodict.parse(response.text))

    def analyze_reply_code(self, xml_response_dict):
        """
        Checks the RETS reply code, on the RETS element and on a RETS-STATUS element inside it, or on a RETS-STATUS
        element sent as the whole response, and raises RETSException for an error
        :param xml_response_dict: The response, as parsed by xmltodict
        :return: None
        """
        if "RETS-STATUS" in xml_response_dict:
            statuses = [xml_response_dict["RETS-STATUS"]]
        elif "RETS" in xml_response_dict:
            rets = xml_response_dict["RETS"]
            statuses = [rets, rets.get("RETS-STATUS")] if isinstance(rets, dict) else []
        else:  # pragma: no cover
            raise RETSException("The <RETS> tag was expected in the response XML but it was not found.")

        for status in statuses:
            # xmltodict gives an element with no attributes as None or its text, so it has no reply code.
            error = reply_code_error(self.get_attributes(status)) if isinstance(status, dict) else None
            if error:
                reply_code, reply_text = error
                raise RETSException(reply_text, reply_code)

import logging

import xmltodict

from rets.exceptions import RETSException


logger = logging.getLogger("rets")

NO_REPLY_TEXT = "RETS did not supply a Reply Text."

# Where a response carries its RETS reply code, as the names of the elements leading to it from the document root:
# the RETS element, a RETS-STATUS element inside it, or a RETS-STATUS element sent as the whole response. Every
# reader of reply codes looks in these places, in this order, so they agree on where an error is reported.
REPLY_CODE_PATHS = (("RETS",), ("RETS", "RETS-STATUS"), ("RETS-STATUS",))


# The media types a RETS server sends an XML reply as, such as an error in place of the object asked for. A type
# that only ends in "+xml", such as an SVG image, is content.
XML_REPLY_MEDIA_TYPES = frozenset(("text/xml", "application/xml"))


def is_xml_reply(content_type):
    """
    Whether a Content-Type is that of an XML reply, whatever its parameters, such as a charset, or its case
    :param content_type: The Content-Type header's value, or None
    :return: bool
    """
    return (content_type or "").split(";", 1)[0].strip().lower() in XML_REPLY_MEDIA_TYPES


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


def reply_code_error_in_document(document, ignore=("0",)):
    """
    Finds the first error reply code in a response parsed by xmltodict
    :param document: The response, as parsed by xmltodict
    :param ignore: The reply codes that do not report an error
    :return: The (reply_code, reply_text) of an error reply code, or None
    """
    for path in REPLY_CODE_PATHS:
        elements = [document]
        for name in path:
            # xmltodict gives a repeated element as a list, and one with no attributes as None or its text.
            children = (element.get(name) for element in elements if isinstance(element, dict))
            elements = [child for value in children for child in (value if isinstance(value, list) else [value])]
        for element in elements:
            error = reply_code_error(Base.get_attributes(element), ignore) if isinstance(element, dict) else None
            if error:
                return error
    return None


def local_name(tag):
    """
    Get an element's name without its namespace. ElementTree names an element in a namespace "{uri}RETS", where
    xmltodict names one in a default namespace just "RETS".
    :param tag: The element's tag, as ElementTree gives it
    :return: string
    """
    return tag.rpartition("}")[2]


def reply_code_error_in_tree(root, ignore=("0",)):
    """
    Finds the first error reply code in a response parsed by ElementTree
    :param root: The response's root element
    :param ignore: The reply codes that do not report an error
    :return: The (reply_code, reply_text) of an error reply code, or None
    """
    for root_name, *names in REPLY_CODE_PATHS:
        if local_name(root.tag) != root_name:
            continue
        elements = [root]
        for name in names:
            elements = [child for parent in elements for child in parent if local_name(child.tag) == name]
        for element in elements:
            error = reply_code_error(element.attrib, ignore)
            if error:
                return error
    return None


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
        :param delimiter: The delimiter to use to split the column and values, or None to split on whitespace
        :return: dict
        """
        delimiter = delimiter or None  # str.split(None) splits on runs of whitespace
        return Base._columns_to_dict(columns_string.split(delimiter), dict_string.split(delimiter))

    @staticmethod
    def _columns_to_dict(columns, values):
        """
        Pairs each column name with the value in its place, as the COMPACT formats lay out a row. Every row of a
        COMPACT response goes through here, for search results and metadata alike.
        :param columns: The column names, already split
        :param values: The row's values, already split
        :return: dict
        """
        # COMPACT lines open and close with the delimiter, which leaves an unnamed column at each end.
        return {column: value for column, value in zip(columns, values) if column != ""}

    def analyze_xml_response(self, response):
        """
        Checks the reply code of a response that came back as XML, which is how servers report an error in place
        of the content asked for. A response of any other type is left for the caller to parse.
        :param response: The response from the RETS server
        :return: None
        """
        if is_xml_reply(response.headers.get("Content-Type")):
            self.analyze_reply_code(xml_response_dict=xmltodict.parse(response.text))

    def analyze_reply_code(self, xml_response_dict):
        """
        Checks the RETS reply code, on the RETS element and on a RETS-STATUS element inside it, or on a RETS-STATUS
        element sent as the whole response, and raises RETSException for an error
        :param xml_response_dict: The response, as parsed by xmltodict
        :return: None
        """
        if not any(path[0] in xml_response_dict for path in REPLY_CODE_PATHS):  # pragma: no cover
            raise RETSException("The <RETS> tag was expected in the response XML but it was not found.")

        error = reply_code_error_in_document(xml_response_dict)
        if error:
            reply_code, reply_text = error
            raise RETSException(reply_text, reply_code)

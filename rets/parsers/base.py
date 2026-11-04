import logging

import xmltodict

from rets.exceptions import RETSException


logger = logging.getLogger("rets")


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
        Checks the RETS Response Code and handles non-zero answers.
        :param xml_response_dict:
        :return: None
        """
        if "RETS-STATUS" in xml_response_dict:
            attributes = self.get_attributes(xml_response_dict["RETS-STATUS"])
            reply_code = attributes["ReplyCode"]
            reply_text = attributes.get("ReplyText", "RETS did not supply a Reply Text.")

            logger.debug("Received ReplyCode of %s from the RETS Server: %s", reply_code, reply_text)
            if reply_code != "0":
                raise RETSException(reply_text, reply_code)

        elif "RETS" not in xml_response_dict:  # pragma: no cover
            raise RETSException("The <RETS> tag was expected in the response XML but it was not found.")

        attributes = self.get_attributes(input_dict=xml_response_dict["RETS"])
        if "ReplyCode" not in attributes:  # pragma: no cover
            # The RETS server did not return a response code.
            return True

        reply_code = attributes["ReplyCode"]
        reply_text = attributes.get("ReplyText", "RETS did not supply a Reply Text.")

        logger.debug("Received ReplyCode of %s from the RETS Server: %s", reply_code, reply_text)
        if reply_code != "0":
            raise RETSException(reply_text, reply_code)

import hashlib
import re

import xmltodict

from rets.exceptions import ParseError
from rets.exceptions import RETSException
from rets.parsers.base import Base


LINE_BREAK = re.compile(r"\r?\n")
HEADER_END = re.compile(r"\r?\n\r?\n")


class ObjectParser(Base):
    @staticmethod
    def _response_object_from_header(obj_head_dict, content=None):
        obj = {}
        obj["content_description"] = obj_head_dict.get("Content-Description")
        obj["content_sub_description"] = obj_head_dict.get("Content-Sub-Description")
        obj["content_id"] = obj_head_dict.get("Content-ID")
        obj["object_id"] = obj_head_dict.get("Object-ID")
        obj["content_type"] = obj_head_dict.get("Content-Type")
        obj["location"] = obj_head_dict.get("Location")
        obj["mime_version"] = obj_head_dict.get("MIME-Version")
        obj["preferred"] = obj_head_dict.get("Preferred")

        if content:
            md = hashlib.md5()  # noqa: S324
            md.update(content)
            obj["content"] = content
            obj["content_md5"] = md.hexdigest()
        else:
            obj["content"] = content
            obj["content_md5"] = None
        return obj


class MultipleObjectParser(ObjectParser):
    """Parses multiple object responses such as multiple images in a multi-part response"""

    @staticmethod
    def _get_multiparts(response):
        """
        From this
        'multipart/parallel; boundary="874e43d27ec6d83f30f37841bdaf90c7"; charset=utf-8'
        get this
        --874e43d27ec6d83f30f37841bdaf90c7
        """
        boundary = None
        for part in response.headers.get("Content-Type", "").split(";"):
            if "boundary=" in part:
                boundary = "--{}".format(part.split("=", 1)[1].strip('"'))
                break

        if not boundary:
            raise ParseError("Was not able to find the boundary between objects in a multipart response")

        if response.content is None:
            return

        # Decode for string operations. latin-1 maps each byte to one character, so encoding a part
        # back gives exactly the bytes the server sent.
        response_string = response.content.decode("latin-1")

        for part in response_string.split(boundary):
            if part.startswith("--"):
                break  # The close delimiter. Anything after it is epilogue.

            # The delimiter line ends in a line break, and the line break ahead of the next delimiter belongs to
            # that delimiter (RFC 2046). Remove exactly one of each, since a binary body can itself end in CR or
            # LF bytes. Some servers send bare LFs rather than CRLFs.
            part = part.removeprefix("\r\n") if part.startswith("\r\n") else part.removeprefix("\n")
            part = part.removesuffix("\r\n") if part.endswith("\r\n") else part.removesuffix("\n")

            # Skip the empty preamble before the first delimiter. A server that leaves out the first
            # delimiter still has its first part read.
            if part.strip():
                yield part

    def parse_image_response(self, response):
        """
        Parse multiple objects from the RETS feed. A lot of string methods are used to handle the response before
        encoding it back into bytes for the object.
        :param response: The response from the feed
        :return: list of SingleObjectParser
        """
        if "xml" in response.headers.get("Content-Type", ""):
            # Got an XML response, likely an error code.
            xml = xmltodict.parse(response.text)
            self.analyze_reply_code(xml_response_dict=xml)

        multi_parts = self._get_multiparts(response)

        # go through each part of the multipart message
        for part in multi_parts:
            # The headers end at the first blank line, whichever line endings the server uses.
            if HEADER_END.search(part):
                header, body = HEADER_END.split(part, maxsplit=1)
            else:
                header = part
                body = None
            part_header_dict = {
                k.strip(): v.strip() for k, v in (h.split(":", 1) for h in LINE_BREAK.split(header) if ":" in h)
            }

            # Some multipart requests respond with a text/XML part stating an error
            if "xml" in part_header_dict.get("Content-Type", ""):
                # Got an XML response, likely an error code.
                # Some rets servers give characters after the closing brace.
                if not body:
                    raise ParseError("Got an XML part in a multipart response, but it has no body")
                body = body[: body.index("/>") + 2] if "/>" in body else body
                xml = xmltodict.parse(body)
                try:
                    self.analyze_reply_code(xml_response_dict=xml)
                except RETSException as e:
                    if e.reply_code == "20403":
                        # The requested object_id was not found.
                        continue
                    raise e

            if body:
                obj = self._response_object_from_header(
                    obj_head_dict=part_header_dict,
                    content=body.encode("latin-1"),
                )
            else:
                obj = self._response_object_from_header(obj_head_dict=part_header_dict)

            yield obj


class SingleObjectParser(ObjectParser):
    def parse_image_response(self, response):
        """
        Parse a single object from the RETS feed
        :param response: The response from the RETS server
        :return: Object
        """
        if "xml" in response.headers.get("Content-Type", ""):
            # Got an XML response, likely an error code.
            xml = xmltodict.parse(response.text)
            self.analyze_reply_code(xml_response_dict=xml)

        obj = self._response_object_from_header(obj_head_dict=response.headers, content=response.content)
        yield obj

import hashlib
import re

import xmltodict
from requests.structures import CaseInsensitiveDict

from rets.exceptions import ParseError
from rets.exceptions import RETSException
from rets.parsers.base import Base


LINE_BREAK = re.compile(r"\r?\n")
HEADER_END = re.compile(rb"\r?\n\r?\n")
# The start of an element, which skips an XML declaration, a comment or a closing tag.
ELEMENT_START = re.compile(rb"<([A-Za-z_][\w.:-]*)")
# A byte that is not whitespace once decoded as latin-1. A part holding none of them is empty.
NOT_WHITESPACE = re.compile(rb"[^\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0]")
# RETS requires each part of a multipart GetObject response to carry these, so text ahead of the first
# delimiter with none of them is a preamble rather than a part.
PART_HEADERS = frozenset(("content-id", "object-id", "content-type"))


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
    def _split_part(content, start, end):
        """
        Split a part of a multipart response into its headers and body
        :param content: The whole response body
        :param start: Where the part starts in content
        :param end: Where the part ends in content
        :return: tuple of the headers as a dict keyed case-insensitively, and the body as bytes, or None if the
        part has none
        """
        # The headers end at the first blank line, whichever line endings the server uses. Only the body is
        # copied out of the response, once, rather than the whole part at each step.
        header_end = HEADER_END.search(content, start, end)
        if header_end:
            header = content[start : header_end.start()]
            body = content[header_end.end() : end]
        else:
            header = content[start:end]
            body = None
        lines = LINE_BREAK.split(header.decode("latin-1"))
        # Header names are case-insensitive (RFC 2045), as they are in the response's own headers.
        headers = CaseInsensitiveDict((k.strip(), v.strip()) for k, v in (h.split(":", 1) for h in lines if ":" in h))
        return headers, body

    @classmethod
    def _get_multiparts(cls, response):
        """
        Split a multipart response into its parts, finding the delimiter from the boundary in the Content-Type:
        'multipart/parallel; boundary="874e43d27ec6d83f30f37841bdaf90c7"; charset=utf-8' is delimited by
        --874e43d27ec6d83f30f37841bdaf90c7
        :param response: The response from the RETS server
        :return: generator of tuples of each part's headers as a dict, and its body as bytes or None
        """
        boundary = None
        for part in response.headers.get("Content-Type", "").split(";"):
            if "boundary=" in part:
                boundary = "--{}".format(part.split("=", 1)[1].strip('"'))
                break

        if not boundary:
            raise ParseError("Was not able to find the boundary between objects in a multipart response")

        content = response.content
        if content is None:
            return

        # Work on the response's bytes by position, so that a large object is not copied at every step.
        delimiter = boundary.encode("latin-1")
        start = 0
        first = True
        while True:
            found = content.find(delimiter, start)
            end = len(content) if found == -1 else found

            # The delimiter line ends in a line break, and the line break ahead of the next delimiter belongs to
            # that delimiter (RFC 2046). Remove exactly one of each, since a binary body can itself end in CR or
            # LF bytes. Some servers send bare LFs rather than CRLFs.
            start += 2 if content.startswith(b"\r\n", start, end) else int(content.startswith(b"\n", start, end))
            end -= 2 if content.endswith(b"\r\n", start, end) else int(content.endswith(b"\n", start, end))

            if NOT_WHITESPACE.search(content, start, end):
                headers, body = cls._split_part(content, start, end)
                # Text ahead of the first delimiter is a preamble, which MIME allows and readers ignore. A
                # server that leaves out the first delimiter still has its first part read, since that has
                # the headers a part needs.
                if not first or any(name in headers for name in PART_HEADERS):
                    yield headers, body

            if found == -1:
                return
            start = found + len(delimiter)
            if content.startswith(b"--", start):
                return  # The close delimiter. Anything after it is epilogue.
            first = False

    @staticmethod
    def _root_element(body):
        """
        Cut an XML part down to its root element. Some RETS servers send characters after it, which would
        otherwise fail the parse.
        :param body: The XML part's body
        :return: bytes
        """
        root = ELEMENT_START.search(body)
        if not root:
            return body
        name = root.group(1)
        start_tag_end = body.find(b">", root.end())
        if start_tag_end != -1 and body[start_tag_end - 1 : start_tag_end] == b"/":
            # The root closes itself, as <RETS ReplyCode="20403"/> does.
            return body[: start_tag_end + 1]
        # Otherwise it ends at its closing tag, after any children such as a RETS-STATUS.
        closing_tag = b"</" + name + b">"
        close = body.find(closing_tag, root.end())
        return body if close == -1 else body[: close + len(closing_tag)]

    def parse_image_response(self, response):
        """
        Parse multiple objects from the RETS feed
        :param response: The response from the feed
        :return: generator of objects
        """
        self.analyze_xml_response(response)

        # go through each part of the multipart message
        for part_header_dict, body in self._get_multiparts(response):
            # Some multipart requests respond with a text/XML part stating an error
            if "xml" in part_header_dict.get("Content-Type", ""):
                # Got an XML response, likely an error code.
                if not body:
                    raise ParseError("Got an XML part in a multipart response, but it has no body")
                # Decoded as latin-1, as before, so a reply text in another encoding still parses.
                xml = xmltodict.parse(self._root_element(body).decode("latin-1"))
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
                    content=body,
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
        self.analyze_xml_response(response)

        obj = self._response_object_from_header(obj_head_dict=response.headers, content=response.content)
        yield obj

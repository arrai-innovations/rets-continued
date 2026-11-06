import logging

import xmltodict

from rets.exceptions import ParseError

from .base import Base


logger = logging.getLogger("rets")


class MetadataParser(Base):
    """What the metadata parsers share: how a wildcard result is keyed, so it has the same shape in each format"""

    # For each metadata type: the attribute each part of its ID names, in order. A wildcard result is keyed by
    # the attributes whose part of the ID is a "*".
    id_attributes = {  # noqa: RUF012
        "METADATA-CLASS": ("Resource",),
        "METADATA-RESOURCE": (),
        "METADATA-LOOKUP_TYPE": ("Resource", "Lookup"),
        "METADATA-OBJECT": ("Resource",),
        "METADATA-TABLE": ("Resource", "Class"),
    }

    @staticmethod
    def _child(element, name):
        """
        Get a child element that can only hold other elements, such as RETS or METADATA
        :param element: The parent element, as parsed by xmltodict
        :param name: The child element's name
        :return: dict, empty when the child is missing, or has no attributes or children, which xmltodict gives
        as None or as the child's text
        """
        child = element.get(name) if isinstance(element, dict) else None
        return child if isinstance(child, dict) else {}

    def _wildcard_attributes(self, metadata_type, meta_id, wildcard):
        """
        Get the attributes a wildcard result is keyed by, outermost first
        :param metadata_type: string
        :param meta_id: The ID the metadata was requested with, or None
        :param wildcard: Whether to treat the last part of the ID as a wildcard, when meta_id is None
        :return: tuple of attribute names, empty for a request without a wildcard
        """
        attributes = self.id_attributes.get(metadata_type, ())
        if meta_id is None:
            return attributes[-1:] if wildcard else ()
        return tuple(attribute for part, attribute in zip(str(meta_id).split(":"), attributes) if part == "*")

    @staticmethod
    def _group_by_names(named_entries, metadata_type, key_by):
        """
        Groups the entries of each metadata element into a dict of lists, keyed by the names the element covers.
        With more than one attribute to key by, the dict is nested, outermost attribute first.
        :param named_entries: For each metadata element, a tuple of its attributes as a dict and its entries
        :param metadata_type: string
        :param key_by: The attributes naming each element, outermost first
        :return: dict
        """
        res = {}
        for attributes, entries in named_entries:
            names = [attributes.get(attribute) for attribute in key_by]
            if None in names:
                if not entries:
                    # Names nothing and holds nothing, so there is nothing to lose by passing over it.
                    continue
                msg = f"A {metadata_type!s} element is missing its {key_by[names.index(None)]!s} attribute"
                raise ParseError(msg)

            level = res
            for name in names[:-1]:
                level = level.setdefault(name, {})
            if names[-1] in level:
                # Two elements for the same names; refuse rather than lose either one's entries.
                described = ", ".join(f"{attribute!s} {name!s}" for attribute, name in zip(key_by, names))
                msg = f"Got more than one {metadata_type!s} element for {described}"
                raise ParseError(msg)
            level[names[-1]] = entries
        return res


class CompactMetadata(MetadataParser):
    """Parses COMPCACT-DECODED RETS responses"""

    def parse(self, response, metadata_type, meta_id=None, wildcard=False):
        """
        Parses RETS metadata using the COMPACT-DECODED format
        :param response: requests Response object
        :param metadata_type: string
        :param meta_id: The ID the metadata was requested with, such as "Property:*". A "*" in place of a part
        gets a dict back, keyed as the STANDARD-XML parser keys it.
        :param wildcard: For a caller without the ID: treat it as a wildcard in the last part, such as
        "Property:*". Ignored when meta_id is given.
        :return: list of the rows, each carrying the attributes of its metadata element, or a dict of lists of
        them for a wildcard request
        """
        # Keep the whitespace around element text. A COMPACT row is tab delimited, so stripping
        # it would drop empty fields from either end and shift every value after them.
        xml = xmltodict.parse(response.text, strip_whitespace=False)
        self.analyze_reply_code(xml_response_dict=xml)
        base = self._child(xml, "RETS").get(metadata_type, {})

        # xmltodict returns a list when the metadata element repeats, as it does for a wildcard lookup. An element
        # with no attributes and no children holds no entries: xmltodict gives a bare one as None, and, since
        # whitespace is kept, one holding only a line break as that text.
        elements = [element for element in (base if isinstance(base, list) else [base]) if isinstance(element, dict)]

        key_by = self._wildcard_attributes(metadata_type, meta_id, wildcard)
        if key_by:
            # Grouped per element rather than per row, so a name with no rows still maps to an empty list.
            named_entries = ((self.get_attributes(element), list(self._parse_element(element))) for element in elements)
            return self._group_by_names(named_entries, metadata_type, key_by)
        return [row for element in elements for row in self._parse_element(element)]

    def _parse_element(self, base):
        """
        Parses a single COMPACT-DECODED metadata element
        :param base: The metadata element, as parsed by xmltodict
        :return:
        """
        attributes = self.get_attributes(base)

        system = base.get("SYSTEM", base.get("System"))
        if system:
            yield self._parse_system(base, system)

        elif "DATA" in base:
            if not isinstance(base["DATA"], list):  # xmltodict could take single entry XML lists and turn them into str
                base["DATA"] = [base["DATA"]]

            for data in base["DATA"]:
                data_dict = self.data_columns_to_dict(
                    columns_string=base.get("COLUMNS") or "",
                    dict_string=data or "",
                    delimiter="\t",
                )
                data_dict.update(attributes)

                yield data_dict

    @staticmethod
    def _parse_system(base, system):
        """
        Parses the SYSTEM element of a COMPACT-DECODED METADATA-SYSTEM response
        :param base: The METADATA-SYSTEM element, as parsed by xmltodict
        :param system: The SYSTEM element within it
        :return: dict
        """
        system_obj = {}

        if system.get("@SystemID"):
            system_obj["system_id"] = str(system["@SystemID"])

        if system.get("@SystemDescription"):
            system_obj["system_description"] = str(system["@SystemDescription"])

        if system.get("@TimeZoneOffset"):
            system_obj["timezone_offset"] = str(system["@TimeZoneOffset"])

        # The comments belong in a COMMENTS element alongside SYSTEM, but some servers
        # nest them inside it instead.
        comments = base.get("COMMENTS") or base.get("Comments") or system.get("Comments")
        if isinstance(comments, str):
            comments = comments.strip()
        if comments:
            system_obj["comments"] = comments

        if base.get("@Version"):
            system_obj["version"] = base["@Version"]

        return system_obj


class StandardXMLMetadata(MetadataParser):
    """Parses STANDARD-XML RETS responses"""

    # For each metadata type: the child element holding its entries, matched case-insensitively.
    element_keys = {  # noqa: RUF012
        "METADATA-CLASS": "class",
        "METADATA-RESOURCE": "resource",
        "METADATA-LOOKUP_TYPE": "lookuptype",
        "METADATA-OBJECT": "object",
        "METADATA-TABLE": "field",
    }

    @staticmethod
    def _identify_key(some_dict, some_key):
        # Get the version with the right capitalization from the dictionary
        key_cap = None
        for k in some_dict.keys():  # noqa: SIM118
            if k.lower() == some_key:
                key_cap = k
            # Some servers don't index lookup correctly for the given RETS version; let's address that here
            elif some_key == "lookuptype":  # noqa: SIM102
                if k.lower() == "lookup":
                    key_cap = k

        if not key_cap:
            msg = f"Could not find {some_key!s} in the response XML"
            raise ParseError(msg)
        return key_cap

    def parse(self, response, metadata_type, meta_id=None, wildcard=False):
        """
        Parses RETS metadata using the STANDARD-XML format
        :param response: requests Response object
        :param metadata_type: string
        :param meta_id: The ID the metadata was requested with, such as "Property:*". A "*" in place of a part
        gets a dict back, even when it matched a single name, keyed by the attribute that part names: "*:Status"
        is keyed by resource, and "Property:*" by lookup. A "*" in both parts gets a dict of dicts, keyed by
        resource and then by lookup or class.
        :param wildcard: For a caller without the ID: treat it as a wildcard in the last part, such as
        "Property:*". Ignored when meta_id is given.
        :return parsed: list, or a dict of lists for a wildcard request or when the response holds several
        metadata elements
        """
        xml = xmltodict.parse(response.text)
        self.analyze_reply_code(xml_response_dict=xml)
        metadata = self._child(self._child(xml, "RETS"), "METADATA")

        if metadata_type == "METADATA-SYSTEM":
            return [self._parse_system(metadata.get(metadata_type) or {})]

        if metadata_type not in self.element_keys:
            msg = f"Got an unknown metadata type of {metadata_type!s}"
            raise ParseError(msg)

        key_by = self._wildcard_attributes(metadata_type, meta_id, wildcard)
        if metadata_type not in metadata:
            if key_by:
                # The wildcard matched nothing.
                return {}
            msg = f"The response holds no {metadata_type!s} element"
            raise ParseError(msg)

        base = metadata[metadata_type]
        if isinstance(base, list) and not key_by:
            # Several elements came back for an ID without a wildcard, so tell them apart by the name each covers.
            key_by = self.id_attributes[metadata_type][-1:]
            if not key_by:
                msg = f"Got more than one {metadata_type!s} element, but there is nothing to tell them apart by"
                raise ParseError(msg)
        if key_by:
            # A wildcard request gets a dict even if it matched a single name, so that its result has the same
            # type however many names the server has.
            named_entries = (
                (
                    self.get_attributes(element) if isinstance(element, dict) else {},
                    self._entries(element, metadata_type),
                )
                for element in (base if isinstance(base, list) else [base])
            )
            return self._group_by_names(named_entries, metadata_type, key_by)

        return self._entries(base, metadata_type)

    @staticmethod
    def _parse_system(base):
        """
        Parses the METADATA-SYSTEM element
        :param base: The METADATA-SYSTEM element, as parsed by xmltodict
        :return: dict
        """
        syst = base.get("System", base.get("SYSTEM"))
        if not syst:
            raise ParseError("Could not get the System key from a METADATA-SYSTEM request.")

        system_obj = {}
        if syst.get("SystemID"):
            system_obj["system_id"] = str(syst["SystemID"])
        if syst.get("SystemDescription"):
            system_obj["system_description"] = str(syst["SystemDescription"])
        if syst.get("Comments"):
            system_obj["comments"] = syst["Comments"]
        if base.get("@Version"):
            system_obj["version"] = base["@Version"]
        return system_obj

    def _entries(self, element, metadata_type):
        """
        Get the entries of one metadata element as a list
        :param element: The metadata element, as parsed by xmltodict
        :param metadata_type: string
        :return: list
        """
        if not isinstance(element, dict):
            # A bare element, which xmltodict gives as None, or one holding only text.
            return []
        if not any(k[0] != "@" and k != "#text" for k in element):
            # The element has attributes but no child elements, such as a lookup with no values. An
            # element whose children go by an unexpected name still fails below, rather than look empty.
            return []
        key_cap = self._identify_key(element, self.element_keys[metadata_type])
        entries = element[key_cap]
        return entries if isinstance(entries, list) else [entries]

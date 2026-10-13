import logging

import xmltodict

from rets.exceptions import ParseError

from .base import Base


logger = logging.getLogger("rets")


class CompactMetadata(Base):
    """Parses COMPCACT-DECODED RETS responses"""

    def parse(self, response, metadata_type):
        """
        Parses RETS metadata using the COMPACT-DECODED format
        :param response:
        :param metadata_type:
        :return:
        """
        # Keep the whitespace around element text. A COMPACT row is tab delimited, so stripping
        # it would drop empty fields from either end and shift every value after them.
        xml = xmltodict.parse(response.text, strip_whitespace=False)
        self.analyze_reply_code(xml_response_dict=xml)
        base = xml.get("RETS", {}).get(metadata_type, {})

        # xmltodict returns a list when the metadata element repeats, as it does for a wildcard lookup.
        for element in base if isinstance(base, list) else [base]:
            yield from self._parse_element(element)

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


class StandardXMLMetadata(Base):
    """Parses STANDARD-XML RETS responses"""

    # For each metadata type: the child element holding its entries, and the attribute naming each
    # metadata element when a wildcard request returns several of them.
    element_keys = {  # noqa: RUF012
        "METADATA-CLASS": ("class", "Resource"),
        "METADATA-RESOURCE": ("resource", None),
        "METADATA-LOOKUP_TYPE": ("lookuptype", "Lookup"),
        "METADATA-OBJECT": ("object", "Resource"),
        "METADATA-TABLE": ("field", "Class"),
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

    def parse(self, response, metadata_type):  # noqa: C901
        """
        Parses RETS metadata using the STANDARD-XML format
        :param response: requests Response object
        :param metadata_type: string
        :return parsed: list, or a dict of lists keyed by name when the response holds several metadata elements
        """
        xml = xmltodict.parse(response.text)
        self.analyze_reply_code(xml_response_dict=xml)
        base = xml.get("RETS", {}).get("METADATA", {}).get(metadata_type, {})

        if metadata_type == "METADATA-SYSTEM":
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
            return [system_obj]

        if metadata_type not in self.element_keys:
            msg = f"Got an unknown metadata type of {metadata_type!s}"
            raise ParseError(msg)
        key, name_attribute = self.element_keys[metadata_type]

        if isinstance(base, list):
            # Multiple metadata elements were returned, as for a wildcard request.
            # Return a dict of lists, keyed by the name each element covers.
            if not name_attribute:
                msg = f"Got more than one {metadata_type!s} element, but there is nothing to tell them apart by"
                raise ParseError(msg)
            res = {}
            for i in base:
                name = i.get(f"@{name_attribute}")
                if name is None:
                    msg = f"A {metadata_type!s} element is missing its {name_attribute!s} attribute"
                    raise ParseError(msg)
                if name in res:
                    # Wildcards spanning several resources can repeat a name; refuse rather than lose entries.
                    msg = f"Got more than one {metadata_type!s} element for {name_attribute!s} {name!s}"
                    raise ParseError(msg)
                key_cap = self._identify_key(i, key)
                res[name] = i[key_cap] if isinstance(i[key_cap], list) else [i[key_cap]]
            return res

        else:
            key_cap = self._identify_key(base, key)
            # Server returns single list
            if isinstance(base[key_cap], list):
                return base[key_cap]
            else:
                return [base[key_cap]]

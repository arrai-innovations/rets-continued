import hashlib
import io
import unittest

import xmltodict

from rets.exceptions import MaxrowException
from rets.exceptions import ParseError
from rets.exceptions import RETSException
from rets.parsers.base import Base
from rets.parsers.get_object import MultipleObjectParser
from rets.parsers.get_object import SingleObjectParser
from rets.parsers.login import OneXLogin
from rets.parsers.metadata import CompactMetadata
from rets.parsers.metadata import StandardXMLMetadata
from rets.parsers.search import OneXSearchCursor
from rets.parsers.search import ResponseStream
from rets.session import Session


SYSTEM_RESPONSE = (
    '<RETS ReplyCode="0" ReplyText="Operation Success.">'
    '<METADATA-SYSTEM Version="1.11.76001" Date="2016-11-29T06:01:13Z">'
    "{body}"
    "</METADATA-SYSTEM>"
    "</RETS>"
)


class FakeResponse:
    """Stands in for the requests Response that the parsers read."""

    def __init__(self, text, headers=None, content=None):
        self.text = text
        self.headers = headers if headers is not None else {"Content-Type": "text/plain"}
        self.content = content if content is not None else text.encode("latin-1")

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]


class CompactSystemMetadataTester(unittest.TestCase):
    """METADATA-SYSTEM extraction, across the shapes RETS servers send it in"""

    def parse(self, body):
        response = FakeResponse(SYSTEM_RESPONSE.format(body=body))
        return list(CompactMetadata().parse(response=response, metadata_type="METADATA-SYSTEM"))

    def test_id_and_description(self):
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS" SystemDescription="A description"/>'),
            [
                {
                    "system_id": "MLS-RETS",
                    "system_description": "A description",
                    "version": "1.11.76001",
                }
            ],
        )

    def test_id_without_description(self):
        # Only SystemDescription is required by the RETS spec, so the id has to be read
        # independently of it.
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS"/>'),
            [{"system_id": "MLS-RETS", "version": "1.11.76001"}],
        )

    def test_description_without_id(self):
        self.assertEqual(
            self.parse('<SYSTEM SystemDescription="A description"/>'),
            [{"system_description": "A description", "version": "1.11.76001"}],
        )

    def test_mixed_case_system_element(self):
        self.assertEqual(
            self.parse('<System SystemID="MLS-RETS" SystemDescription="A description"/>'),
            [
                {
                    "system_id": "MLS-RETS",
                    "system_description": "A description",
                    "version": "1.11.76001",
                }
            ],
        )

    def test_timezone_offset_and_sibling_comments(self):
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS" TimeZoneOffset="-05:00"/><COMMENTS>Some comments</COMMENTS>'),
            [
                {
                    "system_id": "MLS-RETS",
                    "timezone_offset": "-05:00",
                    "comments": "Some comments",
                    "version": "1.11.76001",
                }
            ],
        )

    def test_comments_nested_in_system(self):
        for tag in ("Comments", "COMMENTS"):
            with self.subTest(tag=tag):
                self.assertEqual(
                    self.parse(f'<SYSTEM SystemID="MLS-RETS"><{tag}>Some comments</{tag}></SYSTEM>'),
                    [{"system_id": "MLS-RETS", "comments": "Some comments", "version": "1.11.76001"}],
                )

    def test_missing_system(self):
        # Raised as the STANDARD-XML parser raises it, rather than returning no system.
        for body in ("", "<SYSTEM/>", "<SYSTEM>\n</SYSTEM>", "<COMMENTS>Only comments</COMMENTS>"):
            with self.subTest(body=body), self.assertRaisesRegex(ParseError, "Could not get the System key"):
                self.parse(body)

    def test_empty_comments_element_is_omitted(self):
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS"/><COMMENTS></COMMENTS>'),
            [{"system_id": "MLS-RETS", "version": "1.11.76001"}],
        )


class CompactDataMetadataTester(unittest.TestCase):
    """Splitting COMPACT-DECODED metadata rows into their columns"""

    def parse(self, body):
        response = FakeResponse(
            '<RETS ReplyCode="0"><METADATA-LOOKUP_TYPE Resource="Property" Lookup="Area">'
            f"{body}"
            "</METADATA-LOOKUP_TYPE></RETS>"
        )
        return list(CompactMetadata().parse(response=response, metadata_type="METADATA-LOOKUP_TYPE"))

    def test_values_containing_spaces(self):
        self.assertEqual(
            self.parse("<COLUMNS>\tLongValue\tShortValue\tValue\t</COLUMNS><DATA>\tNorth Side\tN Side\tN\t</DATA>"),
            [
                {
                    "LongValue": "North Side",
                    "ShortValue": "N Side",
                    "Value": "N",
                    "Resource": "Property",
                    "Lookup": "Area",
                }
            ],
        )

    def test_empty_fields(self):
        # Empty fields at the start, middle and end must not shift the values after them.
        self.assertEqual(
            self.parse(
                "<COLUMNS>\tLongValue\tShortValue\tValue\t</COLUMNS><DATA>\t\t\tN\t</DATA><DATA>\tNorth\t\t\t</DATA>"
            ),
            [
                {"LongValue": "", "ShortValue": "", "Value": "N", "Resource": "Property", "Lookup": "Area"},
                {"LongValue": "North", "ShortValue": "", "Value": "", "Resource": "Property", "Lookup": "Area"},
            ],
        )

    def test_empty_data_element(self):
        self.assertEqual(
            self.parse("<COLUMNS>\tLongValue\tValue\t</COLUMNS><DATA></DATA>"),
            [{"Resource": "Property", "Lookup": "Area"}],
        )


class CompactEmptyMetadataTester(unittest.TestCase):
    """COMPACT-DECODED metadata elements that hold no entries"""

    def parse(self, elements):
        response = FakeResponse(f'<RETS ReplyCode="0">{elements}</RETS>')
        return list(CompactMetadata().parse(response=response, metadata_type="METADATA-LOOKUP_TYPE"))

    def test_element_with_no_attributes_or_entries(self):
        for element in ("<METADATA-LOOKUP_TYPE>\n</METADATA-LOOKUP_TYPE>", "<METADATA-LOOKUP_TYPE/>"):
            with self.subTest(element=element):
                self.assertEqual(self.parse(element), [])

    def test_wildcard_with_an_empty_element(self):
        # The empty element does not fail the entries of the others.
        self.assertEqual(
            self.parse(
                '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Area"><COLUMNS>\tValue\t</COLUMNS>'
                "<DATA>\tN\t</DATA></METADATA-LOOKUP_TYPE>"
                "<METADATA-LOOKUP_TYPE>\n</METADATA-LOOKUP_TYPE>"
            ),
            [{"Value": "N", "Resource": "Property", "Lookup": "Area"}],
        )

    def test_element_with_attributes_and_no_entries(self):
        self.assertEqual(
            self.parse('<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Area">\n</METADATA-LOOKUP_TYPE>'), []
        )


def compact_lookup(resource, lookup, *values):
    rows = "".join(f"<DATA>\t{value}\t</DATA>" for value in values)
    columns = "<COLUMNS>\tValue\t</COLUMNS>" if values else ""
    return f'<METADATA-LOOKUP_TYPE Resource="{resource}" Lookup="{lookup}">{columns}{rows}</METADATA-LOOKUP_TYPE>'


def standard_lookup(resource, lookup, *values):
    entries = "".join(f"<LookupType><Value>{value}</Value></LookupType>" for value in values)
    return f'<METADATA-LOOKUP_TYPE Resource="{resource}" Lookup="{lookup}">{entries}</METADATA-LOOKUP_TYPE>'


class EmptyRetsElementTester(unittest.TestCase):
    """A metadata response whose RETS element holds no metadata element has no entries, in either format"""

    BODIES = ("<RETS></RETS>", "<RETS/>", "<RETS>text</RETS>", "<RETS>\n</RETS>", '<RETS ReplyCode="0"/>')

    def test_compact(self):
        # As for a RETS element that only has a reply code: no entries.
        for body in self.BODIES:
            with self.subTest(body=body):
                parser = CompactMetadata()
                self.assertEqual(parser.parse(FakeResponse(body), "METADATA-CLASS"), [])
                self.assertEqual(parser.parse(FakeResponse(body), "METADATA-CLASS", meta_id="*"), {})

    def test_standard_xml(self):
        bodies = (*self.BODIES, '<RETS ReplyCode="0"><METADATA>text</METADATA></RETS>')
        for body in bodies:
            with self.subTest(body=body):
                parser = StandardXMLMetadata()
                self.assertEqual(parser.parse(FakeResponse(body), "METADATA-CLASS"), [])
                self.assertEqual(parser.parse(FakeResponse(body), "METADATA-CLASS", meta_id="*"), {})

    def test_system_is_still_required(self):
        # There is no system to return, so both formats raise rather than return nothing.
        for parser in (CompactMetadata(), StandardXMLMetadata()):
            with self.subTest(parser=type(parser).__name__), self.assertRaises(ParseError):
                parser.parse(FakeResponse('<RETS ReplyCode="0"><METADATA/></RETS>'), "METADATA-SYSTEM")


class CompactWildcardMetadataTester(unittest.TestCase):
    """Keying a COMPACT-DECODED wildcard response by the names the wildcard stands for, as STANDARD-XML does"""

    LOOKUPS = (
        compact_lookup("Property", "Status", "A")
        + compact_lookup("Property", "Area", "N", "S")
        + compact_lookup("Agent", "Status", "B")
    )

    def parse(self, metadata_type, elements, meta_id=None):
        response = FakeResponse(f'<RETS ReplyCode="0">{elements}</RETS>')
        return CompactMetadata().parse(response=response, metadata_type=metadata_type, meta_id=meta_id)

    @staticmethod
    def values(result):
        """The result with each row reduced to its Value, to compare shapes"""
        if isinstance(result, dict):
            return {name: CompactWildcardMetadataTester.values(rows) for name, rows in result.items()}
        return [row["Value"] for row in result]

    def test_wildcard_name_keyed_by_name(self):
        result = self.parse(
            "METADATA-LOOKUP_TYPE",
            compact_lookup("Property", "Status", "A") + compact_lookup("Property", "Area", "N", "S"),
            meta_id="Property:*",
        )

        self.assertEqual(self.values(result), {"Status": ["A"], "Area": ["N", "S"]})
        # Each row keeps the attributes of its element, as it does without a wildcard.
        self.assertEqual(result["Area"][0], {"Value": "N", "Resource": "Property", "Lookup": "Area"})

    def test_wildcard_resource_keyed_by_resource(self):
        result = self.parse(
            "METADATA-LOOKUP_TYPE",
            compact_lookup("Property", "Status", "A") + compact_lookup("Agent", "Status", "B"),
            meta_id="*:Status",
        )

        self.assertEqual(self.values(result), {"Property": ["A"], "Agent": ["B"]})

    def test_wildcard_resource_and_name_nested(self):
        self.assertEqual(
            self.values(self.parse("METADATA-LOOKUP_TYPE", self.LOOKUPS, meta_id="*:*")),
            {"Property": {"Status": ["A"], "Area": ["N", "S"]}, "Agent": {"Status": ["B"]}},
        )

    def test_wildcard_resource_for_tables_and_classes(self):
        tables = (
            '<METADATA-TABLE Resource="Property" Class="RES"><COLUMNS>\tSystemName\t</COLUMNS>'
            "<DATA>\tA\t</DATA></METADATA-TABLE>"
            '<METADATA-TABLE Resource="Agent" Class="RES"><COLUMNS>\tSystemName\t</COLUMNS>'
            "<DATA>\tB\t</DATA></METADATA-TABLE>"
        )
        classes = (
            '<METADATA-CLASS Resource="Property"><COLUMNS>\tClassName\t</COLUMNS><DATA>\tRES\t</DATA></METADATA-CLASS>'
        )

        self.assertEqual(
            {
                name: [row["SystemName"] for row in rows]
                for name, rows in self.parse("METADATA-TABLE", tables, "*:RES").items()
            },
            {"Property": ["A"], "Agent": ["B"]},
        )
        self.assertEqual(list(self.parse("METADATA-CLASS", classes, "*")), ["Property"])

    def test_wildcard_name_with_no_rows(self):
        self.assertEqual(
            self.values(
                self.parse(
                    "METADATA-LOOKUP_TYPE",
                    compact_lookup("Property", "Status", "A") + compact_lookup("Property", "Empty"),
                    meta_id="Property:*",
                )
            ),
            {"Status": ["A"], "Empty": []},
        )

    def test_wildcard_matching_nothing(self):
        for elements in ("", "<METADATA-LOOKUP_TYPE/>", "<METADATA-LOOKUP_TYPE>\n</METADATA-LOOKUP_TYPE>"):
            with self.subTest(elements=elements):
                self.assertEqual(self.parse("METADATA-LOOKUP_TYPE", elements, meta_id="Property:*"), {})

    def test_repeated_element_is_refused(self):
        with self.assertRaisesRegex(ParseError, "for Resource Property, Lookup Status"):
            self.parse("METADATA-LOOKUP_TYPE", self.LOOKUPS + compact_lookup("Property", "Status", "C"), meta_id="*:*")

    def test_missing_name_attribute(self):
        with self.assertRaisesRegex(ParseError, "missing its Lookup attribute"):
            self.parse(
                "METADATA-LOOKUP_TYPE",
                '<METADATA-LOOKUP_TYPE Resource="Property"><COLUMNS>\tValue\t</COLUMNS><DATA>\tA\t</DATA>'
                "</METADATA-LOOKUP_TYPE>",
                meta_id="Property:*",
            )

    def test_id_without_a_wildcard_is_a_list(self):
        # Without a wildcard the rows stay in one list, even when the server sends several elements.
        self.assertEqual(
            self.values(self.parse("METADATA-LOOKUP_TYPE", self.LOOKUPS, meta_id="Property:Status")),
            ["A", "N", "S", "B"],
        )
        self.assertEqual(self.values(self.parse("METADATA-LOOKUP_TYPE", self.LOOKUPS)), ["A", "N", "S", "B"])

    def test_same_shape_as_standard_xml(self):
        # For each ID, the lookups a server would send for it: (resource, lookup, values).
        responses_by_id = {
            "*:*": [
                ("Property", "Status", "A"),
                ("Property", "Area", "N", "S"),
                ("Agent", "Status", "B"),
                ("Property", "Empty"),
            ],
            "Property:*": [("Property", "Status", "A"), ("Property", "Area", "N", "S"), ("Property", "Empty")],
            "*:Status": [("Property", "Status", "A"), ("Agent", "Status", "B")],
        }
        for meta_id, lookups in responses_by_id.items():
            with self.subTest(meta_id=meta_id):
                compact = self.parse(
                    "METADATA-LOOKUP_TYPE", "".join(compact_lookup(*x) for x in lookups), meta_id=meta_id
                )
                standard = StandardXMLMetadata().parse(
                    response=FakeResponse(
                        '<RETS ReplyCode="0"><METADATA>'
                        + "".join(standard_lookup(*x) for x in lookups)
                        + "</METADATA></RETS>"
                    ),
                    metadata_type="METADATA-LOOKUP_TYPE",
                    meta_id=meta_id,
                )

                self.assertEqual(self.values(compact), self.values(standard))


class StandardXMLWildcardMetadataTester(unittest.TestCase):
    """Keying the metadata elements of a STANDARD-XML wildcard response by the name each one covers"""

    def parse(self, metadata_type, elements, meta_id=None):
        response = FakeResponse(f'<RETS ReplyCode="0"><METADATA>{elements}</METADATA></RETS>')
        return StandardXMLMetadata().parse(response=response, metadata_type=metadata_type, meta_id=meta_id)

    def test_classes_keyed_by_resource(self):
        self.assertEqual(
            self.parse(
                "METADATA-CLASS",
                '<METADATA-CLASS Resource="Property"><Class><ClassName>RES</ClassName></Class>'
                "<Class><ClassName>LND</ClassName></Class></METADATA-CLASS>"
                '<METADATA-CLASS Resource="Agent"><Class><ClassName>AGT</ClassName></Class></METADATA-CLASS>',
            ),
            {
                "Property": [{"ClassName": "RES"}, {"ClassName": "LND"}],
                # A resource with a single class still maps to a list.
                "Agent": [{"ClassName": "AGT"}],
            },
        )

    def test_tables_keyed_by_class(self):
        self.assertEqual(
            self.parse(
                "METADATA-TABLE",
                '<METADATA-TABLE Resource="Property" Class="RES"><Field><SystemName>A</SystemName></Field>'
                "</METADATA-TABLE>"
                '<METADATA-TABLE Resource="Property" Class="LND"><Field><SystemName>B</SystemName></Field>'
                "</METADATA-TABLE>",
            ),
            {"RES": [{"SystemName": "A"}], "LND": [{"SystemName": "B"}]},
        )

    def test_objects_keyed_by_resource(self):
        self.assertEqual(
            self.parse(
                "METADATA-OBJECT",
                '<METADATA-OBJECT Resource="Property"><Object><ObjectType>Photo</ObjectType></Object>'
                "</METADATA-OBJECT>"
                '<METADATA-OBJECT Resource="Agent"><Object><ObjectType>Photo</ObjectType></Object>'
                "</METADATA-OBJECT>",
            ),
            {"Property": [{"ObjectType": "Photo"}], "Agent": [{"ObjectType": "Photo"}]},
        )

    def test_repeated_name_is_refused(self):
        # A wildcard across resources can repeat a class name; merging them would silently drop fields.
        with self.assertRaises(ParseError):
            self.parse(
                "METADATA-TABLE",
                '<METADATA-TABLE Resource="Property" Class="1"><Field><SystemName>A</SystemName></Field>'
                "</METADATA-TABLE>"
                '<METADATA-TABLE Resource="Agent" Class="1"><Field><SystemName>B</SystemName></Field>'
                "</METADATA-TABLE>",
            )

    def test_missing_name_attribute(self):
        with self.assertRaises(ParseError):
            self.parse(
                "METADATA-CLASS",
                '<METADATA-CLASS Resource="Property"><Class><ClassName>RES</ClassName></Class></METADATA-CLASS>'
                "<METADATA-CLASS><Class><ClassName>AGT</ClassName></Class></METADATA-CLASS>",
            )

    def test_wildcard_matching_a_single_name(self):
        # The result has the same type as when the wildcard matches several names.
        element = '<METADATA-CLASS Resource="Property"><Class><ClassName>RES</ClassName></Class></METADATA-CLASS>'

        self.assertEqual(self.parse("METADATA-CLASS", element, meta_id="*"), {"Property": [{"ClassName": "RES"}]})
        self.assertEqual(self.parse("METADATA-CLASS", element), [{"ClassName": "RES"}])

    STATUS_LOOKUPS = (
        '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Status"><LookupType><Value>A</Value></LookupType>'
        "</METADATA-LOOKUP_TYPE>"
        '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Area"><LookupType><Value>N</Value></LookupType>'
        "</METADATA-LOOKUP_TYPE>"
        '<METADATA-LOOKUP_TYPE Resource="Agent" Lookup="Status"><LookupType><Value>B</Value></LookupType>'
        "</METADATA-LOOKUP_TYPE>"
    )

    def test_wildcard_resource_keyed_by_resource(self):
        # Two resources each have a Status lookup, which keying by lookup name would collide on.
        elements = (
            '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Status"><LookupType><Value>A</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
            '<METADATA-LOOKUP_TYPE Resource="Agent" Lookup="Status"><LookupType><Value>B</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
        )

        self.assertEqual(
            self.parse("METADATA-LOOKUP_TYPE", elements, meta_id="*:Status"),
            {"Property": [{"Value": "A"}], "Agent": [{"Value": "B"}]},
        )

    def test_wildcard_name_keyed_by_name(self):
        elements = (
            '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Status"><LookupType><Value>A</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
            '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Area"><LookupType><Value>N</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
        )

        self.assertEqual(
            self.parse("METADATA-LOOKUP_TYPE", elements, meta_id="Property:*"),
            {"Status": [{"Value": "A"}], "Area": [{"Value": "N"}]},
        )

    def test_wildcard_resource_and_name_nested(self):
        self.assertEqual(
            self.parse("METADATA-LOOKUP_TYPE", self.STATUS_LOOKUPS, meta_id="*:*"),
            {
                "Property": {"Status": [{"Value": "A"}], "Area": [{"Value": "N"}]},
                "Agent": {"Status": [{"Value": "B"}]},
            },
        )

    def test_wildcard_resource_for_tables(self):
        elements = (
            '<METADATA-TABLE Resource="Property" Class="RES"><Field><SystemName>A</SystemName></Field>'
            "</METADATA-TABLE>"
            '<METADATA-TABLE Resource="Agent" Class="RES"><Field><SystemName>B</SystemName></Field>'
            "</METADATA-TABLE>"
        )

        self.assertEqual(
            self.parse("METADATA-TABLE", elements, meta_id="*:RES"),
            {"Property": [{"SystemName": "A"}], "Agent": [{"SystemName": "B"}]},
        )

    def test_wildcard_resource_with_a_single_part_id(self):
        element = '<METADATA-CLASS Resource="Property"><Class><ClassName>RES</ClassName></Class></METADATA-CLASS>'

        self.assertEqual(self.parse("METADATA-CLASS", element, meta_id="*"), {"Property": [{"ClassName": "RES"}]})

    def test_id_without_a_wildcard(self):
        element = (
            '<METADATA-LOOKUP_TYPE Resource="Property" Lookup="Status"><LookupType><Value>A</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
        )

        self.assertEqual(self.parse("METADATA-LOOKUP_TYPE", element, meta_id="Property:Status"), [{"Value": "A"}])

    def test_nested_wildcard_with_a_repeated_element(self):
        elements = self.STATUS_LOOKUPS + (
            '<METADATA-LOOKUP_TYPE Resource="Agent" Lookup="Status"><LookupType><Value>C</Value></LookupType>'
            "</METADATA-LOOKUP_TYPE>"
        )

        with self.assertRaisesRegex(ParseError, "for Resource Agent, Lookup Status"):
            self.parse("METADATA-LOOKUP_TYPE", elements, meta_id="*:*")

    def test_nested_wildcard_with_a_missing_resource(self):
        elements = (
            '<METADATA-LOOKUP_TYPE Lookup="Status"><LookupType><Value>A</Value></LookupType></METADATA-LOOKUP_TYPE>'
        )

        with self.assertRaisesRegex(ParseError, "missing its Resource attribute"):
            self.parse("METADATA-LOOKUP_TYPE", elements, meta_id="*:*")

    def test_nested_wildcard_matching_nothing(self):
        self.assertEqual(self.parse("METADATA-LOOKUP_TYPE", "", meta_id="*:*"), {})

    def test_wildcard_matching_nothing(self):
        # Whether the server leaves METADATA empty or sends it as a bare tag.
        for metadata in ("<METADATA></METADATA>", "<METADATA/>"):
            with self.subTest(metadata=metadata):
                response = FakeResponse(f'<RETS ReplyCode="0">{metadata}</RETS>')
                self.assertEqual(
                    StandardXMLMetadata().parse(response=response, metadata_type="METADATA-CLASS", meta_id="*"), {}
                )

    def test_wildcard_name_with_no_entries(self):
        # A lookup with no values keeps its name, and does not fail the lookups that have values.
        self.assertEqual(
            self.parse(
                "METADATA-LOOKUP_TYPE",
                '<METADATA-LOOKUP_TYPE Lookup="Area"><LookupType><Value>N</Value></LookupType></METADATA-LOOKUP_TYPE>'
                '<METADATA-LOOKUP_TYPE Lookup="Empty" Version="1.0"/>',
                meta_id="Property:*",
            ),
            {"Area": [{"Value": "N"}], "Empty": []},
        )
        self.assertEqual(
            self.parse("METADATA-LOOKUP_TYPE", '<METADATA-LOOKUP_TYPE Lookup="Empty"/>', meta_id="Property:*"),
            {"Empty": []},
        )

    def test_wildcard_skips_an_unnamed_element_with_no_entries(self):
        self.assertEqual(
            self.parse("METADATA-LOOKUP_TYPE", '<METADATA-LOOKUP_TYPE Version="1.0"/>', meta_id="Property:*"),
            {},
        )

    def test_element_with_no_entries(self):
        for element in ('<METADATA-LOOKUP_TYPE Lookup="Empty" Version="1.0"/>', "<METADATA-LOOKUP_TYPE/>"):
            with self.subTest(element=element):
                self.assertEqual(self.parse("METADATA-LOOKUP_TYPE", element), [])

    def test_missing_element(self):
        # No entries, as the COMPACT-DECODED format gives.
        self.assertEqual(self.parse("METADATA-CLASS", ""), [])

    def test_entries_under_an_unexpected_name(self):
        # Entries the parser does not recognise must not be mistaken for an empty element.
        with self.assertRaises(ParseError):
            self.parse(
                "METADATA-LOOKUP_TYPE", '<METADATA-LOOKUP_TYPE Lookup="Area"><Thing>1</Thing></METADATA-LOOKUP_TYPE>'
            )


class LogMessageTester(unittest.TestCase):
    """The parsers' debug messages carry the values they describe, not unfilled placeholders"""

    def test_reply_code(self):
        with self.assertLogs("rets", level="DEBUG") as logs:
            Base().analyze_reply_code({"RETS": {"@ReplyCode": "0", "@ReplyText": "Operation Success."}})

        self.assertEqual(
            [r.getMessage() for r in logs.records],
            ["Received ReplyCode of 0 from the RETS Server: Operation Success."],
        )

    def test_rets_status_reply_code(self):
        with self.assertLogs("rets", level="DEBUG") as logs:
            Base().analyze_reply_code(
                {
                    "RETS": {
                        "@ReplyCode": "0",
                        "@ReplyText": "Operation Success.",
                        "RETS-STATUS": {"@ReplyCode": "0", "@ReplyText": "Status OK."},
                    }
                }
            )

        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                "Received ReplyCode of 0 from the RETS Server: Operation Success.",
                "Received ReplyCode of 0 from the RETS Server: Status OK.",
            ],
        )

    def test_maxrows(self):
        body = (
            '<RETS ReplyCode="0"><DELIMITER value="09"/><COLUMNS>\tListingID\t</COLUMNS>'
            "<DATA>\t123\t</DATA><DATA>\t456\t</DATA><MAXROWS/></RETS>"
        )
        with self.assertLogs("rets", level="DEBUG") as logs, self.assertRaises(MaxrowException):
            list(OneXSearchCursor().generator(response=FakeResponse(body)))

        self.assertIn("The response held 2 rows before MAXROWS", [r.getMessage() for r in logs.records])

    def test_maxrows_counts_the_rows_of_its_own_response(self):
        body = (
            '<RETS ReplyCode="0"><DELIMITER value="09"/><COLUMNS>\tListingID\t</COLUMNS>'
            "<DATA>\t123\t</DATA><DATA>\t456\t</DATA><MAXROWS/></RETS>"
        )
        parser = OneXSearchCursor()
        with self.assertRaises(MaxrowException):
            list(parser.generator(response=FakeResponse(body)))
        with self.assertRaises(MaxrowException) as caught:
            list(parser.generator(response=FakeResponse(body)))

        # A parser reused for a later search or page reports that response's rows, not every row it has read.
        self.assertEqual(caught.exception.rows_returned, 2)
        self.assertEqual(parser.parsed_rows, 4)


class MultipartObjectTester(unittest.TestCase):
    """Splitting a multipart GetObject response into its objects without altering their content"""

    def parse(self, body):
        response = FakeResponse(
            body.decode("latin-1"),
            headers={"Content-Type": 'multipart/parallel; boundary="BOUND"'},
            content=body,
        )
        return list(MultipleObjectParser().parse_image_response(response))

    def test_binary_content_ending_in_line_breaks(self):
        # Only the CRLF ahead of the delimiter belongs to the multipart framing; the rest is the object's own.
        content = b"\r\n\x89PNG\x00\xaeB`\x82\r\n\n"
        objs = self.parse(b"\r\n--BOUND\r\nContent-ID: 1\r\nObject-ID: 1\r\n\r\n" + content + b"\r\n--BOUND--\r\n")

        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["content"], content)

    def test_bare_lf_line_endings(self):
        objs = self.parse(
            b"\n--BOUND\n"
            b"Content-Type: image/jpeg\nContent-ID: 1\nObject-ID: 1\nLocation: http://example.com/1.jpg\n\n\n"
            b"--BOUND\n"
            b"Content-Type: image/jpeg\nContent-ID: 1\nObject-ID: 2\n\nimagedata\n"
            b"--BOUND--\n"
        )

        self.assertEqual(
            [(o["content_type"], o["object_id"], o["location"], o["content"]) for o in objs],
            [
                ("image/jpeg", "1", "http://example.com/1.jpg", None),
                ("image/jpeg", "2", None, b"imagedata"),
            ],
        )

    def test_epilogue_is_ignored(self):
        objs = self.parse(b"--BOUND\r\nObject-ID: 1\r\n\r\ndata\r\n--BOUND--\r\nan epilogue\r\n")

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("1", b"data")])

    def test_preamble_is_ignored(self):
        for preamble in (b"This is a multi-part message in MIME format.\r\n", b"\r\nSee below.\r\n\r\nThanks\r\n"):
            with self.subTest(preamble=preamble):
                objs = self.parse(preamble + b"--BOUND\r\nContent-ID: 1\r\nObject-ID: 1\r\n\r\ndata\r\n--BOUND--\r\n")

                self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("1", b"data")])

    def test_missing_first_delimiter(self):
        # Text ahead of the first delimiter that has part headers is read as a part, not a preamble.
        objs = self.parse(
            b"Content-ID: 1\r\nObject-ID: 1\r\n\r\nfirst\r\n"
            b"--BOUND\r\nContent-ID: 1\r\nObject-ID: 2\r\n\r\nsecond\r\n--BOUND--\r\n"
        )

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("1", b"first"), ("2", b"second")])

    def test_missing_close_delimiter(self):
        objs = self.parse(b"--BOUND\r\nObject-ID: 1\r\n\r\nno close delimiter")

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("1", b"no close delimiter")])

    def test_blank_parts_are_skipped(self):
        objs = self.parse(b"--BOUND\r\nObject-ID: 1\r\n\r\nA\r\n--BOUND\r\n\r\n--BOUND\r\n \t\r\n\r\n--BOUND--\r\n")

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("1", b"A")])

    def test_object_not_found_part_is_skipped(self):
        # Some servers send characters after the XML part's closing tag.
        objs = self.parse(
            b"--BOUND\r\nContent-Type: text/xml\r\n\r\n"
            b'<RETS ReplyCode="20403" ReplyText="No Object Found"/>trailing\r\n'
            b"--BOUND\r\nObject-ID: 2\r\n\r\nfound\r\n--BOUND--\r\n"
        )

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("2", b"found")])

    def test_object_not_found_in_a_nested_rets_status(self):
        # The RETS-STATUS closes itself inside RETS, so the part does not end at the first "/>".
        objs = self.parse(
            b"--BOUND\r\nContent-Type: text/xml\r\n\r\n"
            b'<RETS ReplyCode="0" ReplyText="ok"><RETS-STATUS ReplyCode="20403" ReplyText="No object"/></RETS>'
            b"trailing\r\n"
            b"--BOUND\r\nObject-ID: 2\r\n\r\nfound\r\n--BOUND--\r\n"
        )

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("2", b"found")])

    def test_object_not_found_with_a_greater_than_sign_in_its_text(self):
        objs = self.parse(
            b"--BOUND\r\nContent-Type: text/xml\r\n\r\n"
            b'<RETS ReplyCode="20403" ReplyText="Object id > max"/>trailing\r\n'
            b"--BOUND\r\nObject-ID: 2\r\n\r\nfound\r\n--BOUND--\r\n"
        )

        self.assertEqual([(o["object_id"], o["content"]) for o in objs], [("2", b"found")])

    def test_error_in_a_nested_rets_status(self):
        with self.assertRaises(RETSException) as caught:
            self.parse(
                b"--BOUND\r\nContent-Type: text/xml\r\n\r\n"
                b'<?xml version="1.0"?>\r\n<RETS ReplyCode="0">\r\n'
                b'<RETS-STATUS ReplyCode="20409" ReplyText="Timeout"/>\r\n</RETS>\r\n'
                b"--BOUND--\r\n"
            )

        self.assertEqual(caught.exception.reply_code, "20409")

    def test_xml_part_cut_to_its_root_element(self):
        cases = {
            b'<RETS ReplyCode="20403"/>junk': b'<RETS ReplyCode="20403"/>',
            b'<?xml version="1.0"?><RETS ReplyCode="20403"/>junk': b'<?xml version="1.0"?><RETS ReplyCode="20403"/>',
            b'<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20403"/></RETS>junk': (
                b'<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20403"/></RETS>'
            ),
            b'<RETS-STATUS ReplyCode="20403"></RETS-STATUS>junk': b'<RETS-STATUS ReplyCode="20403"></RETS-STATUS>',
            # A ">" or "/>" inside an attribute value does not end the start tag.
            b'<RETS ReplyCode="20403" ReplyText="Object id > max"/>junk': (
                b'<RETS ReplyCode="20403" ReplyText="Object id > max"/>'
            ),
            b'<RETS ReplyCode="0" ReplyText="a/>b"><RETS-STATUS ReplyCode="20403"/></RETS>junk': (
                b'<RETS ReplyCode="0" ReplyText="a/>b"><RETS-STATUS ReplyCode="20403"/></RETS>'
            ),
            b"<RETS ReplyCode='20403' ReplyText='x > y' />junk": b"<RETS ReplyCode='20403' ReplyText='x > y' />",
            b'<RETS\r\n  ReplyCode = "20403"\r\n/>junk': b'<RETS\r\n  ReplyCode = "20403"\r\n/>',
            b'<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20403"/></RETS >junk': (
                b'<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20403"/></RETS >'
            ),
            b"no element": b"no element",
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertEqual(MultipleObjectParser._root_element(body), expected)

    def test_header_names_in_any_case(self):
        objs = self.parse(
            b"--BOUND\r\ncontent-type: text/xml\r\ncontent-id: 1\r\n\r\n"
            b'<RETS ReplyCode="20403" ReplyText="No Object Found"/>\r\n'
            b"--BOUND\r\nCONTENT-ID: 1\r\nobject-id: 2\r\ncontent-TYPE: image/jpeg\r\nlocation: http://example.com/2.jpg\r\n"
            b"\r\nfound\r\n--BOUND--\r\n"
        )

        # The lower-case XML error part is recognised and skipped, and the other part's headers are all read.
        self.assertEqual(
            [(o["content_id"], o["object_id"], o["content_type"], o["location"], o["content"]) for o in objs],
            [("1", "2", "image/jpeg", "http://example.com/2.jpg", b"found")],
        )

    def test_content_is_bytes_with_its_md5(self):
        content = bytes(range(256))
        objs = self.parse(b"--BOUND\r\nObject-ID: 1\r\n\r\n" + content + b"\r\n--BOUND--\r\n")

        self.assertEqual(objs[0]["content"], content)
        self.assertEqual(objs[0]["content_md5"], hashlib.md5(content).hexdigest())  # noqa: S324

    def test_xml_part_without_a_body(self):
        with self.assertRaises(ParseError):
            self.parse(b"--BOUND\r\nContent-Type: text/xml\r\n--BOUND--\r\n")


class LoginParserTester(unittest.TestCase):
    """Sorting the login response's key-value lines into capabilities and details"""

    def parse(self, body):
        parser = OneXLogin()
        parser.parse(FakeResponse(body))
        return parser

    def test_extension_capabilities(self):
        parser = self.parse(
            "\r\n".join(
                [
                    "MemberName=John Doe",
                    "MetadataVersion=1.11.75995",
                    "Login=http://server.rets.com/rets/Login.ashx",
                    "Search=http://server.rets.com/rets/Search.ashx",
                    "X-SampleCapability=http://server.rets.com/rets/Sample.ashx",
                ]
            )
        )

        # An X- prefixed name is a vendor capability URL, not a detail about the account.
        self.assertEqual(
            parser.capabilities,
            {
                "Login": "http://server.rets.com/rets/Login.ashx",
                "Search": "http://server.rets.com/rets/Search.ashx",
                "X-SampleCapability": "http://server.rets.com/rets/Sample.ashx",
            },
        )
        self.assertEqual(parser.details, {"MemberName": "John Doe", "MetadataVersion": "1.11.75995"})

    def test_details_are_not_treated_as_capabilities(self):
        parser = self.parse("\r\n".join(["Broker=BROKER1", "TimeoutSeconds=1800", "MaxRows=X-notacapability"]))

        self.assertEqual(parser.capabilities, {})
        self.assertEqual(
            parser.details,
            {"Broker": "BROKER1", "TimeoutSeconds": "1800", "MaxRows": "X-notacapability"},
        )

    def test_extension_details_are_not_treated_as_capabilities(self):
        parser = self.parse(
            "\r\n".join(
                [
                    "X-Selector=/rets/selector",
                    "X-Secure=https://server.rets.com/rets/Secure.ashx",
                    "X-SessionTimeout=30",
                    "X-Info=Contact support for help",
                    "X-Relative=rets/notapath",
                    "X-Scheme=mailto:support@example.com",
                ]
            )
        )

        # Vendors use X- names for details too; only a URL or an absolute path is a transaction.
        self.assertEqual(
            parser.capabilities,
            {"X-Selector": "/rets/selector", "X-Secure": "https://server.rets.com/rets/Secure.ashx"},
        )
        self.assertEqual(
            parser.details,
            {
                "X-SessionTimeout": "30",
                "X-Info": "Contact support for help",
                "X-Relative": "rets/notapath",
                "X-Scheme": "mailto:support@example.com",
            },
        )

    def test_response_without_content_type(self):
        parser = OneXLogin()
        parser.parse(FakeResponse("Login=http://server.rets.com/rets/Login.ashx", headers={}))

        self.assertEqual(parser.capabilities, {"Login": "http://server.rets.com/rets/Login.ashx"})


class ChunkedResponse:
    """A streamed response whose body arrives in the given chunks, counting how many have been read"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.chunks_read = 0

    def iter_content(self, chunk_size=1):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk

    @property
    def content(self):
        return b"".join(self.iter_content())


class XMLReplyTester(unittest.TestCase):
    """A login or GetObject response sent as XML holds a reply code in place of the content asked for"""

    ERROR = '<RETS ReplyCode="20036" ReplyText="Miscellaneous server login error."/>'

    def assert_reply_code_raised(self, parse, content_type):
        response = FakeResponse(self.ERROR, headers={"Content-Type": content_type})
        with self.assertRaises(RETSException) as caught:
            parse(response)
        self.assertEqual(caught.exception.reply_code, "20036")

    def test_login(self):
        self.assert_reply_code_raised(OneXLogin().parse, "text/xml")

    def test_single_object(self):
        self.assert_reply_code_raised(lambda r: list(SingleObjectParser().parse_image_response(r)), "text/xml")

    def test_multiple_objects(self):
        self.assert_reply_code_raised(
            lambda r: list(MultipleObjectParser().parse_image_response(r)), "application/xml; charset=utf-8"
        )

    def test_success_reply_code(self):
        response = FakeResponse('<RETS ReplyCode="0" ReplyText="Success"/>', headers={"Content-Type": "text/xml"})

        objs = list(SingleObjectParser().parse_image_response(response))
        self.assertEqual(objs[0]["content"], response.content)

    def test_non_xml_response_is_not_checked(self):
        # An object that merely contains XML-like bytes is returned as it is.
        response = FakeResponse(self.ERROR, headers={"Content-Type": "image/jpeg"})

        objs = list(SingleObjectParser().parse_image_response(response))
        self.assertEqual(objs[0]["content"], self.ERROR.encode())


class ReplyCodeLocationTester(unittest.TestCase):
    """Every parser finds the reply code wherever a server puts it"""

    NESTED = '<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20203" ReplyText="Miscellaneous error."/></RETS>'
    ROOT = '<RETS-STATUS ReplyCode="20203" ReplyText="Miscellaneous error."/>'

    def assert_reply_code_raised(self, parse):
        for body in (self.NESTED, self.ROOT):
            with self.subTest(body=body), self.assertRaises(RETSException) as caught:
                parse(body)
            self.assertEqual(
                (caught.exception.reply_code, caught.exception.reply_text), ("20203", "Miscellaneous error.")
            )

    def test_login(self):
        self.assert_reply_code_raised(
            lambda body: OneXLogin().parse(FakeResponse(body, headers={"Content-Type": "text/xml"}))
        )

    def test_metadata(self):
        for parser in (CompactMetadata(), StandardXMLMetadata()):
            with self.subTest(parser=type(parser).__name__):
                self.assert_reply_code_raised(
                    lambda body, p=parser: list(p.parse(response=FakeResponse(body), metadata_type="METADATA-CLASS"))
                )

    def test_search(self):
        self.assert_reply_code_raised(
            lambda body: list(OneXSearchCursor().generator(response=ChunkedResponse([body.encode()])))
        )

    def test_success_status_document(self):
        # A RETS-STATUS sent as the whole response used to fail with a KeyError looking for the RETS element.
        Base().analyze_reply_code({"RETS-STATUS": {"@ReplyCode": "0", "@ReplyText": "Status OK."}})

    def test_search_no_records_found_in_rets_status(self):
        response = ChunkedResponse(
            [b'<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20201" ReplyText="No Records Found."/></RETS>']
        )

        self.assertEqual(list(OneXSearchCursor().generator(response=response)), [])

    def test_search_without_a_reply_code(self):
        # No reply code reports no error, as for every other response, rather than a RETSException without a code.
        response = ChunkedResponse([b"<RETS><COLUMNS>\tListingID\t</COLUMNS><DATA>\t1\t</DATA></RETS>"])

        self.assertEqual(list(OneXSearchCursor().generator(response=response)), [{"ListingID": "1"}])


class DataColumnsTester(unittest.TestCase):
    """Pairing a row's values with its column names"""

    def test_delimited(self):
        # The unnamed columns at each end of a COMPACT line are dropped, and empty values keep their place.
        self.assertEqual(
            Base.data_columns_to_dict("\tA\tB\tC\t", "\t1\t\tx y\t", delimiter="\t"),
            {"A": "1", "B": "", "C": "x y"},
        )

    def test_whitespace(self):
        for delimiter in (None, ""):
            with self.subTest(delimiter=delimiter):
                self.assertEqual(
                    Base.data_columns_to_dict("A  B\tC", " 1 2  3 ", delimiter), {"A": "1", "B": "2", "C": "3"}
                )


class ReplyCodeReadersAgreeTester(unittest.TestCase):
    """The xmltodict, ElementTree and streaming readers find the same reply code in the same response"""

    # Each body, and the error reply code every reader must find in it, or None.
    BODIES = {  # noqa: RUF012
        '<RETS ReplyCode="20203"/>': "20203",
        '<RETS ReplyCode="0"><RETS-STATUS ReplyCode="20203"/></RETS>': "20203",
        '<RETS-STATUS ReplyCode="20203"/>': "20203",
        # The first error wins, from the RETS element before a RETS-STATUS inside it.
        '<RETS ReplyCode="20203"><RETS-STATUS ReplyCode="20209"/></RETS>': "20203",
        # Every repeated RETS-STATUS is read, not only the first.
        '<RETS ReplyCode="0"><RETS-STATUS ReplyCode="0"/><RETS-STATUS ReplyCode="20209"/></RETS>': "20209",
        # A RETS-STATUS anywhere else is not where a reply code is reported.
        '<RETS ReplyCode="0"><OTHER><RETS-STATUS ReplyCode="20203"/></OTHER></RETS>': None,
        '<HTML><RETS-STATUS ReplyCode="20203"/></HTML>': None,
        '<RETS ReplyCode="0"/>': None,
    }

    @staticmethod
    def xmltodict_reader(body):
        try:
            Base().analyze_reply_code(xmltodict.parse(body))
        except RETSException as e:
            return e.reply_code
        return None

    @staticmethod
    def tree_reader(body):
        error = Session._rets_error_reply(FakeResponse(body))
        return error[0] if error else None

    @staticmethod
    def stream_reader(body):
        try:
            list(OneXSearchCursor().generator(response=ChunkedResponse([body.encode()])))
        except RETSException as e:
            return e.reply_code
        return None

    def test_readers_agree(self):
        for body, reply_code in self.BODIES.items():
            for reader in (self.tree_reader, self.stream_reader, self.xmltodict_reader):
                if reader is self.xmltodict_reader and body.startswith("<HTML>"):
                    continue  # The parsers only read RETS responses, and raise for any other document.
                with self.subTest(body=body, reader=reader.__name__):
                    self.assertEqual(reader(body), reply_code)


class ResponseStreamTester(unittest.TestCase):
    """Reading a response body through ResponseStream gives exactly its bytes, however the reads fall"""

    CHUNKS = (b"", b"abc", b"", b"defghij", b"k", b"lmnopqrstuvwxyz" * 3, b"")
    BODY = b"".join(CHUNKS)

    def test_reads_smaller_than_a_chunk(self):
        stream = ResponseStream(ChunkedResponse(self.CHUNKS))
        buffer = bytearray(4)
        received = b""
        while size := stream.readinto(buffer):
            received += buffer[:size]

        self.assertEqual(received, self.BODY)
        self.assertEqual(stream.readinto(buffer), 0)

    def test_reads_of_every_size(self):
        for size in range(1, len(self.BODY) + 2):
            with self.subTest(size=size):
                reader = io.BufferedReader(ResponseStream(ChunkedResponse(self.CHUNKS)), buffer_size=size)
                parts = iter(lambda r=reader, n=size: r.read(n), b"")

                self.assertEqual(b"".join(parts), self.BODY)

    def test_read_all(self):
        self.assertEqual(ResponseStream(ChunkedResponse(self.CHUNKS)).read(), self.BODY)
        self.assertEqual(ResponseStream(ChunkedResponse([])).read(), b"")


class SearchStreamingTester(unittest.TestCase):
    """Search rows come out as the response arrives, rather than once all of it has been read"""

    def test_first_row_before_the_whole_response(self):
        response = ChunkedResponse(
            [b'<RETS ReplyCode="0"><DELIMITER value="09"/><COLUMNS>\tListingID\t</COLUMNS>']
            + [f"<DATA>\t{i}\t</DATA>".encode() for i in range(1000)]
            + [b"</RETS>"]
        )
        rows = OneXSearchCursor().generator(response=response)

        self.assertEqual(next(rows), {"ListingID": "0"})
        self.assertLess(response.chunks_read, 10)

        self.assertEqual(len(list(rows)), 999)
        self.assertEqual(response.chunks_read, 1002)

    def test_error_reply_code_before_any_row(self):
        response = ChunkedResponse(
            [
                b'<RETS ReplyCode="20203" ReplyText="Miscellaneous search error.">',
                b"<COLUMNS>\tListingID\t</COLUMNS><DATA>\t1\t</DATA>",
                b"</RETS>",
            ]
        )

        with self.assertRaises(RETSException) as caught:
            next(OneXSearchCursor().generator(response=response))
        self.assertEqual(caught.exception.reply_code, "20203")
        self.assertEqual(caught.exception.reply_text, "Miscellaneous search error.")
        self.assertEqual(str(caught.exception), "Miscellaneous search error.")

    def test_error_reply_code_without_reply_text(self):
        response = ChunkedResponse([b'<RETS ReplyCode="20203"/>'])

        with self.assertRaises(RETSException) as caught:
            list(OneXSearchCursor().generator(response=response))
        self.assertEqual(caught.exception.reply_code, "20203")
        self.assertEqual(str(caught.exception), "RETS did not supply a Reply Text.")

    def test_no_records_found(self):
        response = ChunkedResponse([b'<RETS ReplyCode="20201" ReplyText="No Records Found."/>'])

        self.assertEqual(list(OneXSearchCursor().generator(response=response)), [])


class SearchCursorTester(unittest.TestCase):
    """Search result parsing, for the sparse elements servers include in real responses"""

    def parse(self, body):
        return list(OneXSearchCursor().generator(response=FakeResponse(body)))

    def test_rows(self):
        rows = self.parse(
            '<RETS ReplyCode="0">'
            '<DELIMITER value="09"/>'
            "<COLUMNS>\tListingID\tListPrice\t</COLUMNS>"
            "<DATA>\t123\t200000\t</DATA>"
            "<DATA>\t456\t250000\t</DATA>"
            "</RETS>"
        )
        self.assertEqual(
            rows,
            [
                {"ListingID": "123", "ListPrice": "200000"},
                {"ListingID": "456", "ListPrice": "250000"},
            ],
        )

    def test_empty_data_element(self):
        # A row the server sent with no content still has to be yielded, or the auto-offset
        # would resume before it and fetch it a second time.
        rows = self.parse(
            '<RETS ReplyCode="0">'
            '<DELIMITER value="09"/>'
            "<COLUMNS>\tListingID\tListPrice\t</COLUMNS>"
            "<DATA>\t123\t200000\t</DATA>"
            "<DATA/>"
            "</RETS>"
        )
        self.assertEqual(rows, [{"ListingID": "123", "ListPrice": "200000"}, {}])

    def test_delimiter_without_a_value(self):
        # Falls back to the tab default rather than blowing up on int(None).
        rows = self.parse('<RETS ReplyCode="0"><DELIMITER/><COLUMNS>\tListingID\t</COLUMNS><DATA>\t123\t</DATA></RETS>')
        self.assertEqual(rows, [{"ListingID": "123"}])

    def test_delimiter_is_hex(self):
        # Only tab reads the same in decimal, which hid that the value is hex.
        for value, delimiter in (("09", "\t"), ("7C", "|"), ("7c", "|"), ("2C", ","), ("3B", ";")):
            with self.subTest(value=value):
                rows = self.parse(
                    f'<RETS ReplyCode="0"><DELIMITER value="{value}"/>'
                    f"<COLUMNS>{delimiter}ListingID{delimiter}City{delimiter}</COLUMNS>"
                    f"<DATA>{delimiter}123{delimiter}New Haven{delimiter}</DATA></RETS>"
                )
                self.assertEqual(rows, [{"ListingID": "123", "City": "New Haven"}])

    def test_unreadable_delimiter(self):
        with self.assertRaisesRegex(ParseError, "two hex digits"):
            self.parse('<RETS ReplyCode="0"><DELIMITER value="tab"/><COLUMNS>\tA\t</COLUMNS></RETS>')

    def test_missing_delimiter_element(self):
        rows = self.parse('<RETS ReplyCode="0"><COLUMNS>\tListingID\t</COLUMNS><DATA>\t123\t</DATA></RETS>')
        self.assertEqual(rows, [{"ListingID": "123"}])

    def test_empty_columns_element(self):
        rows = self.parse('<RETS ReplyCode="0"><COLUMNS/><DATA>\t123\t</DATA></RETS>')
        self.assertEqual(rows, [{}])


class ObjectContentTypeTester(unittest.TestCase):
    """Object responses that arrive with no Content-Type header at all"""

    def test_single_object_without_content_type(self):
        response = FakeResponse("imagedata", headers={"Content-ID": "1", "Object-ID": "1"})
        objs = list(SingleObjectParser().parse_image_response(response))

        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["content_id"], "1")
        self.assertEqual(objs[0]["content"], b"imagedata")

    def test_multipart_part_without_content_type(self):
        body = "\r\n".join(
            [
                "--BOUND",
                "Content-ID: 1",
                "Object-ID: 1",
                "",
                "imagedata",
                "--BOUND--",
            ]
        )
        response = FakeResponse(body, headers={"Content-Type": 'multipart/parallel; boundary="BOUND"'})
        objs = list(MultipleObjectParser().parse_image_response(response))

        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["content_id"], "1")
        self.assertEqual(objs[0]["content"], b"imagedata")

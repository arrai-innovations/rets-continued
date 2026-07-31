import unittest

from rets.parsers.get_object import MultipleObjectParser
from rets.parsers.get_object import SingleObjectParser
from rets.parsers.login import OneXLogin
from rets.parsers.metadata import CompactMetadata
from rets.parsers.search import OneXSearchCursor


SYSTEM_RESPONSE = (
    '<RETS ReplyCode="0" ReplyText="Operation Success.">'
    '<METADATA-SYSTEM Version="1.11.76001" Date="2016-11-29T06:01:13Z">'
    "{body}"
    "</METADATA-SYSTEM>"
    "</RETS>"
)


class FakeRaw:
    """The urllib3 stream that the search cursor sets decode_content on."""

    decode_content = False


class FakeResponse:
    """Stands in for the requests Response that the parsers read."""

    def __init__(self, text, headers=None, content=None):
        self.text = text
        self.headers = headers if headers is not None else {"Content-Type": "text/plain"}
        self.content = content if content is not None else text.encode("latin-1")
        self.raw = FakeRaw()


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
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS"><Comments>Some comments</Comments></SYSTEM>'),
            [{"system_id": "MLS-RETS", "comments": "Some comments", "version": "1.11.76001"}],
        )

    def test_empty_comments_element_is_omitted(self):
        self.assertEqual(
            self.parse('<SYSTEM SystemID="MLS-RETS"/><COMMENTS></COMMENTS>'),
            [{"system_id": "MLS-RETS", "version": "1.11.76001"}],
        )


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

    def test_response_without_content_type(self):
        parser = OneXLogin()
        parser.parse(FakeResponse("Login=http://server.rets.com/rets/Login.ashx", headers={}))

        self.assertEqual(parser.capabilities, {"Login": "http://server.rets.com/rets/Login.ashx"})


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

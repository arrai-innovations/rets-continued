import unittest

from rets.parsers.login import OneXLogin
from rets.parsers.metadata import CompactMetadata


SYSTEM_RESPONSE = (
    '<RETS ReplyCode="0" ReplyText="Operation Success.">'
    '<METADATA-SYSTEM Version="1.11.76001" Date="2016-11-29T06:01:13Z">'
    "{body}"
    "</METADATA-SYSTEM>"
    "</RETS>"
)


class FakeResponse:
    """Stands in for the requests Response that the parsers read."""

    def __init__(self, text, headers=None):
        self.text = text
        self.headers = headers if headers is not None else {"Content-Type": "text/plain"}


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

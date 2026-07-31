import unittest

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

    def __init__(self, text):
        self.text = text


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

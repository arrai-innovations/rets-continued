import unittest
from urllib.parse import parse_qs
from urllib.parse import urlparse

import responses

from rets.exceptions import HTTPException
from rets.exceptions import MissingVersion
from rets.exceptions import NotLoggedIn
from rets.exceptions import ParseError
from rets.exceptions import RETSException
from rets.parsers.search import OneXSearchCursor
from rets.session import Session
from tests.custom_parser_example import CreaStandardXParser


SEARCH_RESPONSE = (
    '<RETS ReplyCode="0" ReplyText="Success"><DELIMITER value="09"/>'
    "<COLUMNS>\tListingID\t</COLUMNS><DATA>\t1\t</DATA></RETS>"
)


class SessionTester(unittest.TestCase):
    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login.ashx",
                body=contents,
                status=200,
                headers={"Set-Cookie": "ASP.NET_SessionId=zacqcc1gjhkmazjznjmyrinq;"},
            )
            self.session = Session(
                login_url="http://server.rets.com/rets/Login.ashx",
                username="retsuser",
                version="RETS/1.7.2",
                session_id_cookie_name="ASP.NET_SessionId",
            )
            self.session.login()

    def test_system_metadata(self):

        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_system.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            sys_metadata = self.session.get_system_metadata()

        self.assertEqual(sys_metadata["version"], "1.11.76001")
        self.assertEqual(sys_metadata["system_id"], "MLS-RETS")

    def test_logout(self):
        with open("tests/rets_responses/Logout.html") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Logout.ashx",
                body=contents,
                status=200,
            )

            self.assertTrue(self.session.logout())

    def test_resource_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_resources.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            resource = self.session.get_resource_metadata()
            self.assertEqual(len(list(resource)), 6)

    def test_get_object(self):

        with open("tests/rets_responses/GetObject.byte", "rb") as f:
            single = f.read()

        with open("tests/rets_responses/GetObject_multipart.byte", "rb") as f:
            multiple = f.read()

        multi_headers = {
            "Content-Type": 'multipart/parallel; boundary="24cbd0e0afd2589bb9dcb1f34cf19862"; charset=utf-8',
            "Connection": "keep-alive",
            "RETS-Version": "RETS/1.7.2",
            "MIME-Version": "1.0, 1.0",
        }

        single_headers = {
            "MIME-Version": "1.0, 1.0",
            "Object-ID": "0",
            "Content-ID": "2144466",
            "Content-Type": "image/jpeg",
            "Connection": "keep-alive",
            "RETS-Version": "RETS/1.7.2",
        }

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=single,
                status=200,
                headers=single_headers,
            )

            objs = self.session.get_object(
                resource="Property",
                object_type="Photo",
                content_ids="1",
                object_ids="1",
            )
            obj_l = list(objs)
            self.assertEqual(len(obj_l), 1)
            self.assertEqual(obj_l[0]["content_md5"], "2174ba5b342a04604adcdddf2775b19d")

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=multiple,
                status=200,
                headers=multi_headers,
            )

            objs1 = list(self.session.get_object(resource="Property", object_type="Photo", content_ids="1"))
            # Checksums of the JPEGs in the fixture. The trailing "Object not found" part yields no object.
            self.assertEqual(
                [obj["content_md5"] for obj in objs1],
                [
                    "2174ba5b342a04604adcdddf2775b19d",
                    "2174ba5b342a04604adcdddf2775b19d",
                    "76780bfc931179db9b8f39be77287477",
                    "92276e2f22643ce3d4605d2dac5c0f81",
                    "621acfa042ea2c433f2c4ef23c553bb5",
                    "40c1da31201c9df754ed64b456f9b05e",
                    "48d0d06af1c922a1182c7d7fe0a06f89",
                    "76bda7db20cd096921ba1603275cdf15",
                    "33b342ca422b5ae6bb2ca1619e1057c3",
                ],
            )
            self.assertEqual([obj["object_id"] for obj in objs1], [str(i) for i in range(9)])

    def test_get_object_without_content_type(self):
        with open("tests/rets_responses/GetObject.byte", "rb") as f:
            single = f.read()

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=single,
                status=200,
                content_type=None,
                headers={"Content-ID": "2144466", "Object-ID": "0"},
            )

            # Choosing the parser must not depend on the server sending a Content-Type.
            objs = list(self.session.get_object(resource="Property", object_type="Photo", content_ids="1"))

        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0]["content_md5"], "2174ba5b342a04604adcdddf2775b19d")

    def test_get_object_location1(self):
        with open("tests/rets_responses/GetObject_multipart_Location1.byte", "rb") as f:
            multiple = f.read()

        multi_headers = {
            "Content-Type": "multipart/parallel; "
            'boundary="FLEXLIAsmcpmiKpZ3uhewHnpQUlQNYzuNzPeUi0PIqCAxzgSRkpypX"; '
            "charset=utf-8",
            "Connection": "keep-alive",
            "RETS-Version": "RETS/1.7.2",
            "MIME-Version": "1.0, 1.0",
        }

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=multiple,
                status=200,
                headers=multi_headers,
            )

            objs1 = list(
                self.session.get_object(resource="Property", object_type="Photo", content_ids="1", location="1")
            )
            self.assertEqual(len(objs1), 41)

        # This server separates lines with bare LFs, which used to fold every header into content_type.
        self.assertEqual(
            {k: objs1[0][k] for k in ["content_type", "content_id", "object_id", "location", "preferred", "content"]},
            {
                "content_type": "image/jpeg",
                "content_id": "1256671",
                "object_id": "1",
                "location": "http://cdn.resize.sparkplatform.com/gcar/1024x768/true/20161216161456298557000000-o.jpg",
                "preferred": "1",
                "content": None,
            },
        )

    def test_preferred_object(self):
        with open("tests/rets_responses/GetObject_multipart.byte", "rb") as f:
            multiple = f.read()

        multi_headers = {
            "Content-Type": 'multipart/parallel; boundary="24cbd0e0afd2589bb9dcb1f34cf19862"; charset=utf-8',
            "Connection": "keep-alive",
            "RETS-Version": "RETS/1.7.2",
            "MIME-Version": "1.0, 1.0",
        }

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=multiple,
                status=200,
                headers=multi_headers,
            )

            obj = self.session.get_preferred_object(resource="Property", object_type="Photo", content_id=1)
            self.assertTrue(obj)

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetObject.ashx",
                body=multiple,
                status=200,
            )

            resource = {}
            resource["ResourceID"] = "Agent"
            obj1 = self.session.get_preferred_object(resource=resource, object_type="Photo", content_id=1)
            self.assertTrue(obj1)

    def test_class_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_classes.xml") as f:
            contents = "".join(f.readlines())

        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_classes_single.xml") as f:
            single_contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            resource_classes = self.session.get_class_metadata(resource="Agent")
            self.assertEqual(len(list(resource_classes)), 6)

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=single_contents,
                status=200,
            )
            resource_classes_single = self.session.get_class_metadata(resource="Property")
            self.assertEqual(len(list(resource_classes_single)), 1)

    def test_search(self):

        with open("tests/rets_responses/COMPACT-DECODED/Search.xml") as f:
            search_contents = "".join(f.readlines())

        with open("tests/rets_responses/CREA-STANDARD-XML/Search.xml") as f:
            custom_search_contents = "".join(f.readlines())

        with open("tests/rets_responses/Errors/Error_InvalidFormat.xml") as f:
            invalid_contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=search_contents,
                status=200,
            )
            results_gen = self.session.search(
                resource="Property",
                resource_class="RES",
                search_filter={"ListingPrice": 200000},
            )
            results = list(results_gen)
            self.assertEqual(len(results), 3)

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=search_contents,
                status=200,
            )

            results1_gen = self.session.search(
                resource="Property",
                resource_class="RES",
                limit=3,
                dmql_query="ListingPrice=200000",
                optional_parameters={"RestrictedIndicator": "!!!!"},
            )
            results1 = list(results1_gen)
            self.assertEqual(len(results1), 3)

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=custom_search_contents,
                status=200,
            )

            self.session.search_parser = CreaStandardXParser()
            results2_gen = self.session.search(
                resource="Property",
                resource_class="Property",
                limit=1,
                response_format="STANDARD-XML",
                dmql_query="(ID=20270724)",
            )
            results2 = list(results2_gen)
            self.assertEqual(len(results2), 1)
            self.session.search_parser = None

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=invalid_contents,
                status=200,
            )
            with self.assertRaises(RETSException):
                r = self.session.search(
                    resource="Property",
                    resource_class="RES",
                    dmql_query="ListingPrice=200000",
                    optional_parameters={"Format": "Somecrazyformat"},
                )
                print(list(r))  # noqa: T201

    def test_search_validates_arguments_when_called(self):
        """Bad arguments must raise from the search() call, not wait for the caller to iterate."""
        # Neither a filter nor a query.
        with self.assertRaises(ValueError):
            self.session.search(resource="Property", resource_class="RES")

        # Both a filter and a query.
        with self.assertRaises(ValueError):
            self.session.search(
                resource="Property",
                resource_class="RES",
                search_filter={"ListingPrice": 200000},
                dmql_query="ListingPrice=200000",
            )

        # A dict where a DMQL string belongs.
        with self.assertRaises(ValueError):
            self.session.search(
                resource="Property",
                resource_class="RES",
                dmql_query={"ListingPrice": 200000},
            )

        # A string where a filter dict belongs.
        with self.assertRaises(TypeError):
            self.session.search(
                resource="Property",
                resource_class="RES",
                search_filter="ListingPrice=200000",
            )

        # An unsupported filter operator.
        with self.assertRaises(ValueError):
            self.session.search(
                resource="Property",
                resource_class="RES",
                search_filter={"Status": {"$not": "unsupported"}},
            )

    def test_search_defers_the_request_until_iterated(self):
        """Only validation is eager; no request is made until the generator is consumed."""
        with open("tests/rets_responses/COMPACT-DECODED/Search.xml") as f:
            search_contents = "".join(f.readlines())

        # Built outside the mock, so an eager request here would fail to find a registered URL.
        results = self.session.search(
            resource="Property",
            resource_class="RES",
            search_filter={"ListingPrice": 200000},
        )

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=search_contents,
                status=200,
            )
            self.assertEqual(len(list(results)), 3)

    def test_auto_offset(self):
        with open("tests/rets_responses/COMPACT-DECODED/Search_1of2.xml") as f:
            search1_contents = "".join(f.readlines())

        with open("tests/rets_responses/COMPACT-DECODED/Search_2of2.xml") as f:
            search2_contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=search1_contents,
                status=200,
            )
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                body=search2_contents,
                status=200,
            )
            results_gen = self.session.search(
                resource="Property",
                resource_class="RES",
                search_filter={"ListingPrice": 200000},
            )
            results = list(results_gen)
            self.assertEqual(len(results), 6)

    def test_auto_offset_stops_on_an_empty_truncated_page(self):
        """A MAXROWS response without rows would otherwise be requested again from the same offset forever."""
        empty_truncated = (
            '<RETS ReplyCode="0" ReplyText="Success"><COUNT Records="5"/><DELIMITER value="09"/>'
            "<COLUMNS>\tListingID\t</COLUMNS><MAXROWS/></RETS>"
        )

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body=empty_truncated, status=200)
            with self.assertLogs("rets", level="WARNING"):
                results = list(
                    self.session.search(resource="Property", resource_class="RES", search_filter={"ListingID": 1})
                )

            self.assertEqual(results, [])
            self.assertEqual(len(resps.calls), 1)

    def test_auto_offset_without_a_limit(self):
        with open("tests/rets_responses/COMPACT-DECODED/Search_1of2.xml") as f:
            search1_contents = "".join(f.readlines())

        with open("tests/rets_responses/COMPACT-DECODED/Search_2of2.xml") as f:
            search2_contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            for contents in (search1_contents, search2_contents):
                resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body=contents, status=200)

            results = list(
                self.session.search(
                    resource="Property",
                    resource_class="RES",
                    search_filter={"ListingPrice": 200000},
                    limit=None,
                )
            )
            sent = [parse_qs(call.request.body) for call in resps.calls]

        self.assertEqual(len(results), 6)
        self.assertEqual([q.get("Offset") for q in sent], [None, ["3"]])
        self.assertEqual([q.get("Limit") for q in sent], [None, None])

    def test_auto_offset_with_shared_search_parser(self):
        """A search_parser is reused by every search, so its state must not shift later offsets."""
        with open("tests/rets_responses/COMPACT-DECODED/Search_1of2.xml") as f:
            search1_contents = "".join(f.readlines())

        with open("tests/rets_responses/COMPACT-DECODED/Search_2of2.xml") as f:
            search2_contents = "".join(f.readlines())

        self.session.search_parser = OneXSearchCursor()
        try:
            with responses.RequestsMock() as resps:
                for contents in (search1_contents, search2_contents) * 2:
                    resps.add(
                        resps.POST,
                        "http://server.rets.com/rets/Search.ashx",
                        body=contents,
                        status=200,
                    )

                for _ in range(2):
                    results = list(
                        self.session.search(
                            resource="Property",
                            resource_class="RES",
                            search_filter={"ListingPrice": 200000},
                        )
                    )
                    self.assertEqual(len(results), 6)

                sent = [parse_qs(call.request.body) for call in resps.calls]
        finally:
            self.session.search_parser = None

        # Each search starts unoffset and resumes from row 3, where the first response hit MAXROWS.
        self.assertEqual([q.get("Offset") for q in sent], [None, ["3"], None, ["3"]])
        self.assertEqual([q["Limit"] for q in sent], [["9999999"], ["9999996"], ["9999999"], ["9999996"]])

    def test_cache_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_table.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            self.session.get_table_metadata(resource="Property", resource_class="RES")

        self.assertIn("COMPACT-DECODED:METADATA-TABLE:Property:RES", list(self.session.metadata_responses.keys()))

        # Subsequent call without RequestMock should fail unless we get the saved response from metadata_responses
        table = self.session.get_table_metadata(resource="Property", resource_class="RES")
        self.assertEqual(len(list(table)), 208)

    def test_cache_metadata_after_format_change(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_resources.xml") as f:
            compact_resources = "".join(f.readlines())

        with open("tests/rets_responses/Errors/20514.xml") as f:
            dtd_error = "".join(f.readlines())

        with open("tests/rets_responses/STANDARD-XML/GetMetadata_classes.xml") as f:
            standard_classes = "".join(f.readlines())

        with open("tests/rets_responses/STANDARD-XML/GetMetadata_resources.xml") as f:
            standard_resources = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            for body in [compact_resources, dtd_error, standard_classes, standard_resources]:
                resps.add(resps.POST, "http://server.rets.com/rets/GetMetadata.ashx", body=body, status=200)

            self.assertEqual(len(self.session.get_resource_metadata()), 6)
            # The server rejects COMPACT-DECODED for classes, moving the session over to STANDARD-XML.
            self.session.get_class_metadata(resource="Agent")
            self.assertEqual(self.session.metadata_format, "STANDARD-XML")

            # The cached COMPACT-DECODED resources can't be read by the STANDARD-XML parser, so they are
            # requested again in the new format.
            resources = self.session.get_resource_metadata()

        self.assertEqual([r["ResourceID"] for r in resources], ["OpenHouse", "Property"])

    def test_unparseable_metadata_is_not_cached(self):
        self.session.metadata_format = "STANDARD-XML"
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_resources.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body='<RETS ReplyCode="0"><METADATA><METADATA-RESOURCE Version="1"/></METADATA></RETS>',
                status=200,
            )
            resps.add(resps.POST, "http://server.rets.com/rets/GetMetadata.ashx", body=contents, status=200)

            with self.assertRaises(ParseError):
                self.session.get_resource_metadata()
            self.assertEqual(self.session.metadata_responses, {})

            # The next call asks the server again, rather than failing on the saved response.
            self.assertEqual(len(self.session.get_resource_metadata()), 2)

    def test_table_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_table.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            table = self.session.get_table_metadata(resource="Property", resource_class="RES")

        self.assertEqual(len(list(table)), 208)
        # A value containing spaces and an empty StandardName stay in their own columns.
        self.assertEqual(
            {k: table[1][k] for k in ["SystemName", "StandardName", "LongName", "DBName", "DataType", "InKeyIndex"]},
            {
                "SystemName": "ActiveOpenHouseCount",
                "StandardName": "",
                "LongName": "Active Open House Count",
                "DBName": "R598",
                "DataType": "Int",
                "InKeyIndex": "0",
            },
        )

    def test_lookup_type_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_lookup.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            lookup_values = self.session.get_lookup_values(resource="Agent", lookup_name="Broker")

        self.assertEqual(len(list(lookup_values)), 61)

    def test_wildcard_lookup_type_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_lookup_wildcard.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            lookup_values = self.session.get_lookup_values(resource="Property", lookup_name="*")

        self.assertEqual(
            [(x["Lookup"], x["Value"]) for x in lookup_values],
            [
                ("State", "AL"),
                ("State", "CT"),
                ("PropertyType", "COML"),
                ("PropertyType", "RES"),
                ("PropertyType", "RNT"),
            ],
        )

    def test_object_metadata(self):
        with open("tests/rets_responses/COMPACT-DECODED/GetMetadata_objects.xml") as f:
            contents = "".join(f.readlines())
        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            object_metadata = self.session.get_object_metadata(resource="Agent")

        self.assertEqual(len(list(object_metadata)), 3)

    def test_agent_digest_hash(self):
        self.session.user_agent_password = "testing"  # noqa: S105

        # Section 3.10 of the RETS 1.7.2 spec, worked out with md5sum:
        #   a1 = MD5("Python RETS:testing") = 20b0a313ce37c22aef5a41459d2b217a
        #   MD5(a1 "::" session ID ":" RETS-Version), where the version keeps its "RETS/" prefix
        self.assertEqual(self.session._user_agent_digest_hash(), "699137ecaf098fdae7f70e3610469dc5")

    def test_agent_digest_header(self):
        self.session.user_agent_password = "testing"  # noqa: S105

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Logout.ashx", body="", status=200)
            self.session.logout()
            headers = resps.calls[0].request.headers

        self.assertEqual(headers["RETS-UA-Authorization"], "Digest 699137ecaf098fdae7f70e3610469dc5")
        # The digest covers the version the request actually sends.
        self.assertEqual(headers["RETS-Version"], "RETS/1.7.2")

    def test_user_agent_password_without_a_version(self):
        session = Session(
            login_url="http://server.rets.com/rets/Login.ashx",
            username="retsuser",
            user_agent_password="testing",  # noqa: S106
        )

        # The login request already carries the digest, so it fails before anything is sent.
        with responses.RequestsMock() as resps, self.assertRaises(MissingVersion) as caught:
            session.login()
        self.assertEqual(len(resps.calls), 0)

        self.assertEqual(
            str(caught.exception),
            "A RETS version is required for user agent authentication. The version is part of the digest sent with "
            "every request, including the login, so it is needed before the server can report its own. Pass the "
            'version your RETS server uses to the Session, such as version="RETS/1.7.2".',
        )

    def test_session_cookie_name(self):
        self.assertEqual(self.session.session_id, "zacqcc1gjhkmazjznjmyrinq")

    def test_change_parser_automatically(self):
        self.assertEqual(self.session.metadata_format, "COMPACT-DECODED")

        with open("tests/rets_responses/Errors/20514.xml") as f:
            dtd_error = "".join(f.readlines())

        with open("tests/rets_responses/STANDARD-XML/GetMetadata_system.xml") as f:
            content = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=dtd_error,
                status=200,
            )
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=content,
                status=200,
            )
            self.session.get_system_metadata()

        self.assertEqual(self.session.metadata_format, "STANDARD-XML")

    def test_wildcard_lookups(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_wildcard.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            format_hold = self.session.metadata_format
            try:
                self.session.metadata_format = "STANDARD-XML"
                lookup_values = self.session.get_lookup_values(resource="Property", lookup_name="*")
            finally:
                self.session.metadata_format = format_hold

        # A wildcard request maps each lookup name to its own list of values, rather than
        # collapsing down to just the names.
        self.assertIsInstance(lookup_values, dict)
        self.assertEqual(len(lookup_values), 40)
        self.assertIn("City", lookup_values)
        self.assertEqual(len(lookup_values["City"]), 298)
        self.assertEqual(
            lookup_values["City"][0],
            {
                "MetadataEntryID": "5569",
                "LongValue": "Aboujagane",
                "ShortValue": "ABJGN",
                "Value": "ABJGN",
            },
        )


class StatusCodeTester(unittest.TestCase):
    """How the HTTP status the server answered with is reported to the caller"""

    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login.ashx",
                body=contents,
                status=200,
            )
            self.session = Session(
                login_url="http://server.rets.com/rets/Login.ashx",
                username="retsuser",
                version="RETS/1.7.2",
            )
            self.session.login()

    def search(self):
        return list(
            self.session.search(
                resource="Property",
                resource_class="RES",
                dmql_query="(ListingPrice=200000)",
            )
        )

    def test_400_is_not_reported_as_an_auth_failure(self):
        # A rejected query is an HTTP problem, not a sign the session is logged out.
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body="Bad Request", status=400)

            with self.assertRaises(HTTPException) as caught:
                self.search()

        self.assertIn("400", str(caught.exception))
        self.assertNotIsInstance(caught.exception, NotLoggedIn)

    def test_401_still_reports_an_auth_failure(self):
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body="Unauthorized", status=401)

            with self.assertRaises(NotLoggedIn):
                self.search()

    def test_server_error(self):
        # Previously fell through to the XML parser and failed there instead.
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body="Server Error", status=500)

            with self.assertRaises(HTTPException) as caught:
                self.search()

        self.assertIn("500", str(caught.exception))

    def test_404_on_post_advises_the_get_method(self):
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Search.ashx", body="Not Found", status=404)

            with self.assertRaises(HTTPException) as caught:
                self.search()

        self.assertIn("use_post_method=False", str(caught.exception))

    def test_redirect_is_followed(self):
        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                status=307,
                headers={"Location": "http://server.rets.com/rets/Search2.ashx"},
            )
            resps.add(resps.POST, "http://server.rets.com/rets/Search2.ashx", body=SEARCH_RESPONSE, status=200)

            self.assertEqual(self.search(), [{"ListingID": "1"}])

    def test_redirect_is_not_followed(self):
        self.session.follow_redirects = False
        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Search.ashx",
                status=307,
                headers={"Location": "http://server.rets.com/rets/Search2.ashx"},
            )

            with self.assertRaises(HTTPException) as caught:
                self.search()

            self.assertEqual(len(resps.calls), 1)
        self.assertIn("http://server.rets.com/rets/Search2.ashx", str(caught.exception))


class ContextManagerTester(unittest.TestCase):
    """Logging out when leaving a with block, without hiding why the block ended"""

    LOGOUT_URL = "http://server.rets.com/rets/Logout.ashx"

    def run_block(self, logout_status, body_error=None):
        """Run a with block, returning the error it ended with and the URLs it requested"""
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        # The error is caught inside the mock, since responses skips its own checks while one propagates.
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=contents, status=200)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=logout_status)

            error = None
            try:
                with Session(login_url="http://server.rets.com/rets/Login.ashx", username="retsuser", version="1.7.2"):
                    if body_error:
                        raise body_error
            except Exception as e:
                error = e

            urls = [call.request.url for call in resps.calls]

        return error, urls

    def test_logs_out(self):
        error, urls = self.run_block(logout_status=200)

        self.assertIsNone(error)
        self.assertEqual(urls[-1], self.LOGOUT_URL)

    def test_logout_failure_is_raised_when_the_block_succeeds(self):
        error, _urls = self.run_block(logout_status=500)

        self.assertIsInstance(error, HTTPException)

    def test_logout_failure_does_not_hide_the_blocks_error(self):
        body_error = ValueError("the real error")

        with self.assertLogs("rets", level="WARNING") as logs:
            error, urls = self.run_block(logout_status=500, body_error=body_error)

        self.assertIs(error, body_error)
        self.assertEqual(urls[-1], self.LOGOUT_URL)
        # The logout failure is still reported, with its traceback.
        self.assertIn("HTTPException", logs.output[0])

    def test_logs_out_after_the_blocks_error(self):
        body_error = ValueError("the real error")

        error, urls = self.run_block(logout_status=200, body_error=body_error)

        self.assertIs(error, body_error)
        self.assertEqual(urls[-1], self.LOGOUT_URL)


class NoLogoutCapabilityTester(unittest.TestCase):
    """Servers whose login response offers no Logout transaction"""

    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            self.login_contents = "".join(line for line in f if not line.startswith("Logout="))
        self.session = Session(
            login_url="http://server.rets.com/rets/Login.ashx",
            username="retsuser",
            version="RETS/1.7.2",
        )

    def test_with_block(self):
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)

            with self.session as s:
                self.assertNotIn("Logout", s.capabilities)

            # Leaving the block makes no request, rather than raising NotLoggedIn.
            self.assertEqual(len(resps.calls), 1)

    def test_logout(self):
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)
            self.session.login()

            self.assertTrue(self.session.logout())
            self.assertEqual(len(resps.calls), 1)

    def test_logout_before_login(self):
        # Without a login there is no telling whether the server offers Logout, so this is still a mistake.
        with self.assertRaises(NotLoggedIn):
            self.session.logout()


class LogoutStateTester(unittest.TestCase):
    """What a session keeps once it has logged out"""

    LOGIN_URL = "http://server.rets.com/rets/Login.ashx"
    LOGOUT_URL = "http://server.rets.com/rets/Logout.ashx"

    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            self.login_contents = "".join(f.readlines())
        self.session = Session(login_url=self.LOGIN_URL, username="retsuser", version="RETS/1.7.2")

    def add_login(self, resps):
        resps.add(
            resps.POST,
            self.LOGIN_URL,
            body=self.login_contents,
            status=200,
            headers={"Set-Cookie": "RETS-Session-ID=abc123; Path=/"},
        )

    def test_logout_forgets_the_login(self):
        with responses.RequestsMock() as resps:
            self.add_login(resps)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=200)

            self.session.login()
            self.assertEqual(self.session.session_id, "abc123")
            self.session.logout()

        self.assertEqual(self.session.capabilities, {"Login": self.LOGIN_URL})
        self.assertIsNone(self.session.session_id)
        self.assertEqual(len(self.session.client.cookies), 0)

    def test_requests_after_logout_report_the_missing_login(self):
        with responses.RequestsMock() as resps:
            self.add_login(resps)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=200)
            self.session.login()
            self.session.logout()

            # Raised before any request is sent, rather than using the session the server has ended.
            with self.assertRaises(NotLoggedIn):
                self.session.get_system_metadata()
            with self.assertRaises(NotLoggedIn):
                self.session.logout()
            self.assertEqual(len(resps.calls), 2)

    def test_login_again_after_logout(self):
        with responses.RequestsMock() as resps:
            self.add_login(resps)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=200)
            self.session.login()
            self.session.logout()

            self.assertTrue(self.session.login())
            self.assertTrue(self.session.logout())
            self.assertEqual(
                [call.request.url for call in resps.calls],
                [self.LOGIN_URL, self.LOGOUT_URL, self.LOGIN_URL, self.LOGOUT_URL],
            )

    def test_failed_logout_keeps_the_login(self):
        with responses.RequestsMock() as resps:
            self.add_login(resps)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=500)
            self.session.login()

            with self.assertRaises(HTTPException):
                self.session.logout()

        # The server may still hold the session, so logging out can be tried again.
        self.assertIn("Logout", self.session.capabilities)
        self.assertEqual(self.session.session_id, "abc123")

    def test_logout_inside_a_with_block(self):
        with responses.RequestsMock() as resps:
            self.add_login(resps)
            resps.add(resps.POST, self.LOGOUT_URL, body="", status=200)

            with self.session as s:
                s.logout()

            # Leaving the block does not log out a second time.
            self.assertEqual([call.request.url for call in resps.calls], [self.LOGIN_URL, self.LOGOUT_URL])

    def test_logout_without_a_logout_capability_forgets_the_login(self):
        contents = "".join(line + "\n" for line in self.login_contents.splitlines() if not line.startswith("Logout="))
        with responses.RequestsMock() as resps:
            resps.add(resps.POST, self.LOGIN_URL, body=contents, status=200)
            self.session.login()
            self.session.logout()

        self.assertEqual(self.session.capabilities, {"Login": self.LOGIN_URL})


class BasicAuthOverHttpTester(unittest.TestCase):
    """Warning when basic authentication would send the password over plain HTTP"""

    WARNING = "basic authentication over plain HTTP"

    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            self.login_contents = "".join(f.readlines())

    def make_session(self, login_url, http_auth):
        return Session(
            login_url=login_url,
            username="retsuser",
            password="retspassword",  # noqa: S106
            version="RETS/1.7.2",
            http_auth=http_auth,
        )

    def test_warns_once_for_basic_auth_over_http(self):
        session = self.make_session("http://server.rets.com/rets/Login.ashx", http_auth="basic")

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)
            resps.add(resps.POST, "http://server.rets.com/rets/Logout.ashx", body="", status=200)

            with self.assertLogs("rets", level="WARNING") as logs:
                session.login()
                session.logout()

        warnings = [line for line in logs.output if self.WARNING in line]
        self.assertEqual(len(warnings), 1)
        self.assertIn("server.rets.com", warnings[0])
        self.assertNotIn("retspassword", warnings[0])

    def test_no_warning_for_basic_auth_over_https(self):
        session = self.make_session("https://server.rets.com/rets/Login.ashx", http_auth="basic")

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)

            with self.assertNoLogs("rets", level="WARNING"):
                session.login()

    def test_no_warning_for_digest_auth_over_http(self):
        session = self.make_session("http://server.rets.com/rets/Login.ashx", http_auth="digest")

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)

            with self.assertNoLogs("rets", level="WARNING"):
                session.login()

    def test_warns_when_a_basic_auth_fallback_meets_an_http_capability(self):
        # The login is https, but the server lists plain HTTP URLs for its other transactions.
        session = self.make_session("https://server.rets.com/rets/Login.ashx", http_auth="digest")

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body="", status=401)
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body=self.login_contents, status=200)
            resps.add(resps.POST, "http://server.rets.com/rets/Logout.ashx", body="", status=200)

            with self.assertNoLogs("rets", level="WARNING"):
                session.login()
            with self.assertLogs("rets", level="WARNING") as logs:
                session.logout()

        self.assertIn(self.WARNING, logs.output[0])


class LoginAuthFallbackTester(unittest.TestCase):
    """Falling back from digest to basic authentication when the server rejects digest"""

    def login_against(self, status):
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        session = Session(
            login_url="https://server.rets.com/rets/Login.ashx",
            username="retsuser",
            password="retspassword",  # noqa: S106
            version="RETS/1.7.2",
        )
        self.assertEqual(session.http_authentication, "digest")

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body="", status=status)
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body=contents, status=200)
            session.login()

        return session

    def test_falls_back_to_basic_on_401(self):
        session = self.login_against(401)

        self.assertEqual(session.http_authentication, "basic")
        self.assertIn("Search", session.capabilities)

    def test_falls_back_to_basic_on_400(self):
        # Some servers reject a digest attempt they cannot handle with a 400.
        session = self.login_against(400)

        self.assertEqual(session.http_authentication, "basic")
        self.assertIn("Search", session.capabilities)

    def test_gives_up_when_basic_is_also_rejected(self):
        session = Session(
            login_url="https://server.rets.com/rets/Login.ashx",
            username="retsuser",
            password="retspassword",  # noqa: S106
            version="RETS/1.7.2",
        )

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body="", status=401)
            resps.add(resps.POST, "https://server.rets.com/rets/Login.ashx", body="", status=401)

            with self.assertRaises(NotLoggedIn) as caught:
                session.login()

        self.assertIn("basic or digest", str(caught.exception))

    def test_no_fallback_over_http(self):
        # Retrying with basic auth would put the password on the wire in cleartext.
        session = Session(
            login_url="http://server.rets.com/rets/Login.ashx",
            username="retsuser",
            password="retspassword",  # noqa: S106
            version="RETS/1.7.2",
        )

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body="", status=401)

            with self.assertRaises(NotLoggedIn) as caught:
                session.login()

            self.assertEqual(len(resps.calls), 1)
            self.assertFalse(resps.calls[0].request.headers.get("Authorization", "").startswith("Basic "))
        self.assertEqual(session.http_authentication, "digest")
        self.assertIn('http_auth="basic"', str(caught.exception))

    def test_explicit_basic_over_http(self):
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        session = Session(
            login_url="http://server.rets.com/rets/Login.ashx",
            username="retsuser",
            password="retspassword",  # noqa: S106
            version="RETS/1.7.2",
            http_auth="basic",
        )

        with responses.RequestsMock() as resps:
            resps.add(resps.POST, "http://server.rets.com/rets/Login.ashx", body=contents, status=200)
            session.login()

            self.assertTrue(resps.calls[0].request.headers["Authorization"].startswith("Basic "))
        self.assertIn("Search", session.capabilities)


class Session15Tester(unittest.TestCase):
    def setUp(self):
        super().setUp()
        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login.ashx",
                body=contents,
                status=200,
            )
            self.session = Session(
                login_url="http://server.rets.com/rets/Login.ashx",
                username="retsuser",
                version="1.5",
            )
            self.session.metadata_format = "STANDARD-XML"
            self.session.login()

    def test_system_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_system.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            sys_metadata = self.session.get_system_metadata()

        self.assertEqual(sys_metadata["version"], "45.61.69081")
        self.assertEqual(sys_metadata["system_id"], "RETS")

    def test_resource_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_resources.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            resource = self.session.get_resource_metadata()
            self.assertEqual(len(resource), 2)

    def test_class_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_classes.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            resource_classes = self.session.get_class_metadata(resource="Agent")
            self.assertEqual(len(resource_classes), 8)

    def test_table_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_table.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            table = self.session.get_table_metadata(resource="Property", resource_class="1")

        self.assertEqual(len(table), 162)

    def test_lookup_type_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_lookup.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            lookup_values = self.session.get_lookup_values(resource="Property", lookup_name="1_2")

        self.assertEqual(len(lookup_values), 9)

    def test_alternative_lookup_type_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_lookup2.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            lookup_values = self.session.get_lookup_values(resource="Property", lookup_name="mls_cooling")

        self.assertEqual(len(lookup_values), 4)

    def test_object_metadata(self):
        with open("tests/rets_responses/STANDARD-XML/GetMetadata_objects.xml") as f:
            contents = "".join(f.readlines())
        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/GetMetadata.ashx",
                body=contents,
                status=200,
            )
            object_metadata = self.session.get_object_metadata(resource="Agent")

        self.assertEqual(len(object_metadata), 1)


class LoginTester(unittest.TestCase):
    def test_login(self):
        expected_capabilities1 = {
            "GetMetadata": "http://server.rets.com/rets/GetMetadata.ashx",
            "GetObject": "http://server.rets.com/rets/GetObject.ashx",
            "Login": "http://server.rets.com/rets/Login.ashx",
            "Logout": "http://server.rets.com/rets/Logout.ashx",
            "PostObject": "http://server.rets.com/rets/PostObject.ashx",
            "Search": "http://server.rets.com/rets/Search.ashx",
            "Update": "http://server.rets.com/rets/Update.ashx",
        }

        # This response's relative URLs include a vendor X- capability, which belongs here
        # alongside the standard transactions rather than among the login details.
        expected_capabilities2 = {
            "GetMetadata": "http://server.rets.com/rets/GetMetadata.ashx",
            "GetObject": "http://server.rets.com/rets/GetObject.ashx",
            "Login": "http://server.rets.com/rets/Login.ashx",
            "Logout": "http://server.rets.com/rets/Logout.ashx",
            "Search": "http://server.rets.com/rets/Search.ashx",
            "X-Selector": "http://server.rets.com/rets/selector",
        }

        with open("tests/rets_responses/Login.xml") as f:
            contents = "".join(f.readlines())

        with open("tests/rets_responses/Logout.html") as f:
            logout_contents = "".join(f.readlines())

        with open("tests/rets_responses/Errors/Login_no_host.xml") as f:
            no_host_contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login.ashx",
                body=contents,
                status=200,
            )
            s = Session(
                login_url="http://server.rets.com/rets/Login.ashx",
                username="retsuser",
                version="1.5",
            )
            s.login()

            self.assertEqual(s.capabilities, expected_capabilities1)
            self.assertEqual(s.version, "1.5")

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login.ashx",
                body=contents,
                status=200,
            )
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Logout.ashx",
                body=logout_contents,
                status=200,
            )
            with Session(
                login_url="http://server.rets.com/rets/Login.ashx",
                username="retsuser",
                version="1.7.2",
            ) as s:
                # I logged in here and will log out when leaving context
                pass

            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login_no_host.ashx",
                body=no_host_contents,
                status=200,
                headers={"RETS-Version": "RETS/1.7.2"},
            )
            s1 = Session(
                login_url="http://server.rets.com/rets/Login_no_host.ashx",
                username="retsuser",
                version="1.5",
            )
            s1.login()

            self.assertDictEqual(s1.capabilities, expected_capabilities2)
            self.assertEqual(s.version, "1.7.2")

    def test_login_with_action(self):
        with open("tests/rets_responses/Login_with_Action.xml") as f:
            action_login = "".join(f.readlines())

        with open("tests/rets_responses/Action.xml") as f:
            action_response = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com/rets/Login_with_Action.ashx",
                body=action_login,
                status=200,
            )
            resps.add(
                resps.GET,
                "http://server.rets.com/rets/Action.ashx",
                body=action_response,
                status=200,
            )

            s2 = Session(
                login_url="http://server.rets.com/rets/Login_with_Action.ashx",
                username="retsuser",
                version="1.5",
            )
            s2.login()
            self.assertIn("Action", list(s2.capabilities.keys()))

    def test_port_added_to_actions(self):
        with open("tests/rets_responses/Login_relative_url.xml") as f:
            contents = "".join(f.readlines())

        with responses.RequestsMock() as resps:
            resps.add(
                resps.POST,
                "http://server.rets.com:9999/rets/Login.ashx",
                body=contents,
                status=200,
            )
            s = Session(
                login_url="http://server.rets.com:9999/rets/Login.ashx",
                username="retsuser",
                version="1.5",
            )
            s.login()

            for cap in s.capabilities.values():
                parts = urlparse(cap)
                self.assertEqual(parts.port, 9999)

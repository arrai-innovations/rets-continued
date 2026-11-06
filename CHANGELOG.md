# RETS Changelog

## Unreleased

* **Breaking:** drop support for Python 3.10, which reached its end of life in October 2026. The package now requires Python 3.11 or later.
* **Breaking:** return COMPACT-DECODED wildcard metadata as a dict of lists keyed by name, the same shape as STANDARD-XML, rather than one flat list of every name's rows. A wildcard result therefore keeps its shape when the session switches to STANDARD-XML because the server rejects COMPACT-DECODED. Each row still carries its `Resource`, `Class` or `Lookup`, so code that iterated the list can read the same rows from the dict's lists instead. Requests without a wildcard still return a list. `CompactMetadata.parse()` now returns a list or dict rather than a generator, and takes the requested `meta_id`.
* Preserve every lookup's values in wildcard STANDARD-XML metadata requests, rather than reducing the result to a list of lookup names.
* Work out each auto-offset from the rows the current search has returned, rather than from the search parser's running total. A `search_parser` given to the Session is shared by every search, so its total took in earlier searches' rows, and a later search that followed a truncated response skipped that many records.
* Read COMPACT METADATA-SYSTEM fields independently of each other, accept the mixed-case `<System>` element, and read comments from the sibling `COMMENTS` element.
* Recognize "X-" prefixed vendor capabilities in the login response: an "X-" line whose value is a URL or an absolute path, such as `X-Selector=/rets/selector`. Other "X-" lines, such as `X-SessionTimeout=30`, stay among the login details.
* Tolerate responses missing a Content-Type header, empty search rows, and empty delimiters.
* Validate search arguments when `search()` is called, rather than when its results are first iterated.
* Raise `HTTPException` with the actual status code for refused requests, instead of reporting every 400 as a 401 `NotLoggedIn`.
* Split COMPACT-DECODED metadata rows on tabs, so that values containing spaces and empty fields stay in their own columns.
* Cache metadata responses per format, so that falling back to STANDARD-XML no longer re-reads earlier COMPACT-DECODED responses with the wrong parser, and never cache a response that failed to parse.
* Key wildcard STANDARD-XML class, table and object metadata by resource or class name, instead of failing with a `KeyError` on the missing `Lookup` attribute. Each name now always maps to a list, even when it has a single entry.
* Stop auto-offsetting when the server truncates a search response that holds no rows, rather than requesting the same page forever, and follow truncated searches made with `limit=None` instead of failing with a `TypeError`.
* Honour `follow_redirects`, which was previously ignored so that redirects were always followed. When it is `False`, a redirect raises `HTTPException` naming where the server pointed, instead of handing the redirect body to the parsers.
* Accept numeric strings in `$gte` and `$lte` search filters, which passed validation and then failed to format, and report any non-numeric value, such as `None`, as a `ValueError` rather than a `TypeError`.
* **Security:** only fall back from digest to basic authentication at login when the login URL uses https. Basic authentication sends the password unencrypted, so over plain http the login now fails with `NotLoggedIn` instead. Servers that only accept basic authentication over http need `http_auth="basic"` passed to the Session explicitly.
* Fill in the reply code, reply text, row count and DMQL in debug log messages, which were logged as unformatted placeholders.
* Split multipart GetObject responses at exactly the line breaks that belong to each delimiter, so binary objects ending in CR or LF bytes are no longer truncated, and read part headers separated by bare LFs, which previously left `content_id`, `object_id` and `location` empty.
* Declare the setuptools build backend in pyproject.toml, so builders no longer fall back to the legacy backend, and uv installs the project into its environment rather than treating it as a virtual project.
* Declare the MIT license in the package metadata.
* Reword the `MissingVersion` message, which was missing spaces and blamed the server: the version must be passed to the Session for user agent authentication, since the login request already needs it.
* When a `with Session(...)` block raises and logging out then fails as well, raise the block's error rather than the logout's, and log the logout failure as a warning.
* Treat logging out as done when the server's login response offers no Logout capability, instead of raising `NotLoggedIn`, which made every `with Session(...)` block against such a server fail on exit. Logging out before logging in still raises.
* Forget the login once logging out succeeds: the session drops its capabilities, session ID and cookies, so later requests raise `NotLoggedIn` instead of using a session the server has ended, and leaving a `with Session(...)` block that already logged out no longer logs out again.
* Log a warning, once per session, when basic authentication is about to send the password to a plain http URL. This covers an explicit `http_auth="basic"` with an http login URL, and a session that fell back to basic over an https login and is then given http URLs for other transactions.
* Hash the RETS version in the user agent authentication digest exactly as the `RETS-Version` header sends it, such as `RETS/1.7.2`, as section 3.10 of the RETS spec requires. The digest previously dropped the `RETS/` prefix, so it could not match the digest a server computes from the spec.
* Stream search results. The search parser read the whole response into memory before yielding its first row, and kept every parsed row attached to the document until the end. It now parses each chunk as it arrives and lets each row go once it has been yielded. A search error reply code is raised as soon as the response opens, before any rows, and a search the caller stops iterating early closes its connection.
* Give the `RETSException` raised for a search error reply code its `reply_code` and `reply_text`, like every other `RETSException`, so callers can tell search errors apart. Its message is now the server's reply text, without the "RETS Error <code>:" prefix.
* Give `HTTPException` a `status_code` attribute holding the HTTP status the server answered with, so callers no longer have to read it out of the message. It is set by a keyword-only argument, so `HTTPException` still takes the same positional arguments as before.
* Let a `RETSException` without reply text be printed: its `str()` and `repr()` returned `None`, which raised `TypeError` and left tracebacks showing `<exception str() failed>`. It now falls back to a message naming the reply code. Its `repr()` is the standard `RETSException('text', 'code')` form rather than the bare reply text.
* Raise `ValueError` from `search()` when the STANDARD-XML format is requested without a `search_parser`. The built-in parser only reads COMPACT results, so such a search used to return no rows without any error, however many the server sent.
* Return a dict of lists from every STANDARD-XML wildcard metadata request, even one that matches a single name, which used to come back as a plain list.
* Resume a truncated search at the record after the last one received. RETS numbers records from 1, but a search started without an offset resumed at `Offset` equal to the number of rows received, so the server sent the last row of each page again.
* Leave the caller's search filter unchanged when formatting `$in` and `$nin` values. Their lists were replaced in the filter dict with formatted copies, so any dates in them came back as strings.
* Format `$neq` datetime and time values the way the other filters do, such as `2026-01-02T03:04:05`. They were sent as Python's `str()` of the value, `2026-01-02 03:04:05.600000`, which is not the RETS date-time format.
* Stop keeping metadata responses when `cache_metadata` is `False`. They were stored anyway, and never read back, so a session that turned caching off still held every metadata response it had received.
* Add the `RETS/` prefix to a version given to the Session as a bare number, such as `1.7.2`, so that the `RETS-Version` header and the user agent digest carry `RETS/1.7.2`. `Session.version` now holds the prefixed form too.
* Give `MaxrowException` a message saying the server truncated the search response, rather than only the row count.
* Report the RETS reply code from a response that carries one with an HTTP error status, as a `RETSException`, instead of an `HTTPException` that only gives the status. Such a reply again moves metadata requests over to STANDARD-XML when the server rejects COMPACT-DECODED, and a search's "No Records Found" again returns no rows.
* Close a response the session refuses because of its status, so a streamed search that fails, such as with a 401, releases its connection rather than holding it until garbage collection.
* Explain a login refused over http by what the server's challenge says. The message used to blame digest authentication and suggest basic for any 400 or 401, including wrong credentials. It now points to basic only when the server accepts nothing else, reports wrong credentials when the server offered digest, and otherwise gives the status code and suggests checking the credentials first.
* Count a logout the server refuses with a 401 as logged out, since the server has already ended the session, such as after its timeout. The session forgets the login and `logout()` returns `True`, so a `with Session(...)` block whose session expired no longer fails on exit, later requests raise `NotLoggedIn` before reaching the server, and leaving a block that already logged out does not try again. Other logout failures, such as a 500 or a timeout, still raise and keep the login so logging out can be retried.
* Count only the truncated response's own rows in `MaxrowException.rows_returned`. It held the parser's running total, which takes in every earlier page and search when a `search_parser` is reused. The parser's `parsed_rows` attribute is still that running total.
* Read STANDARD-XML metadata responses that hold no entries. A wildcard that matches nothing returns an empty dict, a metadata element with no entries, such as a lookup without values, returns an empty list, or maps its name to one in a wildcard result, and an empty `METADATA` element no longer fails with an `AttributeError`. A response missing the requested metadata element entirely returns no entries, as COMPACT-DECODED does, where it failed with a `ParseError` or an `AttributeError`.
* Ignore the preamble of a multipart GetObject response, the text a server may send ahead of the first delimiter, which was returned as an extra object with every field `None`. Text there that has a `Content-ID`, `Object-ID` or `Content-Type` header is still read as the first object, for servers that leave out the first delimiter.
* Key a STANDARD-XML wildcard result by the part of the ID that holds the `*`. A wildcard resource, as in `get_lookup_values('*', 'Status')` or `get_table_metadata('*', 'RES')`, raised `ParseError` whenever two resources shared a lookup or class name, since the result was always keyed by that name. It is now keyed by resource, and a wildcard in both parts returns a dict of dicts, keyed by resource and then by lookup or class. `StandardXMLMetadata.parse()` takes the requested `meta_id` to tell which part holds the wildcard.
* Read a COMPACT-DECODED metadata element that has no attributes and no entries, such as `<METADATA-LOOKUP_TYPE/>`, as empty, rather than failing with an `AttributeError`. In a wildcard response, such an element no longer fails the entries of the others.
* Log out when a `with Session(...)` block fails to start because the Action transaction failed after the login succeeded. The block never ran, so leaving it did not log out, and the session stayed open on the server until it timed out. A failed logout is logged as a warning, and the Action failure is raised. Calling `login()` directly still leaves the session logged in.
* Name only the authentication methods actually tried when the server refuses a login. The message always said "in basic or digest", even for `http_auth="basic"`, where digest is never tried. It now says "using basic authentication" in that case, and "using digest or basic authentication" only after falling back from digest.
* Read RETS reply codes the same way in every response: from the `RETS` element, from a `RETS-STATUS` element inside it, and from a `RETS-STATUS` element sent as the whole response. Login, metadata, GetObject and search responses ignored a `RETS-STATUS` inside `RETS`, so an error reported there went unnoticed, and a `RETS-STATUS` response reporting success failed with a `KeyError`. A search response without any reply code no longer raises a `RETSException` without a code. Every `RETS-STATUS` element is checked when a response repeats it, and one anywhere else, such as inside an HTML page, is not taken for a reply code.
* Read an XML error part in a multipart GetObject response up to the end of its root element, rather than up to the first `/>`. A reply code in a `RETS-STATUS` inside `RETS`, such as an object not found, was cut off mid-document and failed with an `ExpatError` instead of being skipped or raised. Characters some servers send after the XML are still dropped.
* Read the headers of each part in a multipart GetObject response in any case, as header names are case-insensitive. A part sending `content-id` or `content-type` came back with its `content_id`, `object_id`, `content_type` and `location` empty, and an XML error part with lower-case headers was returned as an object instead of having its reply code checked.
* Read a metadata response whose `RETS` element has no attributes or children, such as `<RETS/>` or `<RETS>text</RETS>`, as holding no metadata, rather than failing with an `AttributeError`. Both formats return no entries, as COMPACT-DECODED already did for a `RETS` element with only a reply code.
* Raise `ParseError` for a COMPACT-DECODED METADATA-SYSTEM response without a usable `SYSTEM` element, as STANDARD-XML does. `get_system_metadata()` failed with an `IndexError` instead, or an `AttributeError` when the `SYSTEM` element held only whitespace. Comments nested inside `SYSTEM` are also read when spelled `COMMENTS`, not only `Comments`.
* End an auto-offset search quietly, logging a warning, when the server refuses a page it requested itself because the offset is past the end. Some servers, such as Flex MLS, truncate a page that ends at the last record and then reject the next offset with "Offset exceeds available rows.", which was raised after every row had been returned. Such an error on the first page, whose offset the caller chose, is still raised, as is any other error on a later page. Document `auto_offset` in the README, and correct its paging example to resume at record 10,001.

## 2.0.1

* Parse COMPACT-DECODED metadata responses that contain more than one metadata element, such as wildcard lookups.

## 2.0.0

Revive the upstream code and modernize for current Python releases.

* Update copyright notices to include Arrai Innovations.
* Remove Python 2.7 compatibility shims.
* Convert the project settings, including build and testing, to pyproject.toml.
* Switch from nose to pytest.
* Address deprecation warnings in the tests.
* Lint and format using ruff.
* Switch from CI to CircleCI.
* Update documentation.
* Confirmed support for Python 3.10 through 3.14.

## 1.0.0
* Major release. Search results return generator instead of list for lower-footprint processing. Possibly a breaking change depending upon usage.
* Support Python 3.8

## 0.4.11

* Falls back to basic auth if digest returns 401 response on login

## 0.4.10

* Handles wildcard lookup_names for Standard XML responses.

## 0.4.9

* Handles `Lookup` and `LookupType` responses from RETS metadata requests.
* Adding support for python 3.7
* Removing support for python 3.3

## 0.4.8

* Custom search results parser allowed.

## 0.4.7

* Catching the RETS-STATUS when returned from server and parsing response code and text.

## 0.4.6

* Allowing various query types through the search method
* Allowing specified response format (COMPACT-DECODED, COMPACT, or STANDARD-XML)
* Flag for if the query uses system names (default) or standard names
* Deprecated support for Python 3.3 due to setuptools deprecation

## 0.4.5

* If a non-standard port is used during the login, that port is used for all capability requests if the capability URI is supplied and not a URL.

## 0.4.4

* Allowing custom session id cookie name viw the session_id_cookie_name parameter in the Session object

## 0.4.3

* Multipart Python3 images bug fixed

## 0.4.2

* Removing cached metadata responses if the parsing raises an exception.

## 0.4.1

* Not setting the RETS-Version in the header by default anymore. Allowin the login's response to set it.

## 0.4.0

* full Python 3 compatibility

## 0.3.8

* Multipart responses with XML and noncomplient rets functions.

## 0.3.7

* Addressed potential unicode -> ascii issue in Python2

## 0.3.6

* Fixed Lookup -> LookupType in XML example and parsing. Doing the metadata LOOKUP-TYPE now functions as expected

## 0.3.5

* Forcing dict and OrderdDict types when sending search_filters to the session.

## 0.3.4

* Allowing users to specify the xml format when initializing the session with `metadata_format`

## 0.3.3

* Minor bug fix

## 0.3.2

* Checking the RETS response code with the login parser as well.

## 0.3.1

* Bug fix for GET requests to RETS servers.
* Minor documentation update.

## 0.3.0

* Search method now returns a list instead of an iterator. This allows us to catch maxrows internally and automatically

make subsequent reqeusts with offsets rather than forcing the client to catch and adapt. As the size of the reply is often
 small, getting even ~32k listings of data was >300k in memory, this results should not affect the memory footprint.

* Added the `auto_offset` parameter for Session.search method. Defaults to True for making subsequent search requests

if the RETS server truncated the number of requested listings.

## 0.2.0

* Significatn changes to exception raising. No more InvalidFormat exception. ValueErrors are more appropriate for

input errors and RETSExceptions for consistently handling non-zero reply codes from the RETS Server. The RETSException
now has reply_code and reply_text parameters.

## 0.1.3

* get_object requests with location=1 now parse the response appropriately

## 0.1.2

* getObject dictionaries now include md5 fingerprints as content_md5

## 0.1.1

* Multipart image downloads working in Python2. Still not working in Python3

## 0.1.0

* No results continues generator

## 0.0.12

* Action capability called correctly
* RETS Version no longer strips RETS/ prematurely
* Added additional INVALID_VERSION reply code for cathing STANDARD_XML
* Minor Bug Fixes

## 0.0.8

* Removing lxml from requirements
* Parsing STANDARD-XML
* Removing need to manage RETS version
* User Agent Auth

## 0.0.7

* Streaming search results

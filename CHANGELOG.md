# RETS Changelog

## Unreleased

* Preserve every lookup's values in wildcard STANDARD-XML metadata requests, rather than reducing the result to a list of lookup names.
* Start each search's auto-offset at zero, so repeated searches through a shared search parser no longer skip rows.
* Read COMPACT METADATA-SYSTEM fields independently of each other, accept the mixed-case `<System>` element, and read comments from the sibling `COMMENTS` element.
* Recognize "X-" prefixed vendor capabilities in the login response.
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

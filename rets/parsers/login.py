from urllib.parse import urlparse

from rets.parsers.base import Base


class OneXLogin(Base):
    def __init__(self):
        """Login Parser"""
        self.capabilities = {}
        self.details = {}
        self.headers = {}
        self.valid_transactions = [
            "Action",
            "ChangePassword",
            "GetObject",
            "Login",
            "LoginComplete",
            "Logout",
            "Search",
            "GetMetadata",
            "ServerInformation",
            "Update",
            "PostObject",
            "GetPayloadList",
        ]

    def parse(self, response):
        """
        Parse the login xml response
        :param response: the login response from the RETS server
        :return: None
        """
        self.headers = response.headers
        self.analyze_xml_response(response)

        lines = response.text.split("\r\n")
        if len(lines) < 3:
            lines = response.text.split("\n")

        for line in lines:
            line = line.strip()

            name, value = self.read_line(line)
            if name:
                if name in self.valid_transactions or self.is_extension_capability(name, value):
                    self.capabilities[name] = value
                else:
                    self.details[name] = value

    @staticmethod
    def is_extension_capability(name, value):
        """
        Whether a login line is a vendor's extension transaction. Vendors prefix their own names with "X-", for
        transactions and for other details alike, so only a line whose value is a URL counts as a capability.
        :param name: The name on the line
        :param value: The value on the line
        :return: bool
        """
        if not name.startswith("X-"):
            return False
        url = urlparse(value)
        # A path relative to the server, as standard capabilities may also be given, or a full URL.
        return value.startswith("/") or (url.scheme in ("http", "https") and bool(url.netloc))

    @staticmethod
    def read_line(line):
        """Reads lines of XML and delimits, strips, and returns."""
        name, value = "", ""

        if "=" in line:
            name, value = line.split("=", 1)

        return [name.strip(), value.strip()]

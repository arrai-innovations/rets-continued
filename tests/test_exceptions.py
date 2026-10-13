import pickle
import traceback
import unittest

from rets.exceptions import HTTPException
from rets.exceptions import RETSException


class RETSExceptionTester(unittest.TestCase):
    """RETSException can always be printed, and keeps its reply code and text"""

    def test_message_is_the_reply_text(self):
        error = RETSException("Invalid Format", "20513")

        self.assertEqual(str(error), "Invalid Format")
        self.assertEqual(error.args, ("Invalid Format", "20513"))

    def test_without_reply_text(self):
        # str() and repr() used to return None here, which raised TypeError instead.
        self.assertEqual(str(RETSException(reply_code="20203")), "The RETS server returned reply code 20203.")
        self.assertEqual(str(RETSException()), "The RETS server reported an error.")
        self.assertEqual(repr(RETSException()), "RETSException(None, None)")

    def test_traceback(self):
        try:
            raise RETSException(reply_code="20203")
        except RETSException:
            last_line = traceback.format_exc().splitlines()[-1]

        self.assertEqual(last_line, "rets.exceptions.RETSException: The RETS server returned reply code 20203.")

    def test_repr(self):
        self.assertEqual(repr(RETSException("Invalid Format", "20513")), "RETSException('Invalid Format', '20513')")

    def test_pickle(self):
        error = pickle.loads(pickle.dumps(RETSException(reply_text="Invalid Format", reply_code="20513")))  # noqa: S301

        self.assertEqual((error.reply_text, error.reply_code), ("Invalid Format", "20513"))
        self.assertEqual(str(error), "Invalid Format")


class HTTPExceptionTester(unittest.TestCase):
    def test_pickle(self):
        error = pickle.loads(pickle.dumps(HTTPException("Server Error", status_code=500)))  # noqa: S301

        self.assertEqual(error.status_code, 500)
        self.assertEqual(str(error), "Server Error")

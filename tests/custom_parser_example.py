import xmltodict

from rets.exceptions import RETSException


class CreaStandardXParser:

    def generator(self, response):
        rets = xmltodict.parse(response.content)["RETS"]
        reply_code = rets["@ReplyCode"]
        reply_text = rets["@ReplyText"]
        if reply_code != "0":
            raise RETSException(reply_text, reply_code)
        results = rets["RETS-RESPONSE"]["PropertyDetails"]
        if isinstance(results, dict):
            yield results

        else:
            yield from results

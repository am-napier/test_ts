import json
from my_logger import logger

class Factors():
    def __init__(self, factor_file):
        self._content = {}
        with open(factor_file) as jsonfp:
            self._content = json.load(jsonfp)
        logger.info(f"factors created ok {len(self._content)}")

    def get(self, name):
        try:
            return self._content[name][:]
        except KeyError:
            return [1]
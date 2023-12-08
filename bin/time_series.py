from my_logger import logger

# ===================================================================
# tech debt might be here, do we need this class, what's it doing ?
# ===================================================================
class TimeSeries():
    def __init__(self, name, headers, start):
        self._data_ = {} # dict of str(date) and dict for the series properties
        self._ts_ = [] # array of time stamps in increasing order
        self._name_ = name
        self._headers_ = ["datetime"]
        self._headers_.extend(headers)
        self._lastUpdate = start


    def update(self, time, content):
        # does _data_ contain an item for this observation?
        tstr = str(time)
        logger.debug("TS.update for %s called with %s" % (self._name_, tstr))
        try:
            # this works iff the record exists already, if it doesn't
            rec = self._data_[tstr]
            for k, v in content.items():
                rec[k] = content[v]
        except KeyError:
            rec = content.copy()  #don't use the orginal incase the caller changes it
            rec["datetime"] = str(time)
            self._data_[tstr] = rec
            self._ts_.append(time)

        self._lastUpdate = time

    def getLastUpdate(self):
        return self._lastUpdate


    # return a tuple of observations in timeseries order (date, prop1, prop2, ... )
    # until I fix the dateSort this will only work if you insert the series in the correct order
    def get(self):
        # sort the list of _ts_
        res = []
        self._ts_.sort()
        for time in self._ts_:
            row = self._data_[str(time)]
            res.append(row)
        return res
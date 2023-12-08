'''
@todo: write more complete docs.  This was a 10 minute exercise and deserves more time to get it right.

Create a series of data with some pattern in it.  
The pattern follows a factor set based on daily usage.  
Allows weekly deviation to the daily pattern.
This is all configured using the input files
1. ../cfg/factors.cfg - stores factors for the daily patterns.  Each factor series is an array that apportioned to the day linearly, ie if there are 24 items there is one per hour, 288 is one per 5 mins.  If data is required between two points it is calcuated using a linear interpolation 
2. ../cfg/tsdgen.json - stores the series description with max and min values, the type of factors for the day and the week plus the patterns used to vary the data.  Most importantly this file also stores the last update timestamps for the series and updates these after every poll

The patterns used will become active during their window (see times) on the days (see days) specified (0 is sunday) for the duration (yes its called duration) using a probability to determine how likely the pattern will start during its window.

For example if I have times.start=10:00 and times.end=12:00 with days=[1,2,3,4,5] and a probability of 0.1 then there is a 10% chance the pattern will start between 10am for 2 hrs on each poll cycle where it is not running (based on the active flag) during the work days (specified  as 1-5 ie Mon-Fri)

supports 3 patterns (types) now
random - makes spikes when the pattern is active between max and min
regular - changes series by factor or absolute value
trend - saw tooth patterns that increase by a factor/absolute value each cycle while active.

If the Last* properties are missing from the file for any series it will generate ndays with of history.

This programe can be run directly from the command line ie

./bin/make_series.py -bq -n 60 tsdgen.json

the tsdgen.json file is located in ./cfg/

'''

import sys, argparse, csv, io, random, json, time, os
from datetime import datetime, timedelta
from my_logger import logger

from series import SeriesSpec, STD_TIME_FMT
from factors import Factors
import requests
import urllib3
urllib3.disable_warnings()

'''
this is a sine curve from 0 to 1 with 288 (5 minute) intervals and 40 spaces padding on each end
it represents a daily activity pattern for some daily hours task like an intranet server weblog
from this we'll generate a few different data sets like 
1. the smooth data
2. various degreees of noise added (can be relative or additive)
3. and the noise itself (incase you want to verify)
4. patterns overlaying the series, ie monday 8-9am is 2* or weekday dip from 12-1 of 50%
5. seemingly random patterns such as one off spikes or troughs of varying amplitude and duration

timechart the output data and you can see the different patterns

these patterns are defined in the input file

run make_series.py -h


'''


FILE_TIME_FMT = "%Y%m%d_%H%M%S"


class KVStore():
    def __init__(self, server, session_id):
        self.uri = f"https://{server}/servicesNS/nobody/test_ts/storage/collections/data/test_ts_input_status"
        self.headers = {"Authorization" : f"Splunk {session_id[0]}", "Content-Type": "application/json"}
        logger.info(f"KVStore::init url:{self.uri}, headers:{self.headers}")
        self.auth=None

    def setAuth(self, user, pswd):
        self.auth=(user, pswd)
        self.headers = {"Content-Type": "application/json"}

    def read(self, key):
        '''
        READ
        https://localhost:8089/servicesNS/nobody/test_ts/storage/collections/data/test_ts_input_status/<<key>>
        '''
        r = requests.get(f"{self.uri}/{key}", headers=self.headers, auth=self.auth, verify=False)
        if r.status_code == 200:
            return json.loads(r.text)["value"]
        elif r.status_code == 404:
            return { "LastRun": None }
        else:
            logger.error(f"KVStore Read Failed: {r.status_code}")
            raise Error(f"KVStore Read Failed: {r.status_code}")


    def write(self, key, cfg, do_insert):
        '''
        Write
            -X POST https://{server}/servicesNS/nobody/test_ts/storage/collections/data/state_store -d '{"_key": "<<key>>", "modtime": 12345, "config": {"a":1, "b":2}}'

            '{"_key": "123456", "field1": "value1", "field2": "value2"}'
        '''
        logger.info(f"KVStore write key: {key} cfg: {json.dumps(cfg)}")
        payload = {
                  "value" : cfg,
                  "modtime" : int(datetime.utcnow().timestamp()),
        }
        if do_insert:
            logger.info("KVStore insert")
            self.uri = self.uri
            payload["_key"] = key
        else:
            logger.info("KVStore update")
            self.uri = f"{self.uri}/{key}"

        cfg["LastRun"] = datetime.strftime(datetime.now(), "%F %T")
        logger.info(f"Posting {payload} to {self.uri}")
        r = requests.post(self.uri, auth=self.auth, headers=self.headers, verify=False, data=json.dumps(payload))

        if r.status_code <= 201:
            logger.info(f"KVStore write OK {r.text}")
            return r.text
        else:
            logger.error(f"KVStore Write Failed: {r.status_code}")
            raise RuntimeError(f"KVStore Write Failed: {r.status_code}")

# ===================================================================
# parse user input, gather data and output results
# ===================================================================
def main(argv):

    p = argparse.ArgumentParser(description="Make some fake data for testing")

    p.add_argument("pattern", help="file name to read the series definition from, relative to $APP_HOME/cfg/", type=str)
    p.add_argument("host", help="name of host to write these metrics for", type=str)

    p.add_argument("-n", "--ndays", help="number of days for history", type=int, default=30)
    p.add_argument("-v", "--verbose", help="add extra fields to output", action="store_true", default=False)
    p.add_argument("-f", "--factors", help="name of factor file, referenced from $APP_HOME/cfg", type=str, default="factors.json")
    p.add_argument("-s", "--splunk", help="Splunk host:port", type=str, default="localhost:8089")
    p.add_argument("-u", "--user", help="Splunk username", type=str, default=None)
    p.add_argument("-p", "--password", help="Splunk password", type=str, default=None)


    args = p.parse_args(argv)

    logger.info(f"\n\n--------------------------\nRun Start: {argv}\n\n")

    kvstore = KVStore(args.splunk, sys.stdin.readlines())
    if args.user is not None:
        kvstore.setAuth(args.user, args.password)

    last_run_state = kvstore.read(args.host)
    logger.info(f"kvstore record: {json.dumps(last_run_state)}")
    do_insert = last_run_state["LastRun"] is None

    cwd = os.path.dirname(os.path.join(os.getcwd(), __file__))+"/../cfg/"
    logger.info("cwd is "+cwd)

    last_update = run(pattern_file=cwd+args.pattern, host=args.host, ndays=args.ndays, factor_file=cwd+args.factors, verbose=args.verbose, state=last_run_state)    
    last_run_state["LastRun"] = datetime.strftime(last_update, STD_TIME_FMT)
    kvstore.write(args.host, last_run_state, do_insert)

    logger.info("Exit")

 
'''
'''
def run(pattern_file, host, factor_file, ndays, verbose, state):

    logger.info(f"Pattern File: {pattern_file}, host: {host}, ndays: {ndays}, factors: {factor_file}, verbose: {verbose}" )
    
    
    #dataset = DataSet(ts_name=host, file=pattern_file, factors=Factors(factor_file), verbose=verbose, state=state)
    with open(pattern_file) as fp:
        # state gets updated by SeriesSpec as it generates data
        series = SeriesSpec(json.load(fp), host, Factors(factor_file), state)
        ts = series.generate(ndays, verbose)
        for s in ts.get():
            print(json.dumps(s))

        return ts.getLastUpdate()


if __name__ == '__main__':
    main(sys.argv[1:])

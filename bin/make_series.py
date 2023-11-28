
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
from datetime import datetime as dt, timedelta as td
import logging, logging.handlers
import splunk

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

STD_TIME_FMT = "%Y-%m-%d %H:%M:%S"
FILE_TIME_FMT = "%Y%m%d_%H%M%S"

def setup_logging():
    logger = logging.getLogger('splunk.test_ts')
    SPLUNK_HOME = os.environ['SPLUNK_HOME']

    LOGGING_DEFAULT_CONFIG_FILE = os.path.join(SPLUNK_HOME, 'etc', 'log.cfg')
    LOGGING_LOCAL_CONFIG_FILE = os.path.join(SPLUNK_HOME, 'etc', 'log-local.cfg')
    LOGGING_STANZA_NAME = 'python'
    LOGGING_FILE_NAME = "test_ts.log"
    BASE_LOG_PATH = os.path.join('var', 'log', 'splunk')
    LOGGING_FORMAT = "%(asctime)s %(levelname)-s PID:%(process)d\t%(module)s:%(lineno)d - %(message)s"
    splunk_log_handler = logging.handlers.RotatingFileHandler(os.path.join(SPLUNK_HOME, BASE_LOG_PATH, LOGGING_FILE_NAME), mode='a')
    splunk_log_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
    logger.addHandler(splunk_log_handler)
    splunk.setupSplunkLogger(logger, LOGGING_DEFAULT_CONFIG_FILE, LOGGING_LOCAL_CONFIG_FILE, LOGGING_STANZA_NAME)
    return logger
logger = setup_logging()


class Factors():
    def __init__(self):
        self._content = {}

    def load(self, file):
        with open(file) as jsonfp:
            self._content = json.load(jsonfp)

    def get(self, name):
        try:
            return self._content[name][:]
        except KeyError:
            return [1]

FACTORS = Factors()		# load it in main with the args passed

# ===================================================================
# utility function to extract an option from the input file (or any other json/dict)
# ===================================================================
def getOption(json, tag, default=""):
    try:
        return json[tag]
    except:
        return default

# given a CSV string split it into an array, ie pass "1,2,3" and get [1,2,3] back
def parseArr(str):
    return json.loads("[%s]" % str)

# ===================================================================
# parse user input, gather data and output results
# ===================================================================
def main(argv):

    p = argparse.ArgumentParser(description="Make some fake data for testing")

    p.add_argument("series", help="file name to read the series definition from, relative to $APP_HOME/cfg/", type=str)

    p.add_argument("-n", "--ndays", help="number of days for history", type=int, default=30)
    p.add_argument("-v", "--verbose", help="add extra fields to output", action="store_true", default=False)
    p.add_argument("-x", "--nostate", help="don't store the state of the file once finished - for testing", action="store_true", default=False)
    p.add_argument("-c", "--clean", help="ignore the file timestamps", action="store_true", default=False)
    p.add_argument("-o", "--output", help="output mode text or json (default)", type=str, default="json")
    p.add_argument("-f", "--factors", help="name of factor file, referenced from $APP_HOME/cfg", type=str, default="factors.json")


    args = p.parse_args(argv)

    logger.info(f"Run Start: {argv}")
    session = sys.stdin.readlines()
    logger.info(f"nowt xx cw{session}!")

    cwd = os.path.dirname(os.path.join(os.getcwd(), __file__))+"/../cfg/"
    logger.info("cwd is "+cwd)

    FACTORS.load(cwd+args.factors)

    if args.output=="text" :
        print("host\tstart\tfx 0.01\tadjusted\traw\n")

    # rework this for batch updates vs server
    nextUpdate = run(cwd+args.series, args.ndays, args.output, nostate=args.nostate, clean=args.clean, verbose=args.verbose)

    logger.info("Exit for batch mode")

 
'''
Program operates in two ways:
1. Batch load to generate a file from date1 to date2, when it is finished it will exit
2. Realtime datagen that feeds events from the last run (based on stored state) upto the current time then sleeps for 5 mins before feeding the next event
   it will continue doing this until user interupts the process.

So when the program starts we need to test if a batch gen is needed, ie it hasn't run for while.  This is done by looking at the last update time 
from the state file and comparing it with system clock.  If it is older then gen data upto the current time and then run realtime if 
batch was not specified.
'''
def run(infile: object, ndays: object, outMode: object, nostate: object = True, clean: object = False, verbose = False) -> object:

    logger.info("File: %s, ndays: %d, nostate:%d" % (infile, ndays, nostate) )

    dataset = DataSet(infile, clean, verbose)
    fileEnd = ".csv"
    doUpdate=False
    nextUpdate = dt.now()+td(days=10000) # make sure at least one iteration past ts.getLastUpdate happens

    for ts in dataset.generateSeries(ndays):

        for s in ts.get():
            doUpdate = True  # can update state as there were changes made
            if outMode=="text" :
                print("%s\t%s\t%s\t%s\t%s" % (s["host"], s["datetime"], str(s["f0_01"]), str(s["adjusted"]), str(s["raw"])))
            else:
                print(json.dumps(s))

        nextUpdate = min(nextUpdate, ts.getLastUpdate())

    # only update the state file if changes have been made.
    if doUpdate and not nostate:
        dataset.saveState(False)

    return nextUpdate



'''
This class manages the factor series and allows us to set an arbitrary array of factors and then ask for the
factor by time of day, ie if I have an array with 6 items [0, 1, 2, 3, 4, 5] and say give me the item for the
3599th second of the day it will extract the two values between which this time period falls (0 and 1) and then pro-rata
the difference between them by the time asked, in this case returning 1-0 * 3599/ 4 hours in seconds
'''
class DayFactor():
    def __init__(self, arr=[1]):
        self.setFactors(arr[:])

    def setFactors(self, arr):
        self.data = arr
        self.obs = len(self.data)
        self.span = 86400 / float(self.obs)
        self.data.append(self.data[0]) # add the first point to end to create a circle (flattened)

        logger.info("nobs: %d   span: %f" % (self.obs, self.span))

    '''
    find the value between the two points in self.data, 
    ie if secs is 3605 (01:00:05)
    get the two points either side based on this array and find the mid-point
    secs must be 
    '''
    def get(self, secs):
        i = int((secs % 86400) / self.span)
        # i max's out at self.obs-1, i+1 is safe because of the circle (flattened)
        p1 = self.data[i]
        p2 = self.data[i+1]
        tp1 = i * self.span # time of point 1 in seconds
        d = secs - tp1		# distance from p1 to secs
        #print("p1:%d, p2:%d, tp1:%f, i:%d, d:%f" % (p1, p2, tp1, i, d))

        return p1 + (p2 - p1) * (d/self.span)


# ===================================================================
# Simple factor to create a set of time series objects from a file of JSON
# see ts.sjon.spec (todo: make that file)
# ===================================================================
class DataSet():
    def __init__(self, file, clean, verbose):
        self.file = file
        self.seriesSpec = []
        self.verbose = verbose
        with open(self.file) as jsonfp:
            self._data_ = json.load(jsonfp)
            for name, series in self._data_.items():
                try:
                    if not series['disabled']:
                        raise("foo bad idea, bah! (only do this if the property is false or missing")
                except:
                    self.seriesSpec.append(SeriesSpec(series, name, clean))

    def generateSeries(self, ndays):
        logger.info(" reading input args from "+self.file)
        timeseries = []
        for series in self.seriesSpec:
            timeseries.append(series.generate(ndays, self.verbose))

        return timeseries

    def saveState(self, doBackup=True):
        logger.info(" Writing state object")

        # make a datestamped backup
        if doBackup:
            with open(self.file) as fp:
                with open("%s.bak-%s.json" % (self.file, dt.now().strftime(FILE_TIME_FMT)), "w") as bkfp:
                    bkfp.write(fp.read())
                    bkfp.close()
                fp.close()

        with open(self.file, "w") as fp:
            json.dump(self._data_, fp, indent=4, sort_keys=True)
            fp.close()


# ===================================================================
# This is the time series object
# should be redesigned to make it less rubbish
# ===================================================================
class SeriesSpec():
    def __init__(self, json, name, clean):
        # print "loading series "+name
        self._json_ = json  # any changes made to this object will be persisted when saveState is called on DataSet

        if clean:
            self._json_.pop("LastEnd", None)

        self.name = name
        '''
        self.period is the interval in seconds between obs
        self.periodVar is a variance on the length of the time, it introduces the ability to have non uniform time intervals
        0 is disabled, 0.1 is 10% so if span was 60 the interval would be 54 - 66 seconds
        '''
        try:
            self.period = json["periodicity"]["span"]
            self.periodVar = json["periodicity"]["variance"]
        except KeyError:
            self.period = 300
            self.periodVar = 0

        self.desc = getOption(json, 'desc')
        self.max = json['max']
        self.min = json['min']
        self.datatype = getOption(json, "datatype", "float")
        self.weekdays = parseArr(getOption(json, "weekdays", "1.0,1.0,1.0,1.0,1.0,1.0,1.0"))
        self.noiseFactors = parseArr(json['noise']['value'])
        self.noiseType = json['noise']['type']


        try:
            self.factorSet = json['factorSet']
        except KeyError:
            self.factorSet = "DEFAULT_FACTORS"

        # only supporting integer and float at the mo, integer causes rounding of the generated values
        try:
            self.type = json['type']
        except KeyError:
            self.type = "float"

        # load the patterns
        self.patterns = []
        try:
            for pattern in json['patterns']:
                type = pattern['type']
                if type == "regular" :
                    self.patterns.append(RegularPattern(pattern))
                elif type == "random" :
                    self.patterns.append(RandomPattern(pattern))
                elif type == "trend" :
                    self.patterns.append(TrendPattern(pattern))
                elif type == "break" :
                    self.patterns.append(BreakPattern(pattern))
                elif type == "randombreak" :
                    self.patterns.append(RandomBreakPattern(pattern))
                elif type == "step" :
                    self.patterns.append(StepPattern(pattern))
                else:
                    raise Exception('Balls, bad pattern type! :: '+type)
        except KeyError:
            logger.info("Warning: No patterns defined")

        # get the factor set @todo, we can parameterize this easily now ;)
        self.factors = DayFactor(FACTORS.get(self.factorSet))


    # what was the last datetime point updated, this will be LastEnd, if its blank return one created from ndays
    # this is the point that data gen will start at, ie the last point that we generated
    def getLastObs(self, ndays):
        try:
            logger.info("LastEnd is %s" % (self._json_["LastEnd"]))
            return dt.strptime(self._json_["LastEnd"], STD_TIME_FMT)
        except KeyError:
            logger.info("Error getting LastEnd, using default %d, JSON: %s" % (ndays, str(self._json_)))
            return dt.now().replace(hour=0, minute=0,second=0,microsecond=0) - td(days=ndays)

    def getFactor(self, secs):
        return self.factors.get(secs)

    # want to return an object that specifies the timeseries final value plus a number of its component patterns
    # in a way that allows it to be easily output in a number of formats
    # must be a listin date order
    def generate(self, ndays, verbose):

        start = self.getLastObs(ndays) +  td(seconds=self.period)  # add the next period
        end = dt.now()   #.replace(minute=dt.now().minute/5*5, second=0, microsecond=0)

        logger.info( " *** Running %s from %s to %s " % (self.name, start, end))

        headers = ["raw", "factor", "regular", "adjusted", "weekdayFactor"]
        for n in self.noiseFactors:
            headers.append("noise_"+str(n))
            headers.append("final_"+str(n))

        ts = TimeSeries(self.name, headers, start)
        while start <= end:

            randomT = (0.5 if random.random() > 0.5 else -0.5) * self.periodVar * self.period
            tmp_end = start + td(seconds=(self.period+randomT))

            factor = self.getFactor(start.hour*3600+start.minute*60+start.second)

            weekdayFactor = self.weekdays[start.weekday()]
            maxim = self.min + (self.max-self.min) * weekdayFactor
            # this tops the max value of the series for the day but the min value stays the same
            raw = (maxim-self.min) * factor + self.min

            # with the pattern added to the value
            adjusted, adjustedName = self.getAdjustedValue(raw, start)
            if adjusted != 'suppressed':
                logger.info( "Not Suppressed %s :: %s" % (adjusted, adjustedName))
                regular, regularName = self.getAdjustedValue(raw, start, "regular")
                if self.type == "integer" :
                    adjusted = int(round(adjusted, 0))
                    regular = int(round(regular, 0))
                obs = {
                    "host" : self.name,
                    "raw"  : raw,			# the unadjusted, non randomised value
                    "adjusted" : adjusted,		# all patterns applied (non randomised)
                    "regular" : regular		# regular pattern only (non randomised)
                }
                if verbose:
                    obs = {**obs, **{
                        "weekdayFactor" : weekdayFactor,
                        "t_gen" : str(dt.now()),
                        "t_start" : str(start),
                        "t_period" : str(self.period),
                        "adjusted_pattern" : adjustedName, # name of the pattern used
                        "regular_pattern" : regularName, # name of the pattern used
                        "is_verbose" : True
                   }}

                # apply noise to the final value to naturalise it
                for n in self.noiseFactors:
                    tag = "f"+str(n).replace(".", "_")
                    if adjusted == '':
                        raise("This shouldn't happen because I changed the code ;), delete me -1:+2 after conf 2018")
                        obs[tag] = ''
                    else:
                        noise = random.random()*(n/2)*(0.5 if random.random() > 0.5 else -0.5)
                        if self.noiseType=='factor':
                            noise = noise*adjusted

                        obs[tag] = adjusted + noise
                        if self.type == "integer":
                            obs[tag] = int(round(obs[tag], 0))

                ts.update(start, obs)

            r = random.random()
            # add +/- 1/2 some interval up to the period variation * period
            randomT = (0.5 if r > 0.5 else -0.5) * self.periodVar * self.period * r
            start += td(seconds=round(self.period+randomT, 0))

            self._json_["LastStart"] = start.strftime(STD_TIME_FMT)
            self._json_["LastEnd"] = end.strftime(STD_TIME_FMT)
            self._json_["LastRun"] = end.now().strftime(STD_TIME_FMT)

        return ts

    '''
    returns a value that is either a patterned value of the raw value if no patterns are active
    '''
    def getAdjustedValue(self, value, time, type=''):

        for p in self.patterns:
            if len(type) > 0 and p.type() != type:
                pass
            elif p.isActive(time):
                logger.info( "pattern active @ %s active count:%d" % (str(time), p._json_['active']))
                return (p.getValue(value), p.getName())

        return (value, 'raw')

# ===================================================================
# abstract pattern 
# ===================================================================
class Pattern():
    def __init__(self, json):
        factor = json['factor']
        self.factor = (factor['low'], factor['high'], factor['type'])
        self._type_ = json['type']
        self.days = parseArr(json['days'])
        self.times = []

        for timeRange in json['times']:
            start = dt.strptime(timeRange['start'], "%H:%M")
            end = dt.strptime(timeRange['end'], "%H:%M")
            self.times.append(((start.hour*3600+start.minute*60+start.second), (end.hour*3600+end.minute*60+end.second)))

        self._json_ = json
        self.name = "Type: %s, Days: %s, Times: %s" % (self._type_, json['days'], str(self.times))

    def getName(self):
        return self.name

    # adjust the value given constrains on this object
    def getValue(self, value):
        logger.info( "Pattern::getValue")

        low, high, method = self.factor
        if method == 'absolute' :
            return value + (high-low)*random.random() + low
        else:
            return value + value*((high-low)*random.random() + low)

    def type(self):
        return self._type_


# ===================================================================
# pattern that repeats in some way, day of week and hour of day
# implementation relies on the position in the day array of factors
# ===================================================================
class RegularPattern(Pattern):
    def __init__(self, json):
        # print "making Regular pattern: " + str(json['days'])

        Pattern.__init__(self, json)

    def isActive(self, time):
        '''
        this is active if the time hits a specific point in the arrays of configuration
        '''
        secs = (time.second + time.minute*60 + time.hour*3600)
        weekday = time.weekday()
        # print "%s Secs: %d " %(str(weekday), secs)
        if weekday in self.days:
            for t in self.times:
                #print t
                if t[0] <= secs <= t[1]:
                    #self._json_["active"] = 1
                    logger.info( "ON regular pattern inside window %s" % str(time))
                    return True

        #self._json_["active"] = 0
        logger.info( "OFF regular pattern outside window %s" % str(time))
        return False


# ===================================================================
# Random pattern that occurs 1 in x observations and then runs for some period
'''
    from the definition t looks like this
    "active": -103, 				           # internal flag that specifies how long a running pattern has left
    "descr": "low long infrequent spikes",     # put something useful in here
    "duration": {                              # how many intervals the pattern will run for, gets randomised between these values
        "max": 15, 
        "min": 8
    }, 
    "factor": {      						   # what is the size of the spike/trough, random value between low and high and will be factor (multiplicative) or additive (go on have a guess) 
        "high": 4, 
        "low": 3, 
        "type": "factor"
    }, 
    "probability": 0.0005,                            # probability this pattern will fire on each run, 0-1
    "type": "random"
'''
# ===================================================================
class RandomPattern(RegularPattern):
    def __init__(self, json):
        self.probability = json['probability']
        self.dur = json['duration']
        RegularPattern.__init__(self, json)

        try:
            if self._json_["active"] == None:
                pass #ed the test to see if the property exists, if so carry on
        except KeyError:
            # if no active property set then we set it to 0
            # when a spike is running the active flag will be set to the number of remaining points to generate
            self._json_["active"] = 0

    '''
    Sets it active iff its within the time range and te random value matches
    Using this we can set a pattern to only go off between 2-4 pm on a sunday for example.
    '''
    def isActive(self, time):
        if RegularPattern.isActive(self, time):
            r =  random.random()
            if self._json_["active"] <= 0 and r <= self.probability:
                # set it actibe and start the counter
                logger.info( "ON random pattern in window and is going active")
                self._json_["active"] = random.randint(self.dur['min'], self.dur['max'])
            else:
                self._json_["active"] -= 1
                logger.info( "OFF random pattern inside window but remains inactive, decreasing counter to %d" % self._json_["active"])
        else:
            logger.info( 'OFF random pattern outside active window')
            self._json_["active"] = 0

        return self._json_["active"] > 0



# ===================================================================
# Trend pattern that occurs 1 in x observations and then runs for some period
'''
    from the definition t looks like this
    "active": -103, 				           # internal flag that specifies how long a running pattern has left, stops at 0
    "last_value" : 123,							# last value written
    "duration": {                              # how many intervals the pattern will run for, gets randomised between these values
        "max": 15, 
        "min": 8
    }, 
    "factor": {      						   # what is the size of the spike/trough, random value between low and high and will be factor (multiplicative) or additive (go on have a guess) 
        "high": 0.05, 
        "low": 0.02, 
        "type": "factor"						# may be factor or absolute
    }, 
    "probability": 0.0005,                            # probability this pattern will fire on each run, 0-1
    "type": "trend"
'''
# ===================================================================
class TrendPattern(RandomPattern):
    def __init__(self, json):
        logger.info("trend pattern created")
        RandomPattern.__init__(self, json)
        try:
            if self._json_["last_value"] == None:
                pass #ed the test to see if the property exists, if so carry on
        except KeyError:
            self.reset()

    # adjust the value given constrains on this object
    def getValue(self, value):
        logger.info( "Trend::getValue")
        if self._json_["last_value"] == None:
            self._json_["last_value"] = value
        self._json_["last_value"] = RandomPattern.getValue(self, self._json_["last_value"])
        return self._json_["last_value"]

    def isActive(self, time):
        v = RandomPattern.isActive(self, time)
        if self._json_["active"] <= 0:
            self.reset()
        return v

    def reset(self):
        self._json_["last_value"] = None

'''
make a break in the pattern based on time and length options
ie if we say on days 0,1,2 between times 20:00-22:00 with a 0.1 probability break for between 5-20 data points
then this will produce no values during that time range
'''
class BreakPattern(RegularPattern):
    def __init__(self, json):
        logger.info("break pattern created")
        json.update({"factor":{"high": 0,"low": 0,"type": "factor"}})
        RegularPattern.__init__(self, json)

    # return an empty string for this value or do we omit the value from the stream altogether?
    def getValue(self, value):
        logger.info( "Break::getValue")
        return 'suppressed'

'''
make a break in the pattern based on time and length options
ie if we say on days 0,1,2 between times 20:00-22:00 with a 0.1 probability break for between 5-20 data points
then this will produce no values during that time range
'''
class RandomBreakPattern(RandomPattern):
    def __init__(self, json):
        logger.info("random break pattern created")
        json.update({"factor":{"high": 0,"low": 0,"type": "factor"}})
        RandomPattern.__init__(self, json)

    # return an empty string for this value or do we omit the value from the stream altogether?
    def getValue(self, value):
        logger.info( "RandomBreak::getValue")
        return 'suppressed'



# ===================================================================
# this is a cludge because I don't know how to make a sorted dictionary (quickly) without the internet
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
        logger.info("TS.update for %s called with %s" % (self._name_, tstr))
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


"""
def dateSortxxx(d1, d2):
    if d1==d2:
        return 0
    elif d1>d2:
        return 1
    return -1
"""

'''
***** please don't delete me, again
'''
if __name__ == '__main__':
    main(sys.argv[1:])

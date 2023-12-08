from my_logger import logger

from day_factor import DayFactor
from patterns import *
from time_series import TimeSeries

import json
from datetime import datetime
from datetime import timedelta
import random

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

STD_TIME_FMT = "%Y-%m-%d %H:%M:%S"


# ===================================================================
# This is the time series object
# should be redesigned to make it less rubbish
# ===================================================================
class SeriesSpec():
    '''
    Called from main.run
    SeriesSpec(json.load(fp), host, Factors(factor_file))

    {
        "Description": [
            "weekdays are similar but weekends are different, sat is high sunday is low, backup jobs run sunday at 3am for random 10-90 mins"
        ],
        "factorSet": "DAY_FACTORS_288",
        "max": 25,
        "min": 5,
        "weekdays": "0.75,0.73,0.71,0.69,0.79,0.19,0.05",
        "noise": {
            "type": "factor",
            "value": "0.01,0.1,0.25,0.5,1,2,5"
        },
        // span is in seconds, variance is factor to vary the time by
        "periodicity": {
            "span": 30,  
            "variance": 0.05
        },
        "type" : integer or float
        "patterns": { ... }
    }    

    state = {
        "LastRun": "date time str"
        "patterns" : {
            "ptn-1" : 12,
            "ptn-2" : -99,
            #"ptn-3" : None,
        }
    }
    '''
    def __init__(self, json, name, factors, state):
        
        self._json_ = json  
        self.name = name
        # state is a JSON object 
        self.state = state
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

        #self.desc = getOption(json, 'desc')
        self.max = json['max']
        self.min = json['min']
        #self.datatype = getOption(json, "datatype", "float")
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
        self.patterns = {}
        try:
            for pattern_name, pattern in json['patterns'].items():
                type = pattern['type']
                logger.info(f"Creating pattern: {pattern_name} using type: {type}")
                ptn = None
                if not pattern_name in self.state:
                    logger.info(f"Created new state for {pattern_name}")
                    self.state[pattern_name] = {}

                ptn_state = self.state[pattern_name]
                if type == "regular" :
                    ptn = RegularPattern(pattern, ptn_state)
                elif type == "random" :
                    ptn = RandomPattern(pattern, ptn_state)
                elif type == "trend" :
                    ptn = TrendPattern(pattern, ptn_state)
                elif type == "break" :
                    ptn = BreakPattern(pattern, ptn_state)
                elif type == "randombreak" :
                    ptn = RandomBreakPattern(pattern, ptn_state)
                else:
                    raise Exception('Balls, bad pattern type! :: '+type)
                self.patterns[pattern_name] = ptn
        except KeyError:
            logger.warning("Warning: No patterns defined")

        self.factors = DayFactor(factors.get(self.factorSet))


    # what was the last datetime point updated, this will be LastEnd, if its blank return one created from ndays
    # this is the point that data gen will start at, ie the last point that we generated
    def getLastObs(self, ndays):
        logger.info(f'LastRun is {self.state["LastRun"]}')
        if self.state["LastRun"] is None:
            logger.info(f"No LastRun so using default of {ndays} day(s), State: {str(self.state)}")
            return datetime.now().replace(hour=0, minute=0,second=0,microsecond=0) - timedelta(days=ndays)

        return datetime.strptime(self.state["LastRun"], STD_TIME_FMT)


    def getFactor(self, secs):
        return self.factors.get(secs)

    # want to return an object that specifies the timeseries final value plus a number of its component patterns
    # in a way that allows it to be easily output in a number of formats
    # must be a listin date order
    def generate(self, ndays, verbose):

        start = self.getLastObs(ndays) +  timedelta(seconds=self.period)  # add the next period
        end = datetime.now()   #.replace(minute=datetime.now().minute/5*5, second=0, microsecond=0)

        logger.info(f" *** Running {self.name} from {start} to {end}")

        headers = ["raw", "factor", "regular", "adjusted", "weekdayFactor"]
        for n in self.noiseFactors:
            headers.append("noise_"+str(n))
            headers.append("final_"+str(n))

        ts = TimeSeries(self.name, headers, start)
        while start <= end:

            randomT = (0.5 if random.random() > 0.5 else -0.5) * self.periodVar * self.period
            tmp_end = start + timedelta(seconds=(self.period+randomT))

            factor = self.getFactor(start.hour*3600+start.minute*60+start.second)

            weekdayFactor = self.weekdays[start.weekday()]
            maxim = self.min + (self.max-self.min) * weekdayFactor
            # this tops the max value of the series for the day but the min value stays the same
            raw = (maxim-self.min) * factor + self.min

            # with the pattern added to the value
            adjusted, adjustedName = self.getAdjustedValue(raw, start)
            if adjusted != 'suppressed':
                logger.debug( "Not Suppressed %s :: %s" % (adjusted, adjustedName))
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
                        "t_gen" : str(datetime.now()),
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
            start += timedelta(seconds=round(self.period+randomT, 0))

            self.state["LastEnd"] = end.strftime(STD_TIME_FMT)
            #self._json_["LastStart"] = start.strftime(STD_TIME_FMT)
            #self._json_["LastRun"] = end.now().strftime(STD_TIME_FMT)

        return ts

    '''
    returns a value that is either a patterned value of the raw value if no patterns are active
    '''
    def getAdjustedValue(self, value, time, type=''):

        for p_name, ptn in self.patterns.items():
            if len(type) > 0 and ptn.type() != type:
                pass
            elif ptn.isActive(time):
                logger.debug(f"Pattern {p_name} active @ {str(time)}, active count:{-9999}")
                return (ptn.getValue(value), p_name)

        return (value, 'raw')


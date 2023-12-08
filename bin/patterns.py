from my_logger import logger
import json
from datetime import datetime as dt
import random

# given a CSV string split it into an array, ie pass "1,2,3" and get [1,2,3] back
def parseArr(str):
    return json.loads("[%s]" % str)


class State():
    def __init__(self, cfg):
        self.cfg = cfg

    def getState(self, name):
        return self.cfg[name]


# ===================================================================
# abstract pattern 
# ===================================================================
class Pattern():
    def __init__(self, json, state):
        self.state = state
        factor = json['factor']
        self.factor = (factor['low'], factor['high'], factor['type'])
        self._type_ = json['type']
        self.days = parseArr(json['days'])
        self.times = []

        for timeRange in json['times']:
            start = dt.strptime(timeRange['start'], "%H:%M")
            end = dt.strptime(timeRange['end'], "%H:%M")
            self.times.append(((start.hour*3600+start.minute*60+start.second), (end.hour*3600+end.minute*60+end.second)))

        self.name = f"Type: {json['type']}, Days: {json['days']}, Times: {str(self.times)}"


    def getName(self):
        logger.info("Pattern.getName has been deprecated, DO NOT CALL THIS METHOD AS I'M DELETEING IT")
        return self.name

    # adjust the value given constrains on this object
    def getValue(self, value):
        logger.debug( "Pattern::getValue")

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
    def __init__(self, json, state):
        # print "making Regular pattern: " + str(json['days'])

        Pattern.__init__(self, json, state)

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
                    #self.state["active"] = 1
                    logger.debug( "ON regular pattern inside window %s" % str(time))
                    return True

        #self.state["active"] = 0
        logger.debug( "OFF regular pattern outside window %s" % str(time))
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
    def __init__(self, json, state):
        self.probability = json['probability']
        self.dur = json['duration']
        RegularPattern.__init__(self, json, state)

        try:
            if self.state["active"] == None:
                pass #ed the test to see if the property exists, if so carry on
        except KeyError:
            # if no active property set then we set it to 0
            # when a spike is running the active flag will be set to the number of remaining points to generate
            self.state["active"] = 0

    '''
    Sets it active iff its within the time range and te random value matches
    Using this we can set a pattern to only go off between 2-4 pm on a sunday for example.
    '''
    def isActive(self, time):
        if RegularPattern.isActive(self, time):
            r =  random.random()
            if self.state["active"] <= 0 and r <= self.probability:
                # set it actibe and start the counter
                logger.debug( "ON random pattern in window and is going active")
                self.state["active"] = random.randint(self.dur['min'], self.dur['max'])
            else:
                self.state["active"] -= 1
                logger.debug( "OFF random pattern inside window but remains inactive, decreasing counter to %d" % self.state["active"])
        else:
            logger.debug( 'OFF random pattern outside active window')
            self.state["active"] = 0

        return self.state["active"] > 0



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
    def __init__(self, json, state):
        logger.info("trend pattern created")
        RandomPattern.__init__(self, json, state)
        try:
            if self.state["last_value"] == None:
                pass #ed the test to see if the property exists, if so carry on
        except KeyError:
            self.reset()

    # adjust the value given constrains on this object
    def getValue(self, value):
        logger.debug( "Trend::getValue")
        if self.state["last_value"] == None:
            self.state["last_value"] = value
        self.state["last_value"] = RandomPattern.getValue(self, self.state["last_value"])
        return self.state["last_value"]

    def isActive(self, time):
        v = RandomPattern.isActive(self, time)
        if self.state["active"] <= 0:
            self.reset()
        return v

    def reset(self):
        self.state["last_value"] = None

'''
make a break in the pattern based on time and length options
ie if we say on days 0,1,2 between times 20:00-22:00 with a 0.1 probability break for between 5-20 data points
then this will produce no values during that time range
'''
class BreakPattern(RegularPattern):
    def __init__(self, json, state):
        logger.info("break pattern created")
        json.update({"factor":{"high": 0,"low": 0,"type": "factor"}})
        RegularPattern.__init__(self, json, state)

    # return an empty string for this value or do we omit the value from the stream altogether?
    def getValue(self, value):
        logger.debug( "Break::getValue")
        return 'suppressed'

'''
make a break in the pattern based on time and length options
ie if we say on days 0,1,2 between times 20:00-22:00 with a 0.1 probability break for between 5-20 data points
then this will produce no values during that time range
'''
class RandomBreakPattern(RandomPattern):
    def __init__(self, json, state):
        logger.info("random break pattern created")
        json.update({"factor":{"high": 0,"low": 0,"type": "factor"}})
        RandomPattern.__init__(self, json, state)

    # return an empty string for this value or do we omit the value from the stream altogether?
    def getValue(self, value):
        logger.debug( "RandomBreak::getValue")
        return 'suppressed'
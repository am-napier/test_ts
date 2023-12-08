from my_logger import logger

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

This app generates some test data time series that have a well structured pattern that could be used for exercising adaptive thresholding and/or anomaly detection.
All data is indexed in metrics index ts_metrics
If you install the app it will start up and generate 6 series called weekday-1, weekday-2, weekday-3, daily-1, daily-2 and daily-3

inputs.conf defines those sample inputs.  They are python based, see the arg parser in make_series.py for a list of options.
When each input runs it reads a state object from lookup test_ts_input_status.  When it completes the lookup is updated, one record is kept per input in that lookup
The -n argument is number of default days to generate data is there is no state object in the kvstore, this is set to 60 in the sample inputs.
If the input starts and there is a state object it generates a data point for each time from the recorded time to now..
If there is no state object the input generates data n days back.
1st positional argument is the name of a file in the cfg folder that defines the pattern of the series, second argument is the name of teh series (also the kvstore key field)
It uses passAuth but can be run from the command line with splunk cmd python, needs the splunk logging library but that's it.  All comms are using bython requests.

Here is a sample pattern file, comments # are for documentation only

Description - is just for reading
max, min : are the high and low values for the make_series
weekdays : csv list of day weightings for Mon-Sun
noise : describes the noise added to the raw series, ie 0.01 is 1%, 0.1 is 10%
periodicity : seconds between data points, variance adds some randomisation to that timestamp
patterns : describe was to add extra detail, ie spikes to a make_series.  Each pattern has a name, some state info is stored in the kvstore for each pattern.  
  You can add as many patterns as you want, they are all tested for every data point.

    type : there are a few types, regular, random etc.  see bin/patterns.py
    days : days of the week the pattern is active
    desc : text description of the pattern, ie docs
    duration : how long the pattern is active once its triggered
    factor : amount to alter the series by if pattern is active, between factors low and high, also supports absolute, read the code if you are that keen
    probability : real number probability that the pattern will become active within the periodicity (applies to random patterns)
    times : start and end time for the patterns



{
    "Description": [
        "Series of 5 weekdays the same, sat is 50%, sun is 25%"
    ],
    "max": 100,
    "min": 0,
    "weekdays": "1,1,1,1,1,0.5,0.25",
    "noise": {"type":"factor","value":"0.01,0.1,0.25,0.5,1,2,5"},
    "periodicity": {"span":30, variance:0.05},
    "patterns": {
        "background-noise":{
            "days": "0,1,2,3,4,5,6",
            "desc": "small random noise every day all day, 2% probability, 10-50% increase in value",
            "duration": { "max": 10, "min": 1 }, 
            "factor": { "low": 0.4, "high": 0.5, "type": "factor" },
            "probability": 0.02,
            "times": [{"start":"00:00","end":"23:25"}],
            "type": "random"
        },
        "randomness":{
            "desc": "11am to 12pm every day",
            "days": "0,1,2,3,4,5,6",
            "probability": 0.01,
            "type": "random",
            "duration": {"max":50,"min":5},
            "factor": {"high":1.0,"low":1.0,"type":"factor"},
            "times": [{"start":"11:00","end":"12:00"}]
        }
    }
}

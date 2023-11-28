# test_ts
time series datagen

Creates some json like this 
```
{ [-]
   adjusted: 5                      # original series with faults added to it, see pattern definitions in make_series.py 
   datetime: 2023-11-28 22:40:46    # a timestamp
   f0_01: 4.992213827898024         # adjusted + 0-0.01 random noise factor 
   f0_1: 4.957032939622173          # adjusted + 0-0.1 random noise factor 
   f0_25: 5.110601935508311         # adjusted + 0-0.25 random noise factor 
   f0_5: 4.408345706557888          # adjusted + 0-0.5 random noise factor 
   f1: 6.066633053500141            # adjusted + 0-1.0 random noise factor 
   f2: 6.16283449970642             # adjusted + 0-2.0 random noise factor
   f5: 10.727248687448483           # adjusted + 0-5.0 random noise factor
   host: weekday                    # name of the host in the index
   raw: 5                           # raw unadjusted value based on the initial factor set 
   regular: 5                       # same as raw, don't know why there are two
}
```
Please read the bin/make_series.py for more details and when you work out what I did feel free to write some docs ;)  
Otherwise its on my todo list ... near the bottom ;) 
soz!

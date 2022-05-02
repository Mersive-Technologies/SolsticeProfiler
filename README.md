# SolsticeProfiler

CLI tool that provides blackbox profiling of the Solstice client. It operates by detecting the state of the application from the binaries that are being run.

High level overview of how the script works is:
* Script starts and polls every `(60 / samplesPerMinute)` looking for the Solstice processes running and inferring the state from which are running with load.
* The script will run indefinitely until it sees some Solstice processes (`ctrl+c` to end without gather metrics)
* Once it sees any Solstice processes it will go into STARTUP state for `secondsForTransition` before transitioning to `IDLE` or whatever state the app is currently in
* After each poll it will check if the script total run time is greater than totalSessionLength if totalSessionLength is not zero
* In all non-transition states `(IDLE, SHARING, CONFERENCE)` it will collect data every `(60 / samplesPerMinute)` seconds until it has gathered `samplesPerState`. The script will then inform the user that all the samples for that state have been gathered
* At this point it will continue to poll (it has to check for the processes to get state) but the sample will be thrown out until the next state change
* Once no Solstice processes are seen it will wait `secondsToWaitAfterSolsticeCloses` to see another Solstice process, if it doesn't it will stop the script and generate the report

The tool can be invoked with the following flags, passed in flags will clobber the config file values.

Running the script with `-c` will allow you to pass the path to a config json file which will be used instead of the default `mersiveProfiler.json` in the project root.

In the config file are the following properties:

* "solsticeRoot": (Optional) If provided this will use the git information for the filename of the output report instead of just the current timestamp.
* "totalSessionLength": How long the profiling session should last overall. 0 runs until the script sees Solstice close.
* "samplesPerMinute": How many samples per minute to gather. There is a hard limit of around 30 since it can take just under 2 seconds to gather the CPU info (see "Time to gather sample" column in raw output).
* "samplesPerState": How many samples are gathered in non-transitional states before it waits for the next state.
* "secondsForTransition": When major application states are changed there will be a transition state held for this many seconds to not skew the CPU results while Solstice loads.
* "gpu": Do GPU profiling, not currently supported.
* "humanReadableUnits": Whether to output raw bytes or in megabytes
* "zeroPercentageInReport": Whether to omit samples with a 0 CPU rate from the report
* "secondsToWaitAfterSolsticeCloses": Once the script detects no more Solstice executables it will wait this long before closing.
* "processSolsticeClient": The name of the main solstice client process, change for different OS.
* "processVirtualDisplay": The name of the virtual display process, change for different OS.
* "processSolsticeConference": The name of the Solstice Conference process, change for different OS.
* "processRsusbipclientProcess": The name of the rsubipclient process, change for different OS.

Flags which can be passed from the command line:

* "-c", "--config", help="Use a config file instead of passing arguments")
* "-l", "--totalSessionLength", help="Length of the profile session. Set 0 for until Solstice closes." )
* "-m", "--samplesPerMinute", help="Samples gathered per minute." )
*  "-s", "--samplesPerState", help="There are three states for the client app, Idle, Sharing, and Conference. How many samples to gather after each state change. 0 is infinite." )
*  "-g", "--gpu", help="1 (default): profile GPU usage. 0: Don't profile GPU usage." )
* "-u", "--humanReadableUnits", help="Human readable units, MB instead of bytes, etc.", action='store_false')
* "-z", "--zeroPercentageInReport", help="Report instances where CPU is zero.", action='store_false')
* "-t", "--transitionStateSeconds", help="How long after a state changes is it considered in a transition state")





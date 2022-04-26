# SolsticeProfiler

CLI tool that provides blackbox profiling of the Solstice client. It operates by detecting the state of the application from the binaries that are being run.

The tool can be invoked with the following flags, using -c will allow you to pass the path to a config json which will be used instead of these flags.

* "-c", "--config", help="Use a config file instead of passing arguments")
* "-l", "--length", help="Length of the profile session." )
* "-f", "--frequency", help="Samples gathered per minute." )
*  "-s", "--secondsPerState", help="There are three states for the client app, Idle, Sharing, and Conference. How long in seconds to gather samples after each state change. 0 is infinite." )
*  "-g", "--gpu", help="1 (default): profile GPU usage. 0: Don't profile GPU usage." )
* "-u", "--units", help="Human readable units, MB instead of bytes, etc.", action='store_false')
* "-z", "--zeroPercentageInReport", help="Report instances where CPU is zero.", action='store_false')
* "-t", "--transitionStateSeconds", help="How long after a state changes is it considered in a transition state")



In the config file are the following properties:

* "solsticeRoot": If provided this will use the git information to form the filename for the output instead of just the current timestamp.
* "length": How long the profiling session should last overall. 0 runs until the script sees Solstice close.
* "frequency": How many samples per minute to gather. There is a hard limit of around 60 since it takes roughly 1 second to gather the CPU info.
* "secondsPerState": How long samples will be gathered after each state change
* "secondsForTransition": When major application states are changed there will be a transition state held for this many seconds to not skew the CPU results while Solstice loads.
* "gpu": Do GPU profiling, not currently supported.
* "humanReadableUnits": Whether to output raw bytes or in megabytes
* "zeroPercentageInReport": Whether to omit samples with a 0 CPU rate from the report
* "secondsToWaitAfterSolsticeCloses": Once the script detects no more Solstice executables it will wait this long before closing.

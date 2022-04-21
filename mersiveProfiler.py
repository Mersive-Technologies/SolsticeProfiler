import argparse
from fileinput import filename
import psutil
import time
import datetime
from enum import Enum

NVidiaLibAvailable = True
IntelGPULibAvailable = False
try:
    import nvidia_smi
except ModuleNotFoundError:
    NVidiaLibAvailable = False

SolsticeClientProcess = "SolsticeClient.exe"
VirtualDisplayProcess = "SolsticeVirtualDisplay.exe"
SolsticeConferenceProcess = "SolsticeConference.exe"
RsusbipclientProcess = "rsusbipclient.exe"

ProcessesToFind = [ SolsticeClientProcess, VirtualDisplayProcess, SolsticeConferenceProcess, RsusbipclientProcess ]

def parseArguments():
    parser = argparse.ArgumentParser()
    parser.add_argument( "-l", "--length", help="Length of the profile session." )
    parser.add_argument( "-f", "--frequency", help="Samples gathered per minute." )
    parser.add_argument( "-s", "--secondsPerState", help="There are three states for the client app, Idle, Sharing, and Conference. How long in seconds to gather samples after each state change. 0 is infinite." )
    parser.add_argument( "-g", "--gpu", help="1 (default): profile GPU usage. 0: Don't profile GPU usage." )
    return parser.parse_args()

def startSession( args ):
    frequency = 60
    secondsPerState = 15
    profileGPU = True
    length = 30

    if( args.frequency ):
        frequency = float( args.frequency )
    if( args.secondsPerState ):
        secondsPerState = float( args.secondsPerState )
    if( args.gpu == "0"):
        profileGPU = False
    if( args.length ):
        length = float( args.length )

    sampleDelay = 60 / frequency 
    session = ProfileSession( frequency, sampleDelay, secondsPerState, profileGPU, length )
    session.printStartSession()
    return session

class GPUSnapshot:
    def __init__( self, device, memory, temperature, gpuPercentageUsed ):
        self.device = device
        self.memory = memory
        self.temperature = temperature
        self.gpuPercentageUsed = gpuPercentageUsed

    def __str__(self):
        return f"Device {self.device} GPU % [{self.gpuPercentageUsed}] Memory (MB) [{self.memory / 1024 / 1024}] Temperature [{self.temperature}]"

    def __repr__(self):
        return f'GPUSnapshot(device={self.device}, gpuPercentageUsed={self.gpuPercentageUsed}, memory={self.memory}, temperature={self.temperature})'            

class ProcessSnapshot:
    def __init__( self, processName, cpuPercentageUsed, memory ):
        self.processName = processName
        self.cpuPercentageUsed = cpuPercentageUsed
        self.memory = memory

    def __str__(self):
        return f"{self.processName} CPU% [{self.cpuPercentageUsed}] Memory (MB) [{self.memory / 1024 / 1024}]"

    def __repr__(self):
        return f'ProcessSnapshot(processName={self.processName}, cpuPercentageUsed={self.cpuPercentageUsed}, memory={self.memory})'        

class PerformanceSnapshot:
    def __init__( self ):
        self.time = time.time()
        self.processSnapshots = []
        self.gpuSnapshots = []
        self.timeToGatherSample = 0

    def __str__(self):
        output = f"{datetime.datetime.fromtimestamp(self.time)} gathered in {self.timeToGatherSample} seconds:\n"
        output += "  Processes:\n"
        for process in self.processSnapshots:
            output += "    " + str(process) + "\n"
        if len( self.gpuSnapshots ) > 0:
            output += "  GPU Devices:\n"
            for gpu in self.gpuSnapshots:
                output += "    " + str(gpu) + "\n"
        return output

    def __repr__(self):
        output = f"PerformanceSnapshot(processSnapshots=["
        
        for process in self.processSnapshots:
            output += repr(process)
        output += "], gpuSnapshots=["

        for gpu in self.gpuSnapshots:
            output += str(gpu)
        output += "], time={self.time}, timeToGatherSample={self.timeToGatherSample})"

    def currentApplicationState( self ):
        virtualMonitor = False
        solstice = False
        conference = False
        rsusbipClient = False

        for process in self.processSnapshots:
            if process.processName == SolsticeClientProcess:
                solstice = True
            elif process.processName == VirtualDisplayProcess and process.cpuPercentageUsed > 0.0:
                virtualMonitor = True
            elif process.processName == SolsticeConferenceProcess:
                conference = True
            elif process.processName == RsusbipclientProcess:
                rsusbipClient = True

        if solstice and not conference and not virtualMonitor:
            return ApplicationState.IDLE
        elif solstice and conference:
            return ApplicationState.CONFERENCE
        elif solstice and virtualMonitor:
            return ApplicationState.SHARING

        return ApplicationState.NONE            

class ApplicationState(Enum):
    NONE = 0
    STARTUP = 1
    IDLE = 2
    SHARING = 3
    CONFERENCE = 4
    def __str__(self):
        return self.name

class ApplicationStateSamples:
    def __init__( self, state ):
        self.stateStarted = time.time()
        self.state = state
        self.samples = []

    def __str__(self):
        output = f"Application started state {self.state} at {datetime.datetime.fromtimestamp(self.stateStarted)}. Samples:\n"
        if len(self.samples) > 0:
            for snapshot in self.samples:
                output += str(snapshot)
        return output  

class ProfileSession:
    def __init__( self, frequency, sampleDelay, secondsPerState, profileGPU, sessionLengthSeconds ):
        self.startedAt = time.time()
        self.applicationStateSamples = []
        self.frequency = frequency
        self.sampleDelay = sampleDelay
        self.secondsPerState = secondsPerState
        self.profileGPU = profileGPU
        self.sessionLengthSeconds = sessionLengthSeconds

    def printStartSession( self ):
        print( f"Profiling Solstice at frequency [{self.frequency} Hz] Sample time per state [{self.secondsPerState} seconds] sampleDelay [{self.sampleDelay} seconds] Session Length [{self.sessionLengthSeconds} seconds]." )
        print( f"Started session at {datetime.datetime.fromtimestamp(self.startedAt)}")        

    def __str__(self):
        output = f""
        if len(self.applicationStateSamples) > 0:
            for sample in self.applicationStateSamples:
                output += str(sample) + "\n"
        
        if len( output ) == 0:
            output = "No instances of Solstice found."
        return output

    def writeCsv( self ):
        # HEADER row
        output = f"Time,Process,CPU%,Memory,State,Process Info Gathering Time\n"
        if len(self.applicationStateSamples) > 0:
            for applicationStateSample in self.applicationStateSamples:
                for performanceSnapshot in applicationStateSample.samples:
                    # TODO: merge GPU stats into same row
                    for processSnapshot in performanceSnapshot.processSnapshots:
                        output += f"{datetime.datetime.fromtimestamp(performanceSnapshot.time)},{processSnapshot.processName},{processSnapshot.cpuPercentageUsed},{processSnapshot.memory},{applicationStateSample.state},{performanceSnapshot.timeToGatherSample}\n"
        fileName = f"Solstice-Profile-{datetime.datetime.fromtimestamp(performanceSnapshot.time)}.csv"
        fileName = fileName.replace(":", "_")
        file = open(fileName, "w")
        file.write(output)
        file.close()
        print(f"Wrote file: {fileName}")

if __name__ == '__main__':
    args = parseArguments()
    session = startSession(args)

    if session.profileGPU and NVidiaLibAvailable:
        try:
            nvidia_smi.nvmlInit()
        except:
            NVidiaLibAvailable = False
            print ( "Could not initialize nvidia library" )

    gatherSamples = True
    startTime = time.time()
    applicationState = None
    currentApplicationStateSamples = None
    firstSampleTaken = True
    changedStatesLastFrame = False
    validStatesInSession = False
    appClosedTimeoutStart = None

    while gatherSamples:
        performanceSnapshot = PerformanceSnapshot()

        if session.profileGPU and NVidiaLibAvailable:
            deviceCount = nvidia_smi.nvmlDeviceGetCount()
            for i in range(deviceCount):
                handle = nvidia_smi.nvmlDeviceGetHandleByIndex(i)
                info = nvidia_smi.nvmlDeviceGetMemoryInfo(handle)
                device = nvidia_smi.nvmlDeviceGetName(handle)
                # TODO: hook into API
                memory = 0
                temperature = 0
                gpuPercentageUsed = 0
                performanceSnapshot.gpuSnapshots.append( GPUSnapshot( device, memory, temperature, gpuPercentageUsed ) )

        timeToQuery = time.time()
        processes = [proc for proc in psutil.process_iter()]
        performanceSnapshot.timeToGatherSample = time.time() - timeToQuery
        try:
            for process in processes:
                if process.name() in ProcessesToFind:
                    percentage = process.cpu_percent()
                    if firstSampleTaken:
                        firstSampleTaken = False
                        continue
                    percentage = percentage / psutil.cpu_count()
                    performanceSnapshot.processSnapshots.append( ProcessSnapshot( process.name(), percentage, process.memory_full_info().uss ) )
        except Exception as e:
            print( f"Warning: sample failed due to {e}" )
            continue

        if len( performanceSnapshot.processSnapshots ) > 0 or applicationState != ApplicationState.NONE:
            currentApplicationState = performanceSnapshot.currentApplicationState()
            if currentApplicationState != applicationState:
                print( f"Application state changed from {applicationState} to {currentApplicationState}" )
                if currentApplicationState != ApplicationState.NONE:
                    validStatesInSession = True
                    appClosedTimeoutStart = None
                elif currentApplicationState == ApplicationState.NONE and validStatesInSession:
                    appClosedTimeoutStart = time.time()
               
                # Don't store rapid state changes
                if currentApplicationStateSamples and not changedStatesLastFrame:
                    session.applicationStateSamples.append(currentApplicationStateSamples)

                currentApplicationStateSamples = ApplicationStateSamples( currentApplicationState )
                applicationState = currentApplicationState
                changedStatesLastFrame = True
            else:
                changedStatesLastFrame = False

        # Close out the profiler after Solstice closes
        if appClosedTimeoutStart != None and time.time() - appClosedTimeoutStart > 5:
            gatherSamples = False

        if applicationState != ApplicationState.NONE and \
            time.time() - currentApplicationStateSamples.stateStarted < session.secondsPerState and \
            ( len( performanceSnapshot.gpuSnapshots ) > 0 or len( performanceSnapshot.processSnapshots ) > 0 ):
            currentApplicationStateSamples.samples.append( performanceSnapshot )

        delay = session.sampleDelay - performanceSnapshot.timeToGatherSample
        # per docs:
        # https://psutil.readthedocs.io/en/latest/#psutil.Process.cpu_percent
        # When interval is 0.0 or None compares process times to system CPU times elapsed since last call, returning immediately. 
        # That means the first time this is called it will return a meaningless 0.0 value which you are supposed to ignore. 
        # In this case is recommended for accuracy that this function be called a second time with at least 0.1 seconds between calls.
        if delay < 0.1:
            delay = 0.1
        time.sleep( delay )

        if time.time() - startTime > session.sessionLengthSeconds:
            gatherSamples = False

    if currentApplicationStateSamples:
        session.applicationStateSamples.append(currentApplicationStateSamples)

    if session.profileGPU and NVidiaLibAvailable:
        nvidia_smi.nvmlShutdown()

    print(str(session))
    session.writeCsv()

import argparse
from fileinput import filename
import psutil
import time
import datetime
import json
import os
from enum import Enum

GithubLibAvailable = True
try:
    from git import Repo
except ModuleNotFoundError:
    GithubLibAvailable = False

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
    parser.add_argument( "-c", "--config", help="Use a config file instead of passing arguments")
    parser.add_argument( "-l", "--length", help="Length of the profile session." )
    parser.add_argument( "-f", "--frequency", help="Samples gathered per minute." )
    parser.add_argument( "-s", "--secondsPerState", help="There are three states for the client app, Idle, Sharing, and Conference. How long in seconds to gather samples after each state change. 0 is infinite." )
    parser.add_argument( "-g", "--gpu", help="1 (default): profile GPU usage. 0: Don't profile GPU usage." )
    parser.add_argument( "-u", "--units", help="Human readable units, MB instead of bytes, etc.", action='store_false')
    parser.add_argument( "-z", "--zeroPercentageInReport", help="Report instances where CPU is zero.", action='store_false')
    parser.add_argument( "-t", "--transitionStateSeconds", help="How long after a state changes is it considered in a transition state")
    return parser.parse_args()

def startSession( args ):
    global Session
    frequency = 60
    secondsPerState = 15
    profileGPU = False
    length = 0
    humanReadable = False
    solsticeRoot = None
    zeroPercentageInReport = False
    secondsToWaitAfterSolsticeCloses = 5
    secondsForTransition = 10

    if args.config:
        f = open( args.config )
        data = json.load(f)
        f.close()
        if data["solsticeRoot"]:
            solsticeRoot = data["solsticeRoot"]
        if data["frequency"]:
            frequency = float( data["frequency"] )
        if data["secondsPerState"]:
            secondsPerState = float( data["secondsPerState"] )
        if data["gpu"]:
            profileGPU = data["gpu"]
        if data["length"]:
            length = float( data["length"] )
        if data["humanReadableUnits"]:
            humanReadable = bool( data["humanReadableUnits"] )
        if data["zeroPercentageInReport"]:
            zeroPercentageInReport = bool( data["zeroPercentageInReport"] )
        if data["secondsToWaitAfterSolsticeCloses"]:
            secondsToWaitAfterSolsticeCloses = data["secondsToWaitAfterSolsticeCloses"]
        if data["secondsForTransition"]:
            secondsForTransition = data["secondsForTransition"]
    else:
        if( args.frequency ):
            frequency = float( args.frequency )
        if( args.secondsPerState ):
            secondsPerState = float( args.secondsPerState )
        if( args.gpu == "0"):
            profileGPU = False
        if( args.length ):
            length = float( args.length )

        zeroPercentageInReport = args.zeroPercentageInReport
        humanReadable = args.units

    sampleDelay = 60 / frequency 
    Session = ProfileSession( solsticeRoot, frequency, sampleDelay, secondsPerState, profileGPU, length, humanReadable, zeroPercentageInReport, secondsToWaitAfterSolsticeCloses, secondsForTransition )
    Session.printStartSession()

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

    def addGPUSample( self, device, memory, temperature, gpuPercentageUsed ):
        self.gpuSnapshots.append( GPUSnapshot( device, memory, temperature, gpuPercentageUsed ) )

    def addProcessSample( self, processName, cpuPercentage, memoryUsed ):
        self.processSnapshots.append( ProcessSnapshot( processName, cpuPercentage, memoryUsed ) )

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
    SHARING_STARTUP = 3
    SHARING = 4
    CONFERENCE_STARTUP = 5
    CONFERENCE = 6
    RETURN_TO_IDLE = 7
    def __str__(self):
        return self.name

class ProcessStateAverage:
    def __init__ ( self, state, processName ):
        self.state = state
        self.processName = processName
        self.cpuPercentageTotal = 0
        self.memoryUsedTotal = 0
        self.numberOfSamples = 0
        self.lowestCpuUsed = None
        self.highestCpuUsed = 0
        self.lowestMemoryUsed = None
        self.highestMemoryUsed = 0
        self.earliestSample = None
        self.latestSample = None

    def addSample ( self, time, cpuPercentage, memoryUsed ):
        if self.earliestSample is None or time <= self.earliestSample:
            self.earliestSample = time
        elif self.latestSample is None or time >= self.latestSample:
            self.latestSample = time

        self.numberOfSamples += 1
        self.cpuPercentageTotal += cpuPercentage
        self.memoryUsedTotal += memoryUsed
        if ( self.lowestCpuUsed is None or cpuPercentage < self.lowestCpuUsed ) and cpuPercentage != 0:
            self.lowestCpuUsed = cpuPercentage
        if cpuPercentage > self.highestCpuUsed:
            self.highestCpuUsed = cpuPercentage
        if ( self.lowestMemoryUsed is None or memoryUsed < self.lowestMemoryUsed ) and memoryUsed != 0:
            self.lowestMemoryUsed = memoryUsed
        if memoryUsed >= self.highestMemoryUsed:
            self.highestMemoryUsed = memoryUsed            

    def averageCPU( self ):
        return self.cpuPercentageTotal / self.numberOfSamples

    def averageMemory( self ):
        total = self.memoryUsedTotal / self.numberOfSamples
        if Session.humanReadableUnits:
            total = total / 1024 / 1024
        return total
    
    def timeInState( self ):
        if self.latestSample is None or self.earliestSample is None:
            return 0
        return self.latestSample - self.earliestSample

    def csvRow( self ):
        lowestMem = self.lowestMemoryUsed
        highestMem = self.highestMemoryUsed
        if Session.humanReadableUnits:
            lowestMem = lowestMem / 1024 / 1024
            highestMem = highestMem / 1024 / 1024
        lowestCpu = 0
        if self.lowestCpuUsed is not None:
            lowestCpu = self.lowestCpuUsed
        return f"{self.processName},{self.state},{self.timeInState()},{self.numberOfSamples},{lowestCpu},{self.highestCpuUsed},{lowestMem},{highestMem},{self.averageCPU()},{self.averageMemory()}\n" 


class ApplicationStateSamples:
    def __init__( self, state ):
        self.stateStarted = time.time()
        self.state = state
        self.samples = []
    
    def addStateSamples( self, samples ):
        self.samples.append( samples )

    def __str__(self):
        output = f"Application started state {self.state} at {datetime.datetime.fromtimestamp(self.stateStarted)}. Samples:\n"
        if len(self.samples) > 0:
            for snapshot in self.samples:
                output += str(snapshot)
        return output  

class ProfileSession:
    def __init__( self, solsticeRoot, frequency, sampleDelay, secondsPerState, profileGPU, sessionLengthSeconds, 
        humanReadableUnits, zeroPercentageInReport, secondsToWaitAfterSolsticeCloses, transitionStateSeconds ):
        self.startedAt = time.time()
        self.solsticeRoot = solsticeRoot
        self.applicationStateSamples = []
        self.applicationStateAverages = []
        self.frequency = frequency
        self.sampleDelay = sampleDelay
        self.secondsPerState = secondsPerState
        self.profileGPU = profileGPU
        self.sessionLengthSeconds = sessionLengthSeconds
        self.humanReadableUnits = humanReadableUnits
        self.zeroPercentageInReport = zeroPercentageInReport
        self.secondsToWaitAfterSolsticeCloses = secondsToWaitAfterSolsticeCloses
        self.transitionStateSeconds = transitionStateSeconds

    def printStartSession( self ):
        sessionLength = f"{self.sessionLengthSeconds} seconds"
        if self.sessionLengthSeconds == 0:
            sessionLength = "Until Solstice closes"
        print( f"Profiling Solstice with settings:" )
        print( f"  Frequency (samples per minute): {self.frequency}" )
        print( f"  Time per state (seconds): {self.secondsPerState}" )
        print( f"  Length of transition period between states (seconds): {self.transitionStateSeconds}" )
        print( f"  Session length: {sessionLength}" )
        print( f"  Seconds to wait after Solstice closes to end profiling: {self.secondsToWaitAfterSolsticeCloses}")
        if ( self.solsticeRoot ):
            print(f'  Solstice root: "{self.solsticeRoot}"')
        print( f"Started session at {datetime.datetime.fromtimestamp(self.startedAt)}\n")        

    def __str__(self):
        output = f""
        if len(self.applicationStateSamples) > 0:
            for sample in self.applicationStateSamples:
                output += str(sample) + "\n"
        
        if len( output ) == 0:
            output = "No instances of Solstice found."
        return output

    def writeCsv( self ):
        global GithubLibAvailable
        dataWritten = False
        # HEADER rows
        memoryUnits = ""
        if self.humanReadableUnits:
            memoryUnits += " (MB)"
        else:
            memoryUnits += " (bytes)"
        averageOutput = f"Process,State,Time in State,# Samples,Lowest CPU %,Highest CPU %,Lowest Memory Used{memoryUnits}, Highest Memory Used{memoryUnits},Average CPU &,Average Memory Used{memoryUnits}\n"  
        output = f"Time,Process,CPU%,Memory Used{memoryUnits},State\n"

        # Sample data
        if len(self.applicationStateSamples) > 0:
            for applicationStateSample in self.applicationStateSamples:
                processAverages = []
                for performanceSnapshot in applicationStateSample.samples:
                    for processSnapshot in performanceSnapshot.processSnapshots:
                        currentAverage = None
                        # Gather the averages from this state
                        for pa in processAverages:
                            if pa.processName == processSnapshot.processName:
                                currentAverage = pa
                                break
                        if not currentAverage:
                            currentAverage = ProcessStateAverage( applicationStateSample.state, processSnapshot.processName )
                            processAverages.append( currentAverage )
                        currentAverage.addSample( performanceSnapshot.time, processSnapshot.cpuPercentageUsed, processSnapshot.memory )

                        # Don't write zero % CPU if not set
                        if not self.zeroPercentageInReport and processSnapshot.cpuPercentageUsed == 0:
                            continue

                        # Accumulate CSV output for raw samples
                        dataWritten = True
                        memory = processSnapshot.memory
                        if self.humanReadableUnits:
                            memory = memory / 1024 / 1024
                        output += f"{datetime.datetime.fromtimestamp(performanceSnapshot.time)},{processSnapshot.processName},{processSnapshot.cpuPercentageUsed},{memory},{applicationStateSample.state}\n"
                for pa in processAverages:
                    # TODO: merge GPU stats into same row
                    averageOutput += pa.csvRow()

        # Use commit metadata for filename if available
        useBackupFilename = True
        if GithubLibAvailable and self.solsticeRoot and self.solsticeRoot != "":
            try:
                repo = Repo( self.solsticeRoot )
                assert not repo.bare
                headcommit = repo.head.commit
                fileName = f"Solstice-Profile-{datetime.datetime.fromtimestamp(headcommit.committed_date)}-{repo.head.ref}-{headcommit.hexsha}"
                useBackupFilename = False
            except:
                pass
            
        if useBackupFilename:
            fileName = f"Solstice-Profile-{datetime.datetime.fromtimestamp(Session.startedAt)}"

        fileName = fileName.replace(":", "_")
        if dataWritten:
            # Don't clobber existing files
            maxAttempts = 1000
            if os.path.exists( f"{fileName}.csv" ):
                for i in range(2, maxAttempts):
                    newFileName = f"{fileName}_v{i}.csv"
                    if not os.path.exists( newFileName ):
                        fileName = newFileName
                        break
                if i == maxAttempts - 1:
                    print( f"Failed to create new csv file with root: {fileName}")
                    exit( 1 )
            else:
                fileName = fileName + ".csv"
                        
            file = open(fileName, "w")
            file.write(averageOutput)
            file.write("\n\n\n")
            file.write(output)
            file.close()
            print(f"Wrote file: {fileName}")
        else:
            print( f"{fileName} NOT written since there were no sample outputs")

    def addStateSamples( self, samples ):
        self.applicationStateSamples.append( samples )

if __name__ == '__main__':
    args = parseArguments()
    startSession(args)

    if Session.profileGPU and NVidiaLibAvailable:
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

        if Session.profileGPU and NVidiaLibAvailable:
            deviceCount = nvidia_smi.nvmlDeviceGetCount()
            for i in range(deviceCount):
                handle = nvidia_smi.nvmlDeviceGetHandleByIndex(i)
                info = nvidia_smi.nvmlDeviceGetMemoryInfo(handle)
                device = nvidia_smi.nvmlDeviceGetName(handle)
                # TODO: hook into API
                memory = 0
                temperature = 0
                gpuPercentageUsed = 0
                performanceSnapshot.addGPUSample( device, memory, temperature, gpuPercentageUsed )

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
                    performanceSnapshot.addProcessSample( process.name(), percentage, process.memory_full_info().uss )
        except Exception as e:
            print( f"Warning: sample failed due to {e}" )
            continue

        if len( performanceSnapshot.processSnapshots ) > 0 or applicationState != ApplicationState.NONE:
            currentApplicationState = performanceSnapshot.currentApplicationState()

            stateRunningPastTransition = False
            if currentApplicationStateSamples:
                stateRunningPastTransition = time.time() - currentApplicationStateSamples.stateStarted > Session.transitionStateSeconds

            # determine if we are in a transitional state
            if ( applicationState == ApplicationState.NONE or applicationState == None ) and currentApplicationState == ApplicationState.IDLE:
                currentApplicationState = ApplicationState.STARTUP
                currentApplicationStateSamples = None
                stateRunningPastTransition = False

            if currentApplicationState == ApplicationState.IDLE and applicationState == ApplicationState.STARTUP and not stateRunningPastTransition:
                currentApplicationState = ApplicationState.STARTUP
            elif currentApplicationState == ApplicationState.SHARING and applicationState == ApplicationState.IDLE:
                currentApplicationState = ApplicationState.SHARING_STARTUP
            elif currentApplicationState == ApplicationState.SHARING and applicationState == ApplicationState.SHARING_STARTUP and not stateRunningPastTransition:
                currentApplicationState = ApplicationState.SHARING_STARTUP
            elif currentApplicationState == ApplicationState.CONFERENCE and applicationState == ApplicationState.IDLE:
                currentApplicationState = ApplicationState.CONFERENCE_STARTUP
            elif currentApplicationState == ApplicationState.CONFERENCE and applicationState == ApplicationState.CONFERENCE_STARTUP and not stateRunningPastTransition:
                currentApplicationState = ApplicationState.CONFERENCE_STARTUP
            elif currentApplicationState == ApplicationState.IDLE and applicationState == ApplicationState.CONFERENCE:
                currentApplicationState = ApplicationState.RETURN_TO_IDLE
            elif currentApplicationState == ApplicationState.IDLE and applicationState == ApplicationState.SHARING:
                currentApplicationState = ApplicationState.RETURN_TO_IDLE                
            elif currentApplicationState == ApplicationState.IDLE and applicationState == ApplicationState.RETURN_TO_IDLE and not stateRunningPastTransition:
                currentApplicationState = ApplicationState.RETURN_TO_IDLE                
            
            # handle post transition state
            if applicationState == ApplicationState.STARTUP and stateRunningPastTransition:
                currentApplicationState = ApplicationState.IDLE
            elif applicationState == ApplicationState.SHARING_STARTUP and stateRunningPastTransition:
                currentApplicationState = ApplicationState.SHARING
            elif applicationState == ApplicationState.CONFERENCE_STARTUP and stateRunningPastTransition:
                currentApplicationState = ApplicationState.CONFERENCE
            elif applicationState == ApplicationState.RETURN_TO_IDLE and stateRunningPastTransition:
                currentApplicationState = ApplicationState.IDLE                                                

            if currentApplicationState != applicationState:
                if applicationState == ApplicationState.NONE:
                    print( f"Application detected in {currentApplicationState} state" )
                elif applicationState != None and currentApplicationState == ApplicationState.NONE:
                    print( f"Solstice application closed, exiting in {Session.secondsToWaitAfterSolsticeCloses} seconds unless new state is seen..." )                    
                elif applicationState != None:
                    print( f"Application state changed from {applicationState} to {currentApplicationState}" )
                elif applicationState == None and currentApplicationState == ApplicationState.NONE:
                    print( f"Searching for Solstice processes..." )

                if currentApplicationState != ApplicationState.NONE:
                    validStatesInSession = True
                    appClosedTimeoutStart = None
                elif currentApplicationState == ApplicationState.NONE and validStatesInSession:
                    appClosedTimeoutStart = time.time()
               
                # Don't store rapid state changes
                if currentApplicationStateSamples and len( currentApplicationStateSamples.samples ) > 0:
                    Session.addStateSamples(currentApplicationStateSamples)

                currentApplicationStateSamples = ApplicationStateSamples( currentApplicationState )
                applicationState = currentApplicationState
                changedStatesLastFrame = True
                showStopGathering = True
            else:
                changedStatesLastFrame = False

        # Close out the profiler after Solstice closes
        if appClosedTimeoutStart != None and time.time() - appClosedTimeoutStart > 5:
            gatherSamples = False

        if applicationState != ApplicationState.NONE and \
            ( Session.secondsPerState == 0 or time.time() - currentApplicationStateSamples.stateStarted < Session.secondsPerState ) and \
            ( len( performanceSnapshot.gpuSnapshots ) > 0 or len( performanceSnapshot.processSnapshots ) > 0 ):
            currentApplicationStateSamples.samples.append( performanceSnapshot )

        if Session.secondsPerState != 0 and time.time() - currentApplicationStateSamples.stateStarted >= Session.secondsPerState and not showStopGathering:
            print("State sample timeout reached. Waiting for state change to start gathering additional samples.")
            showStopGathering = False

        delay = Session.sampleDelay - performanceSnapshot.timeToGatherSample
        # per docs:
        # https://psutil.readthedocs.io/en/latest/#psutil.Process.cpu_percent
        # When interval is 0.0 or None compares process times to system CPU times elapsed since last call, returning immediately. 
        # That means the first time this is called it will return a meaningless 0.0 value which you are supposed to ignore. 
        # In this case is recommended for accuracy that this function be called a second time with at least 0.1 seconds between calls.
        if delay < 0.1:
            delay = 0.1
        time.sleep( delay )

        if Session.sessionLengthSeconds != 0 and time.time() - startTime > Session.sessionLengthSeconds:
            gatherSamples = False

    if currentApplicationStateSamples and len(currentApplicationStateSamples.samples) > 0:
        Session.applicationStateSamples.append(currentApplicationStateSamples)

    if Session.profileGPU and NVidiaLibAvailable:
        nvidia_smi.nvmlShutdown()

    print(str(Session))
    Session.writeCsv()

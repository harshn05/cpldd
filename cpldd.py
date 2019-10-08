import os
import re
import shutil
import argparse
import distutils.dir_util

def GetStreamsBetween(data,str1,str2):
    start = []
    end = []
    sym = (str1==str2)
    if sym is False:
        mask1 = "MASK1"
        mask2 = "MASK2"
        #print("AA")
    else:
        mask1 = "MASK"
        mask2 = "MASK"
     
    Data1 = data.replace(str1,mask1)
    Data = Data1.replace(str2,mask2)    
   
    for m in re.finditer(mask1, Data):
        start.append(m.span()[1])
        #print(m.span())

    for n in re.finditer(mask2, Data):
        end.append(n.span()[0])
        #print(n.span())
    
    l1 = len(start);
    l2 = len(end)
    #print(l1)
    #print(l2)
    if(l1!=l2):
        print("Pairing Not Possible")
        return None
    
    if l1==0:
        return [];
   
  
    if sym is False:
        pairs = l1
        streams = []    
        for i in range(0, pairs):
            tic = start[i]
            toc = end[i]
            streams.append((Data[tic:toc]))
    else:
        pairs = int(l1/2.0)
        streams = []    
        for i in range(0, pairs):
            tic = start[2*i]
            toc = end[2*i+1]
            #print(tic,toc)
            streams.append((Data[tic:toc]))
    
    return streams

def strike(text):
    result = ''
    for c in text:
        result = result + c + '\u0336'
    return result
    
def GetWindowsPath(ShellPath):
    return os.popen('cygpath -m ' + ShellPath).read()

def CopyFileAndPrintStatus(dllfile, outputfolder, i, n):
    newPath = shutil.copy(dllfile, outputfolder)    
    print("Copied DLL Number : " +str(i+1) +"[" +str(int(100*(i+1)/n))  + "%]: " + dllfile)



parser = argparse.ArgumentParser()
parser.add_argument("inputexe")
parser.add_argument('-f', '--force', action='store_true',help="Force System32 Dlls to Copy")
parser.add_argument("outputfolder")


args = parser.parse_args()
inputexe = args.inputexe
outputfolder = args.outputfolder
ignoresystem32 = not args.force
print (ignoresystem32)
distutils.dir_util.mkpath(outputfolder)
copieddlls = 0

print("")
print("==========Copying the Executable Itself==========")
newPath = shutil.copy(inputexe, outputfolder)
print(inputexe +" => " + newPath )

print("")
print("==========Searching For Non Qt Dependencies==========")
RAW = os.popen('ldd ' + inputexe).read()
Files1 = GetStreamsBetween(RAW,'=>',' (')
Files = list(dict.fromkeys(Files1))
n = len(Files)
print("Total " + str(n) + " number of dlls found")
for i in range(n):
    res1 = Files[i].find("?")    
    if(res1<0):
        dllfile = GetWindowsPath(Files[i]).rstrip()
        if (ignoresystem32 is True):
            res2 = Files[i].lower().find("/windows/system32/")
            if (res2>0):
                print("System DLL Ignored: " +str(i+1) +"[" +str(int(100*(i+1)/n))  + "%]: " + strike(dllfile))
            else:
                CopyFileAndPrintStatus(dllfile, outputfolder, i, n)
                copieddlls = copieddlls + 1                
        else:
            CopyFileAndPrintStatus(dllfile, outputfolder, i, n)
            copieddlls = copieddlls + 1
        
    else:
        print("Invalid DLL Ignored..." +str(i+1) +"[" +str(int(100*(i+1)/n))  + "%]: " + strike(" dll not recognized"))
    
print("Total "+ str(copieddlls) + " Number of Non-Qt dlls Copied")    

#######QT Dependencies #####
print("")
print("==========Searching For Qt Dependencies=============")
command = 'windeployqt.exe --release ' + outputfolder +" " + inputexe
print(command)
windepqtoutput = os.popen(command).read()
res = windepqtoutput.lower().find("does not seem to be a qt executable.")
if (res<0):
    print("All Qt Dependencies Copied ")

print("Finished Deployment!!!")
# CPLDD
CPLDD is a deployment script written in Python for Qt or non-Qt C/C++ executable programs. It scans and copies all "dll" dependencies into a user-specified single folder along with the executable itself. CPLDD utilizes the console output of ldd.exe from the MSYS2 project and windeployqt.exe for Qt/C++ applications. In general, the script can be used to deploy executables regardless of the compiler toolchain (MSVC/MSYS2/MinGW/Cygwin) used to build the executable. It is assumed that the shell or CMD environment in which CPLDD is run has all the DLL dependencies available in its path. This means the executable program can be successfully run in the shell or CMD without any DLL load failures. If not, only the partial dependencies available through the shell or CMD will be copied.

## Command line usage:

***python cpldd.py <Input_Exe_File> <Output_Folder_Path>***

***cpldd.exe <Input_Exe_File> <Output_Folder_Path>***

### Optional Arguments:

**-f** : Force dependencies from "system32" folder to be copied to the deployment folder, which is often undesired and un-necessary.

## Sample Output:
The following two screenshots show console outputs when a C++ executable, which is an outcome of very complicated project with tons of dependencies (Qt//VTK/ITK/OpenBlas/muParser/Armadillo/tinyxml2 ...) is deployed using CPLDD. The two screenshots only differ by the compiler tool chain (MSVC vs MSYS2), which can be clearly seen in the output.

  ![MSVC output](screenshot_msvc.PNG)
  ![MSYS2 output](screenshot_msys2.PNG)

Despite all the complicated dependencies, CPLDD has been shown to be successful 100%. 

## Download

Download the latest binaries from the release section: <https://github.com/harshn05/cpldd/releases/latest>.


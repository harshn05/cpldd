#include <iostream>
#include <fstream>
#include <filesystem>
#include <string>
#include <vector>
#include <regex>
#include <algorithm>
#include <cstdlib>

namespace fs = std::filesystem;

// Function to escape special regex characters in a string
std::string escapeRegex(const std::string& str) {
    static const std::regex specialChars(R"([-[\]{}()*+?.,\^$|#\s])");
    return std::regex_replace(str, specialChars, R"(\$&)");
}

// Function to extract streams between two delimiters
std::vector<std::string> GetStreamsBetween(const std::string& data, const std::string& str1, const std::string& str2) {
    std::vector<size_t> start, end;
    std::string mask1 = (str1 == str2) ? "MASK" : "MASK1";
    std::string mask2 = (str1 == str2) ? "MASK" : "MASK2";

    std::string escapedStr1 = escapeRegex(str1);
    std::string escapedStr2 = escapeRegex(str2);

    std::string Data = std::regex_replace(data, std::regex(escapedStr1), mask1);
    Data = std::regex_replace(Data, std::regex(escapedStr2), mask2);

    std::regex re1(mask1), re2(mask2);
    std::sregex_iterator iter1(Data.begin(), Data.end(), re1), iter2(Data.begin(), Data.end(), re2);
    std::sregex_iterator endIter;

    for (; iter1 != endIter; ++iter1) {
        start.push_back(iter1->position() + iter1->length());
    }
    for (; iter2 != endIter; ++iter2) {
        end.push_back(iter2->position());
    }

    if (start.size() != end.size()) {
        std::cerr << "Pairing Not Possible\n";
        return {};
    }

    std::vector<std::string> streams;
    size_t pairs = (str1 == str2) ? start.size() / 2 : start.size();
    for (size_t i = 0; i < pairs; ++i) {
        size_t tic = str1 == str2 ? start[2 * i] : start[i];
        size_t toc = str1 == str2 ? end[2 * i + 1] : end[i];
        streams.push_back(Data.substr(tic, toc - tic));
    }

    return streams;
}

// Function to add strikethrough to text (using combining long stroke)
std::string strike(const std::string& text) {
    std::string result;
    for (char c : text) {
        result += c;
        result += "\u0336"; // Unicode combining long stroke (UTF-8 encoding)
    }
    return result;
}



// Function to convert shell path to Windows path (assumes Cygwin environment)
std::string GetWindowsPath(const std::string& shellPath) {
    std::string command = "cygpath -m " + shellPath;
    char buffer[128];
    std::string result;
    FILE* pipe = popen(command.c_str(), "r");
    if (!pipe) throw std::runtime_error("popen() failed!");
    try {
        while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
            result += buffer;
        }
    } catch (...) {
        pclose(pipe);
        throw;
    }
    pclose(pipe);
    return result;
}

// Function to copy file and print status
void CopyFileAndPrintStatus(const std::string& dllfile, const std::string& outputfolder, int i, int n) {
    fs::path source(dllfile);
    fs::path destination = fs::path(outputfolder) / source.filename();
    fs::copy_file(source, destination, fs::copy_options::overwrite_existing);
    std::cout << "Copied DLL Number : " << (i + 1) << "[" << int(100 * (i + 1) / n) << "%]: " << dllfile << "\n";
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <inputexe> <outputfolder> [-f]\n";
        return 1;
    }

    std::string inputexe = argv[1];
    std::string outputfolder = argv[2];
    bool ignoresystem32 = true;

    if (argc == 4 && std::string(argv[3]) == "-f") {
        ignoresystem32 = false;
    }

    fs::create_directories(outputfolder);

    std::cout << "\n==========Copying the Executable Itself==========\n";
    fs::path newPath = fs::path(outputfolder) / fs::path(inputexe).filename();
    fs::copy_file(inputexe, newPath, fs::copy_options::overwrite_existing);
    std::cout << inputexe << " => " << newPath << "\n";

    std::cout << "\n==========Searching For Non-Qt Dependencies==========\n";
    std::string command = "ldd " + inputexe;
    char buffer[128];
    std::string RAW;
    FILE* pipe = popen(command.c_str(), "r");
    if (!pipe) throw std::runtime_error("popen() failed!");
    try {
        while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
            RAW += buffer;
        }
    } catch (...) {
        pclose(pipe);
        throw;
    }
    pclose(pipe);

    std::vector<std::string> Files = GetStreamsBetween(RAW, "=>", " (");
    Files.erase(std::unique(Files.begin(), Files.end()), Files.end());

    int n = Files.size();
    std::cout << "Total " << n << " number of dlls found\n";
    int copieddlls = 0;
    for (int i = 0; i < n; ++i) {
        if (Files[i].find("?") == std::string::npos) {
            std::string dllfile = GetWindowsPath(Files[i]);
            dllfile.erase(std::remove(dllfile.begin(), dllfile.end(), '\n'), dllfile.end());
            if (ignoresystem32) {
                if (Files[i].find("/WINDOWS/SYSTEM32/") == std::string::npos) {
                    CopyFileAndPrintStatus(dllfile, outputfolder, i, n);
                    ++copieddlls;
                } else {
                    std::cout << "System DLL Ignored: " << (i + 1) << "[" << int(100 * (i + 1) / n) << "%]: " << strike(dllfile) << "\n";
                }
            } else {
                CopyFileAndPrintStatus(dllfile, outputfolder, i, n);
                ++copieddlls;
            }
        } else {
            std::cout << "Invalid DLL Ignored..." << (i + 1) << "[" << int(100 * (i + 1) / n) << "%]: " << strike(" dll not recognized") << "\n";
        }
    }
    std::cout << "Total " << copieddlls << " Number of Non-Qt dlls Copied\n";

    std::cout << "\n==========Searching For Qt Dependencies=============\n";
    command = "windeployqt.exe " + outputfolder + " " + inputexe;
    std::cout << command << "\n";
    pipe = popen(command.c_str(), "r");
    std::string windepqtoutput;
    if (!pipe) throw std::runtime_error("popen() failed!");
    try {
        while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
            windepqtoutput += buffer;
        }
    } catch (...) {
        pclose(pipe);
        throw;
    }
    pclose(pipe);

    if (windepqtoutput.find("does not seem to be a Qt executable.") == std::string::npos) {
        std::cout << "All Qt Dependencies Copied\n";
    }

    std::cout << "Finished Deployment!!!\n";

    return 0;
}

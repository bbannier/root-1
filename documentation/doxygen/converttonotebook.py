#!/usr/bin/env python
# Author: Pau Miquel i Mir <pau.miquel.mir@cern.ch> <pmm1g15@soton.ac.uk>>
# Date: July, 2016
#
# DISCLAIMER: This script is a prototype and a work in progress. Indeed, it is very that
# it may not work for certain tutorials, and that it, or the tutorial, might need to be
# tweaked slightly to ensure full functionality. Please do not hesistate to email the author
# with any questions or with examples that do not work.
#
# REQUIREMENTS: This script needs jupyter to be properly installed, as it uses the python
# package nbformat and calls the shell commands `jupyter nbconvert` and `jupyter trust`. The
# rest of the packages used should be included in a standard installation of python. The script
# is intended to be run on a UNIX based system.
#
# The converttonotebook script creates Jupyter notebooks from raw C++ or python files.
# Particulary, it is indicated to convert the ROOT tutorials found in the ROOT
# repository.
#
# The script should be called from bash with the following format:
#      python /path/to/script/converttonotebook.py /path/to/<macro>.C /path/to/outdir
#
# Indeed the script takes two arguments, the path to the macro and the path to the directory
# where the notebooks will be created
#
# The script's general funcitoning is as follows. The macro to be converted is imported as a string.
# A sereis of modifications are made to this sring, for instacne delimiting where markdown and
# code cells are. Then, this string is converted into ipynb format using a function in the
# nbconvert package. Finally, the notebook is executed and output.
#
# For converting python tutorials it is fairly straightforward. It extracts the decription and
# author information from the header and then removes it. It also converts any comment at the
# beginning of a line into a Markdown cell.
#
# For C++ files the process is slightly more complex. The script separates the functions from the
# main code. The main function is identified as it has the smae name as the macro file. The other
# functions are considered functions. The main function is "extracted"and presented as main code.
# The helper functions are placed in their own code cell with the %%cpp -d magic to enable function
# defintion. Finally, as with Python macros, relevant information is extracted from the header, and
# newline comments are converted into Markdown cells (unless they are in helper functions).
#
# The script creates an .ipynb version of the macro,  with the full output included.
# The files are named:
#     <macro>.C.nbconvert.ipynb
#
# It is called by filter.cxx, which in turn is called by doxygen when processing any file
# in the ROOT repository. filter.cxx only calls convertonotebook.py when the string \notebook
# is found in the header of the turorial, but this script checks for its presence as well.


import re
import os
import sys
import json
import time
import textwrap
import subprocess
from nbformat import v3, v4
from datetime import datetime, date

# List of types that will be considered when looking for a C++ function. If a macro returns a
# type not included on the list, the regular expression will not match it, and thus the function
# will not be properly defined. Thus, any other type returned by function  must be added to this list
# for the script to work correctly.
gTypesList = ["void", "int", "Int_t", "TF1", "string", "bool", "double", "float", "char",
    "TCanvas", "TTree", "TString", "TseqCollection", "Double_t", "TFile", "Long64_t", "Bool_t"]

# -------------------------------------
# -------- Fuction definitions---------
# -------------------------------------

def unindenter(string):
    """
    Returns string with each line unindented by 3 spaces. If line isn't indented, it stays the same.
    """
    newstring = ''
    lines = string.splitlines()
    for line in lines:
        if line.startswith("   "):
            newstring += (line[3:] + "\n")
        else:
            newstring += (line + "\n")

    return newstring


def readHeaderPython(text):
    """
    Extract author and description from header, eliminate header from text. Also returns
    notebook boolean, which is True if the string \notebook is present in the header
    Also determine options (-js, -nodraw, -header) passed in \notebook command, and
    return their booleans
    """
    lines = text.splitlines()

    description = ''
    author = ''
    isNotebook = False
    isJsroot = False
    nodraw = False
    needsHeaderFile = False
    for i, line in enumerate(lines):
        if line.startswith("## \\aut"):
            author = line[11:]
        elif line.startswith("## \\note"):
            isNotebook = True
            if "-js" in line:
                isJsroot = True
            if "-nodraw" in line:
                nodraw = True
            if "-header" in line:
                needsHeaderFile = True
        elif line.startswith("##"):
            if not line.startswith("## \\") and isNotebook:
                description += (line[3:] + '\n')
        else:
            break
    newtext = ''
    for line in lines[i:]:
        newtext += (line + "\n")

    return newtext, description, author, isNotebook, isJsroot, nodraw, needsHeaderFile


def pythonComments(text):
    """
    Converts comments delimited by # or ## and on a new line into a markdown cell.
    For python files only
    """
    text = text.splitlines()
    newtext = ''
    inComment = False
    for i, line in enumerate(text):
        if line.startswith("#") and not inComment:  # True if first line of comment
            inComment = True
            newtext += "# <markdowncell>\n"
            newtext += (line + "\n")
        elif inComment and not line.startswith("#"):  # True if first line after comment
            inComment = False
            newtext += "# <codecell>\n"
            newtext += (line+"\n")
        else:
            newtext += (line+"\n")
    return newtext


def readHeaderCpp(text):
    """
    Extract author and description from header, eliminate header from text. Also returns
    notebook boolean, which is True if the string \notebook is present in the header
    Also determine options (-js, -nodraw, -header) passed in \notebook command, and
    return their booleans
    """
    lines = text.splitlines()

    description = ''
    author = ''
    isNotebook = False
    isJsroot = False
    nodraw = False
    needsHeaderFile = False
    for i, line in enumerate(lines):
        if line.startswith("/// \\aut"):
            author = line[12:]
        if line.startswith("/// \\note"):
            isNotebook = True
            if "-js" in line:
                isJsroot = True
            if "-nodraw" in line:
                nodraw = True
            if "-header" in line:
                needsHeaderFile = True
        if line.startswith("///"):
            if not line.startswith("/// \\") and isNotebook:
                description += ('# ' + line[4:] + '\n')
        else:
            break
    newtext = ''
    for line in lines[i:]:
        newtext += (line + "\n")

    return newtext, description, author, isNotebook, isJsroot, nodraw, needsHeaderFile


def cppFunction(text):
    """
    Extracts main function for the function enclosure by means of regular expression
    """
    functionContentRe = re.compile(r'(?<=\{).*(?=^\})', flags = re.DOTALL | re.MULTILINE)

    match = functionContentRe.search(text)

    if match:
        return match.group()
    else:
        return text

def cppComments(text):
    """
    Converts comments delimited by // and on a new line into a markdown cell. For C++ files only.
    """
    text = text.splitlines()
    newtext = ''
    inComment = False

    for line in text:
        if line.startswith("//") and not inComment:  # True if first line of comment
            inComment = True
            newtext += "# <markdowncell>\n"
            newtext += ("# " + line[2:]+"\n")
        elif inComment and not line.startswith("//"):  # True if first line after comment
            inComment = False
            newtext += "# <codecell>\n"
            newtext += (line+"\n")
        elif inComment and line.startswith("//"):  # True if in the middle of a comment block
            newtext += ("# " + line[2:] + "\n")
        else:
            newtext += (line+"\n")

    return newtext


def split(text):
    """
    Splits the text string into main, helpers, and rest. main is the main function,
    i.e. the function tha thas the same name as the macro file. Helpers is a list of
    strings, each a helper function, i.e. any other function that is not the main funciton.
    Finally, rest is a string containing any top-level code outside of any function.
    Comments immediately prior to a helper cell are converted into markdown cell,
    added to the helper, and removed from rest.
    Intended for C++ files only.
    """
    
    functionReString="("
    for cpptype in gTypesList:
        functionReString += ("^%s|") % cpptype
    
    functionReString = functionReString[:-1] + r")\s?\*?\s?[\w:]*?\s?\([^\)]*\)\s*\{.*?^\}"
    
    functionRe = re.compile(functionReString, flags = re.DOTALL | re.MULTILINE)
    #functionre = re.compile(r'(^void|^int|^Int_t|^TF1|^string|^bool|^double|^float|^char|^TCanvas|^TTree|^TString|^TSeqCollection|^Double_t|^TFile|^Long64_t|^Bool_t)\s?\*?\s?[\w:]*?\s?\([^\)]*\)\s*\{.*?^\}', flags = re.DOTALL | re.MULTILINE)
    functionMatches = functionRe.finditer(text)
    helpers = []
    main = ""
    for matchString in [match.group() for match in functionMatches]:
        if tutName == findFunctionName(matchString):  # if the name of the funcitn is that of the macro
            main = matchString
        else:
            helpers.append(matchString)

    # Create rest by replacing the main and helper funcitons with blank strings
    rest = text.replace(main, "")

    for helper in helpers:
        rest = rest.replace(helper, "")
    
    newHelpers = []
    lines = text.splitlines()
    for helper in helpers:      # For each helper function
        for i, line in enumerate(lines):                    # Look through the lines until the
            if line.startswith(helper[:helper.find("\n")]):  # first line of the helper is found
                j = 1
                commentList = []
                while lines[i-j].startswith("//"):   # Add comment lines immediately prior to list
                    commentList.append(lines[i-j])
                    j += 1
                if commentList:                  # Convert list to string
                    commentList.reverse()
                    helperDescription = ''
                    for comment in commentList:
                        if comment == "//":
                            helperDescription += "\n\n"  # Two newlines to create hard break in Markdown
                        else:
                            helperDescription += comment[2:]
                            rest = rest.replace(comment, "")
                    break
                else:   # If no comments are found create generic description
                    helperDescription = "A helper function is created:"
                    break

        if findFunctionName(helper) != "main":  # remove void main function
            newHelpers.append("\n# <markdowncell>\n " + helperDescription + " \n# <codecell>\n%%cpp -d\n" + helper)

    rest = rest.rstrip("\n /")  # remove newlines and empty comments at the end of string

    return main, newHelpers, rest


def findFunctionName(text):
    """
    Takes a string representation of a C++ funciton as an input,
    finds and returns the name of the function
    """
    functionNameReString="(?<="
    for cpptype in gTypesList:
        functionNameReString += ("(?<=%s)|") % cpptype
    
    functionNameReString = functionNameReString[:-1] + r")\s?\*?\s?[^\s]*?(?=\s?\()"
    
    functionNameRe = re.compile(functionNameReString, flags = re.DOTALL | re.MULTILINE)

    #functionnamere = re.compile(r'(?<=(?<=int)|(?<=void)|(?<=TF1)|(?<=Int_t)|(?<=string)|(?<=double)|(?<=Double_t)|(?<=float)|(?<=char)|(?<=TString)|(?<=bool)|(?<=TSeqCollection)|(?<=TCanvas)|(?<=TTree)|(?<=TFile)|(?<=Long64_t)|(?<=Bool_t))\s?\*?\s?[^\s]*?(?=\s?\()', flags = re.DOTALL | re.MULTILINE)
    match = functionNameRe.search(text)
    functionname = match.group().strip(" *")
    return functionname


def processmain(text):
    """
    Evaluates whether the main function returns a TCanvas or requires input. If it
    does then the keepfunction flag is True, meaning the function wont be extracted
    by cppFunction. If the initial condition is true then an extra cell is added
    before at the end that calls the main function is returned, and added later.
    """
    callMainFunction = ''
    keepfunction = False

    argumentesre = re.compile(r'(?<=\().*?(?=\))', flags = re.DOTALL | re.MULTILINE)
    arguments = argumentesre.search(text)
    if text:
        if text.startswith("TCanvas") or len(arguments.group()) > 3:
            keepfunction = True
            functionname = findFunctionName(text)
            callMainFunction = "\n# <markdowncell> \n# Call the main function \n# <codecell>\n%s();" % functionname

    return text, callMainFunction, keepfunction

# now define text transformers
def removePaletteEditor(code):
    return code.replace("img->StartPaletteEditor();", "")

def runEventExe(code):
    if "copytree" in tutName:
        return "# <codecell> \n.! $ROOTSYS/test/eventexe 1000 1 1 1 \n" + code
    return code

def getLibMathMore(code):
    if "quasirandom" == tutName:
        return "# <codecell> \ngSystem->Load(\"libMathMore\"); \n# <codecell> \n" + code
    return code

def fixes(code):
    codeTransformers=[removePaletteEditor, runEventExe, getLibMathMore]

    for transformer in codeTransformers:
        code = transformer(code)
    return code

def isCpp():
    return extension in ("C", "c", "cpp", "C++", "cxx")


# -------------------------------------
# ------------ Main Program------------
# -------------------------------------


def mainfunction(text):
    """
    Main function. Calls all other functions, depending on whether the macro input is in python or c++.
    It adds the header information. Also, it adds a cell that draws all canvases. The working text is
    then converted to a version 3 jupyter notebook, subsequently updated to a version 4. Then, metadata
    associated with the language the macro is written in is attatched to he notebook. Finally the
    notebook is executed and output as a Jupyter notebook.
    """
    # Modify text from macros to suit a notebook
    if isCpp():
        main, helpers, rest = split(text)
        main, callMainFunction, keepfunction = processmain(main)
        if not keepfunction:
            main = cppComments(unindenter(cppFunction(main)))  # Remove function, Unindent, and convert comments to Markdown cells
        rest = cppComments(rest)  # Convert top level code comments to Markdown cells

        # Construct text by starting with top level code, then the helper functions, and finally the main function.
        # Also add cells for headerfile, or keepfunction
        if needsHeaderFile:
            text = "# <markdowncell>\n# The header file must be copied to the current directory\n# <codecell>\n.!cp %s%s.h .\n# <codecell>\n" % (tutRelativePath, tutName)
            text += rest
        else:
            text = rest

        for helper in helpers:
            text += helper

        if keepfunction:
            text += "\n# <markdowncell>\n# The main function is defined\n# <codecell>\n%%cpp -d\n"
        else:
            text += "\n# <codecell>\n"
        text += main
        if callMainFunction:
            text += callMainFunction

    if extension == "py":
        text = pythonComments(text)  # Convert comments into Markdown cells
    

    # Perform last minute fixes to the notebook, used for specific fixes needed by some tutorials
    text = fixes(text)

    # Add the title and header of the notebook
    text = "# <markdowncell> \n# # %s\n%s# \n# \n# **Author:** %s  \n# <small>This notebook tutorial" \
        "was automatically generated from the macro found in the ROOT repository " \
        "on %s.</small>\n# <codecell>\n%s" % (tutName.title(), description, author, date, text)

    # Add cell at the end of the notebook that draws all the canveses. Add a Markdown cell before explaining it.
    if isJsroot:
        if isCpp():
            text += "\n# <markdowncell> \n# Draw all canvases \n# <codecell>\n%jsroot on\ngROOT->GetListOfCanvases()->Draw()"
        if extension == "py":
            text += "\n# <markdowncell> \n# Draw all canvases \n# <codecell>\n%jsroot on\nfrom ROOT import gROOT \ngROOT.GetListOfCanvases().Draw()"

    elif not nodraw:
        if isCpp():
            text += "\n# <markdowncell> \n# Draw all canvases \n# <codecell>\ngROOT->GetListOfCanvases()->Draw()"
        if extension == "py":
            text += "\n# <markdowncell> \n# Draw all canvases \n# <codecell>\nfrom ROOT import gROOT \ngROOT.GetListOfCanvases().Draw()"

    print text

    # Create a notebook from the working text
    nbook = v3.reads_py(text)
    nbook = v4.upgrade(nbook)  # Upgrade v3 to v4

    # Load notebook string into json format, essentially creating a dictionary
    json_data = json.loads(v4.writes(nbook))

    # add the corresponding metadata
    if extension == "py":
        json_data[u'metadata'] = {
            "kernelspec": {
                "display_name": "Python 2",
                "language": "python",
                "name": "python2"
            },
            "language_info": {
                "codemirror_mode": {
                    "name": "ipython",
                    "version": 2
                },
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython2",
                "version": "2.7.10"
            }
        }
    elif isCpp():
        json_data[u'metadata'] = {
            "kernelspec": {
                "display_name": "ROOT C++",
                "language": "c++",
                "name": "root"
            },
            "language_info": {
                "codemirror_mode": "text/x-c++src",
                "file_extension": ".C",
                "mimetype": " text/x-c++src",
                "name": "c++"
            }
        }

    # write the json file with the metadata
    with open(outPathName, 'w') as fout:
        json.dump(json_data, fout, indent=1, sort_keys=True)

    print time.time() - starttime
    # Call commmand that executes the notebook and creates a new notebook with the output
    r = subprocess.call(["jupyter", "nbconvert", "--ExecutePreprocessor.timeout=90",  "--to=notebook", "--execute",  outPathName])
    if r != 0:
        sys.stderr.write("NOTEBOOK_CONVERSION_WARNING: Nbconvert failed for notebook %s with return code %s\n" %(outname,r))
    if isJsroot:
        subprocess.call(["jupyter", "trust",  os.path.join(outdir + outnameconverted)])
    os.remove(outPathName)


if __name__ == "__main__":

    # -------------------------------------
    # ----- Preliminary definitions--------
    # -------------------------------------

    # Extract and define the name of the file as well as its derived names
    tutPathName = str(sys.argv[1])
    tutPath = os.path.dirname(tutPathName)
    if tutPath.split("/")[-2] == "tutorials":
        tutRelativePath = "$ROOTSYS/tutorials/%s/" % tutPath.split("/")[-1]
    tutFileName = os.path.basename(tutPathName)
    tutName, extension = tutFileName.split(".")
    outname = tutFileName + ".ipynb"
    outnameconverted = tutFileName + ".nbconvert.ipynb"

    # Extract output directory
    try:
        outdir = str(sys.argv[2])
    except:
        outdir = tutPath

    outPathName = os.path.join(outdir, outname)
    # Find and define the time and date this script is run
    date = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

    # -------------------------------------
    # -------------------------------------
    # -------------------------------------

    # Set DYLD_LIBRARY_PATH. When run without root access or as a different user, epecially from Mac systems,
    # it is possible for security reasons that the enviornment does not include this definition, so it is manually defined.
    os.environ["DYLD_LIBRARY_PATH"] = os.environ["ROOTSYS"] + "/lib"

    # Open the file to be converted
    with open(tutPathName) as fin:
        text = fin.read()

    # Extract information from header and remove header from text
    if extension == "py":
        text, description, author, isNotebook, isJsroot, nodraw, needsHeaderFile = readHeaderPython(text)
    elif isCpp():
        text, description, author, isNotebook, isJsroot, nodraw, needsHeaderFile = readHeaderCpp(text)

    if isNotebook:
        starttime = time.time()
        mainfunction(text)
        print time.time() - starttime
    else:
        pass

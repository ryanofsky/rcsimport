#!/usr/bin/env python

import sys
import getopt
import os
import re
import datetime
import stat
import xml.dom.minidom
import xml.dom.ext

import ezt

# ===================================================================
# Generate RCS Files

def rcsimport(files, out, info):
  meta = []
  data = []

  for i in xrange(len(files)-1, -1, -1):
    file = files[i]
    author, log = info.get(file) or ("", "")

    m = kw(revision="1.%i" % (i+1),
           date=date_str(mtime(file)),
           author=author,
           dead=ezt.boolean(0),
           branches=(),
           next=None,
           keywords=(),
           filename=file)

    if meta:
      meta[-1].next = m.revision
      prevfile = meta[-1].filename
    else:
      prevfile = None

    meta.append(m)

    d = kw(revision=m.revision,
           log=log,
           text=diff_cb(prevfile, file))

    data.append(d)

  vars = kw(head=meta[0].revision,
            branch=None,
            access=None,
            symbols=(),
            locks=None,
            strict=None,
            comment="# ",
            expand=None,
            keywords=(),
            meta=meta,
            desc="",
            data=data,
            string=string_cb)

  RCSFILE.generate(out, vars)

RCSFILE_TEXT = """|
head	[head];
[if-any branch]|
  |branch	[branch];
[end]|
access[if-any access]	[access][end];
symbols|
[for symbols]
  |	[symbols.name]:[symbols.number]|
[end];
locks[if-any locks]	[locks][end]; [if-any strict] strict;[end]
comment [string comment];
[if-any expand]|
  |expand	[string expand];
[end]|
[for keywords]|
  |[keywords.name]	[keywords.value];
[end]|

[for meta]
  |[meta.revision]
  |date	[meta.date];	author [meta.author];	|
  |state [if-any meta.dead]dead[else]Exp[end];
  |branches|
  [for meta.branches]
    |	[meta.branches]|
  [end];
  |next	[if-any meta.next][meta.next][end];
  [for meta.keywords]|
    |[meta.keywords.name]	[meta.keywords.value];
  [end]|
[end]|


desc
[string desc]

[for data]
  |[data.revision]
  |log
  |[string data.log]
  |text
  |[string data.text]
[end]
"""

RCSFILE = ezt.Template(compress_whitespace=False, trim_whitespace=True)
RCSFILE.parse(RCSFILE_TEXT)

# ===================================================================
# Generate and Parse XML Commit Information

def info_generate(files, fp):
  ### See if there's a way to pretty print this incrementally without building
  ### up the whole tree in memory. If not, can use EZT to manually pretty
  ### print it.

  doc = xml.dom.minidom.Document()
  history = doc.createElement("history")
  doc.appendChild(history)

  for file in files:
    lastcopy = None

    for copy in file:
      commit = doc.createElement("commit")
      history.appendChild(commit)

      path = doc.createElement("path")
      commit.appendChild(path)
      pathtext = doc.createTextNode(copy)
      path.appendChild(pathtext)

      author = doc.createElement("author")
      commit.appendChild(author)
      authortext = doc.createTextNode(fowner(copy))
      author.appendChild(authortext)

      log = doc.createElement("log")
      commit.appendChild(log)
      logtext = doc.createTextNode(lastcopy
                                   and "meld %s %s" % (lastcopy, copy)
                                   or "gvim %s" % copy)
      log.appendChild(logtext)

      lastcopy = copy

  xml.dom.ext.PrettyPrint(doc, fp)

def info_parse(fp):
  ### could read the file incrementally too (sax) or maybe look up data
  ### in dom instead of building dictionary (xpath)
  files = {}
  doc = xml.dom.minidom.parse(fp)
  history = xml_elem(doc, "history")
  for commit in xml_elems(history, "commit"):
    author = xml_text(xml_elem(commit, "author"))
    log = xml_text(xml_elem(commit, "log"))
    for filenode in xml_elems(commit, "path"):
      file = xml_text(filenode)
      files[file] = (author, log)
  return files

# ===================================================================
# Recurse Directories

_re_backup = re.compile(r"^(.*?)(?:\.(\d+))?$")

def find_copies(in_dir):
  for relpath, dirs, files in relwalk(in_dir):
    file_copies = {}
    for file in files:
      basefile, ordinal = _re_backup.match(file).groups()
      basepath = os.path.join(relpath, basefile)
      path = os.path.join(in_dir, relpath, file)
      if ordinal is None:
        ordinal = "" # strings compare higher than ints
      else:
        ordinal = int(ordinal)

      try:
        list = file_copies[basepath]
      except KeyError:
        file_copies[basepath] = [(ordinal, path)]
      else:
        list.append((ordinal, path))

    for basepath, copies in file_copies.iteritems():
      copies.sort()
      yield relpath, basepath, [path for ordinal, path in copies]

def find_copies_plain(in_dir):
  for relpath, basepath, copies in find_copies(in_dir):
    yield copies

# ===================================================================
# Template Utilities

class kw:
  def __init__(self, **kwargs):
    vars(self).update(kwargs)

def string_cb(ctx, value, *args):
  ctx.write("@")
  ctx.printers.append(string_escape_cb)
  try:
    ctx.write(value, args)
  finally:
    ctx.printers.pop()
  ctx.write("@")

def string_escape_cb(ctx, value):
  ctx.write(str(value).replace("@", "@@"))

class diff_cb:
  def __init__(self, file1, file2):
    self.file1 = file1
    self.file2 = file2

  def __call__(self, ctx):
    if self.file1 is None:
      fp = open(self.file2, "rb")
    else:
      cmd = argv_to_command_string(["diff", "-n", "-a", "--binary",
                                    self.file1, self.file2])
      fp = os.popen(cmd, "rb")

    try:
      ctx.write(fp)
    finally:
      fp.close()

def date_str(date):
  return ("%04i.%02i.%02i.%02i.%02i.%02i"
          % (date.year, date.month, date.day,
             date.hour, date.minute, date.second))

# ===================================================================
# Directory Crawling Utilities

def relwalk(top, *args, **kwargs):
  """like os.walk() but yield paths relative to top directory"""
  len_top = len(top)
  for dirpath, dirs, files in os.walk(top, *args, **kwargs):
    assert dirpath[:len_top] == top
    assert len(dirpath) == len_top or dirpath[len_top] == os.sep
    relpath = dirpath[len_top+1:]
    yield relpath, dirs, files

def mtime(file):
  return datetime.datetime.utcfromtimestamp(os.path.getmtime(file))

try:
  import pwd
except ImportError:
  def fowner(file):
    return None
else:
  def fowner(file):
    return pwd.getpwuid(os.stat(file)[stat.ST_UID]).pw_name

# ===================================================================
# Shell Utilities

def escape_shell_arg(str):
  return "'" + str.replace("'", "'\\''") + "'"

def argv_to_command_string(argv):
  return " ".join(map(escape_shell_arg, argv))

# ===================================================================
# XML Utilities

def xml_elems(node, name):
 for e in node.childNodes:
   if e.nodeType == e.ELEMENT_NODE and e.localName == name:
     yield e

def xml_elem(node, name):
  return xml_elems(node, name).next()

def xml_text(node):
  for e in node.childNodes:
    if e.nodeType == e.TEXT_NODE:
      return e.nodeValue

# ===================================================================
# Command Line Interface

def usage():
  print "Usage: rcsimport.py [OPTION...] SOURCE..."
  print "Create rcs file(s) from history stored in flat files"
  print
  print "Options:"
  print "  -o, --output=PATH    Store output in specified file path"
  print "                       (or directory path in recursive mode)"
  print "  -r, --recurse        Recursively crawl source directory, producing"
  print "                       RCS histories of all files, using backup files"
  print "                       (*.0, *.1, *.2, *.10, ...) for past history."
  print "  -i, --info=FILE      Read commit information from specified XML file"
  print "  -g, --generate-info  Don't produce any RCS files, just generate"
  print "                       XML file for the import operation which can"
  print "                       be edited and passed to --info"
  print "      --help           Display this help"
  print
  print "Examples:"
  print "  rcsimport.py -o source.c,v source.c.001 source.c.002 source.c"
  print "    Create RCS file `source.c,v' from specified source revisions"
  print "  rcsimport.py -g -o project.xml -r project_dir"
  print "    Generate `project.xml' file that can be filled in with log and"
  print "    author information for recursive import of `project_dir'"
  print "  rcsimport.py -o rcs_dir -i project.xml -r project_dir"
  print "    Output RCS files in `rcs_dir' using log and author information"
  print "    from `project.xml' and flat file history from `project_dir'"

def error(s):
  print >> sys.stderr, "Error:", s
  print >> sys.stderr, "(run `rcsimport.py --help' for help)"
  sys.exit(1)

class Options:
  def __init__(self):
    self.output = None
    self.info = {}
    self.recurse = False
    self.generate_info = False

def main():
  try:
    opts, args = getopt.getopt(sys.argv[1:], "o:ri:g",
                               ["output=", "recurse", "info=", "generate-info",
                                "help"])
  except getopt.GetoptError, e:
    error(str(e))

  options = Options()
  for o, a in opts:
    if o in ("-o", "--output"):
      options.output = a
    elif o in ("-r", "--recurse"):
      options.recurse = True
    elif o in ("-i", "--info"):
      options.info = info_parse(a)
    elif o in ("-g", "--generate-info"):
      options.generate_info = True
    elif o == "--help":
      usage()
      sys.exit()

  if options.recurse:
    if len(args) != 1:
      error("wrong number of arguments, recursive mode must be used with a "
            "single source directory")
    elif not os.path.isdir(args[0]):
      error("source path `%s' is not a directory" % args[0])

    if options.generate_info:
      if options.output:
        out = open(options.output, "w")
      else:
        out = sys.stdout

      try:
        info_generate(find_copies_plain(args[0]), out)
      finally:
        out.close()

    else:
      if not options.output:
        error("no output directory specified")
      elif not os.path.isdir(options.output):
        error("output path `%s' is not a directory" % options.output)

      lastrelpath = None
      for relpath, basepath, copies in find_copies(args[0]):
        outpath = os.path.join(options.output, relpath)
        if relpath and lastrelpath != relpath:
          os.makedirs(outpath)

        outpath = os.path.join(options.output, basepath + ",v")
        print >> sys.stderr, ("Writing `%s' [%i revisions]"
                              % (outpath, len(copies)))
        out = open(outpath, "wb")
        try:
          rcsimport(copies, out, options.info)
        finally:
          out.close()

        lastrelpath = relpath

  else:
    if not args:
      error("wrong number of arguments, specify at least one input file")

    if options.output:
      out = open(options.output, options.generate_info and "w" or "wb")
    else:
      out = sys.stdout

    if options.generate_info:
      info_generate([args], out)
    else:
      rcsimport(args, out, options.info)

if __name__ == "__main__":
  main()


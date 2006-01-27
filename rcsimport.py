#!/usr/bin/env python

import sys
import getopt
import os
import re
import datetime
import xml.dom.minidom
import xml.dom.ext
import stat

import ezt

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
  |date	[meta.date];	author [meta.author];	state |
  |[if-any meta.dead]dead[else]Exp[end];
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

RCSFILE = ezt.Template(compress_whitespace=False, trim_whitespace=1)
RCSFILE.parse(RCSFILE_TEXT)

def string_cb(ctx, value, *args):
  ctx.write("@")
  ctx.write(value, args, string_escape_cb)
  ctx.write("@")

def string_escape_cb(ctx, obj):
  ctx.write(str(obj).replace("@", "@@"))

def date_str(date):
  return ("%04i.%02i.%02i.%02i.%02i.%02i"
          % (date.year, date.month, date.day,
             date.hour, date.minute, date.second))

def writercs(files, options):
  if options.output:
    out = open(options.output, "wb")
  else:
    out = sys.stdout

  if options.generate_info:
    return info_generate(files, out)

  meta = []
  data = []

  for i in xrange(len(files)-1, -1, -1):
    file = files[i]
    m = kw(revision="1.%i" % (i+1),
           date=date_str(mtime(file)),
           author="billy",
           dead=ezt.boolean(0),
           branches=(),
           next=None,
           keywords=(),
           filename=file)

    if meta:
      fp = diff_fp(meta[-1].filename, file)
      meta[-1].next = m.revision
    else:
      fp = open(file, "rb")
      pass

    d = kw(revision=m.revision,
           log="billy did it",
           text=fp)

    meta.append(m)
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

def info_generate(files, fp):
  ### See if there's a way to pretty print this incrementally without building
  ### up the whole tree in memory. If not, can use EZT to manually pretty
  ### print it.

  doc = xml.dom.minidom.Document()
  history = doc.createElement("history")
  doc.appendChild(history)

  lastfile = None

  for file in files:
    commit = doc.createElement("commit")
    history.appendChild(commit)

    path = doc.createElement("path")
    commit.appendChild(path)
    pathtext = doc.createTextNode(file)
    path.appendChild(pathtext)

    author = doc.createElement("author")
    commit.appendChild(author)
    authortext = doc.createTextNode(fowner(file))
    author.appendChild(authortext)

    log = doc.createElement("log")
    commit.appendChild(log)
    logtext = doc.createTextNode(lastfile
                                 and "meld %s %s" % (lastfile, file)
                                 or "gvim %s" % file)
    log.appendChild(logtext)

    lastfile = file

  xml.dom.ext.PrettyPrint(doc)

def info_parse(fp):
  ### could read the file incrementally too
  files = {}
  doc = xml.dom.minidom.parse(fp)
  history = xml_elem(doc, "history")
  for commit in xml_elems(history, "commit"):
    author = xml_text(xml_elem(commit, "author"))
    log = xml_text(xml_elem(commit, "log"))
    for filenode in xml_elems(commit, "path"):
      file = xml_text(filenode)
      files[file] = kw(author=author, log=log)

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

def diff_fp(file1, file2):
  cmd = argv_to_command_string(["diff", "-n", "-a", "--binary", file1, file2])
  return os.popen(cmd, "rb")

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
# Single Input

def import_backup(in_dir, out_dir, options):
  for relpath, dirs, files in relwalk(in_dir):
    file_copies = {}
    for file in files:
      path = os.path.join(relpath, file)

      basepath, ordinal = _re_backup.match(path).groups()
      if ordinal is None:
        basepath = path
        ordinal = ""
      else:
        ordinal = int(ordinal)

      try:
        list = file_copies[basepath]
      except KeyError:
        file_copies[basepath] = [(ordinal, path)]
      else:
        list.append((ordinal, path))

    for basepath, copies in file_copies.items():
      copies.sort()
      print "Copies of %s:" % basepath
      for ordinal, copypath in copies:
        print "  %s" % copypath

_re_backup = re.compile(r"^(.*?)(?:\.(\d+))?$")

# ===================================================================
# Utility Functions

def escape_shell_arg(str):
  return "'" + str.replace("'", "'\\''") + "'"

def argv_to_command_string(argv):
  return " ".join(map(escape_shell_arg, argv))

def relwalk(top, *args, **kwargs):
  """like os.walk() but yield paths relative to top directory"""
  len_top = len(top)
  for dirpath, dirs, files in os.walk(top, *args, **kwargs):
    assert dirpath[:len_top] == top
    assert len(dirpath) == len_top or dirpath[len_top] == os.sep
    relpath = dirpath[len_top+1:]
    yield relpath, dirs, files

class kw:
  def __init__(self, **kwargs):
    vars(self).update(kwargs)

# ===================================================================
# Command Line Interface

def usage():
  print "Usage: rcsimport.py [OPTION...] SOURCE..."
  print "Create an rcs file(s) from history stored in flat files"
  print
  print "Options:"
  print "  -o, --output         Store output in specified file or directory"
  print "  -r, --recurse        Recursively crawl source directory, producing"
  print "                       RCS histories of all files, using backup files"
  print "                       (*.0, *.1, *.2, *.10, ...) for past history."
  print "  -i, --info           Read commit information from specified XML file"
  print "  -g, --generate-info  Don't produce any RCS files, just generate"
  print "                       XML file for this import operation which can"
  print "                       be filled with commit info"
  print "      --help           Display this help"

def error(s):
  print >> sys.stderr, "Error:", s
  print >> sys.stderr, "(run `rcsimport.py --help' for help)"
  sys.exit(1)

class Options:
  def __init__(self):
    self.output = None
    self.info = None
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
      self.recurse = True
    elif o in ("-i", "--info"):
      options.info = info_parse(a)
    elif o in ("-g", "--generate-info"):
      options.generate_info = True
    elif o == "--help":
      usage()
      sys.exit()

  if options.recurse:
    if len(args) != 1:
      error("wrong number of arguments, recursive mode must be used with one "
            "directory at a time")
    import_backup(args[0], options.output, options)
  else:
    if not args:
      error("wrong number of arguments, specify at least one input file")
    writercs(args, options)

if __name__ == "__main__":
  main()


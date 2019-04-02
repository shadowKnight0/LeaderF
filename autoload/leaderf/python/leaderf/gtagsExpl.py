#!/usr/bin/env python
# -*- coding: utf-8 -*-

import vim
import re
import os
import os.path
import subprocess
from .utils import *
from .explorer import *
from .manager import *

if sys.version_info >= (3, 0):
    import queue as Queue
else:
    import Queue

#*****************************************************
# GtagsExplorer
#*****************************************************
class GtagsExplorer(Explorer):
    def __init__(self):
        self._root_markers = lfEval("g:Lf_RootMarkers")
        self._db_location = os.path.join(lfEval("g:Lf_CacheDirectory"),
                                     '.LfCache',
                                     'gtags')
        self._project_root = ""

        self._task_queue = Queue.Queue()
        self._worker_thread = threading.Thread(target=self._processTask)
        self._worker_thread.daemon = True
        self._worker_thread.start()

    def __del__(self):
        self._task_queue.put(None)
        self._worker_thread.join()

    def _processTask(self):
        while True:
            try:
                task = self._task_queue.get()
                if task is None:
                    break
                task()
            except Exception as e:
                lfPrintError(e)

    def getContent(self, *args, **kwargs):
        return self.getFreshContent(*args, **kwargs)

    def getFreshContent(self, *args, **kwargs):
        has_new_tagfile = False
        has_changed_tagfile = False
        filenames = [name for name in self._file_tags]
        for tagfile in vim.eval("tagfiles()"):
            tagfile = os.path.abspath(tagfile)
            mtime = os.path.getmtime(tagfile)
            if tagfile not in self._file_tags:
                has_new_tagfile = True
                with lfOpen(tagfile, 'r', errors='ignore') as f:
                    self._file_tags[tagfile] = [mtime, f.readlines()[6:]]
            else:
                filenames.remove(tagfile)
                if mtime != self._file_tags[tagfile][0]:
                    has_changed_tagfile = True
                    with lfOpen(tagfile, 'r', errors='ignore') as f:
                        self._file_tags[tagfile] = [mtime, f.readlines()[6:]]

        for name in filenames:
            del self._file_tags[name]

        if has_new_tagfile == False and has_changed_tagfile == False:
            return self._tag_list
        else:
            self._tag_list = list(itertools.chain.from_iterable((i[1] for i in self._file_tags.values())))
            return self._tag_list

    def _nearestAncestor(self, markers, path):
        """
        return the nearest ancestor path(including itself) of `path` that contains
        one of files or directories in `markers`.
        `markers` is a list of file or directory names.
        """
        if os.name == 'nt':
            # e.g. C:\\
            root = os.path.splitdrive(os.path.abspath(path))[0] + os.sep
        else:
            root = '/'

        path = os.path.abspath(path)
        while path != root:
            for name in markers:
                if os.path.exists(os.path.join(path, name)):
                    return path
            path = os.path.abspath(os.path.join(path, ".."))

        for name in markers:
            if os.path.exists(os.path.join(path, name)):
                return path

        return ""

    def _isVersionControl(self, filename):
        if self._project_root and filename.startswith(self._project_root):
            return True

        ancestor = self._nearestAncestor(self._root_markers, os.path.dirname(filename))
        if ancestor:
            self._project_root = ancestor
            return True
        else:
            return False

    def _db_path(self, filename):
        """
        return the (dbpath,  whether gtags exists)
        """
        if self._project_root and filename.startswith(self._project_root):
            root = self._project_root
        else:
            ancestor = self._nearestAncestor(lfEval("g:Lf_RootMarkers"), os.path.dirname(filename))
            if ancestor:
                self._project_root = ancestor
                root = self._project_root
            else:
                root = os.getcwd()
        
        if os.name == 'nt':
            db_folder = re.sub(r'[\/]', '%', root.replace(':\\', '%', 1))
        else:
            db_folder = root.replace('/', '%')

        dbpath = os.path.join(self._db_location, db_folder)
        return (dbpath, os.path.exists(os.path.join(dbpath, "GTAGS")))

    def updateGtags(self, filename, single_update, auto):
        self._task_queue.put(partial(self._update, filename, single_update, auto))

    def _update(self, filename, single_update, auto):
        if filename == "":
            return

        if single_update:
            dbpath, exists = self._db_path(filename)
            if exists:
                cmd = "gtags --single-update %s %s" % (filename, dbpath)
                subprocess.Popen(cmd, shell=True)
        elif not auto:
            dbpath, exists = self._db_path(filename)
            if not os.path.exists(dbpath):
                os.makedirs(dbpath)
            cmd = "gtags %s" % dbpath
            subprocess.Popen(cmd, shell=True)
        elif self._isVersionControl(filename):
            dbpath, exists = self._db_path(filename)
            if not exists:
                if not os.path.exists(dbpath):
                    os.makedirs(dbpath)
                cmd = "gtags %s" % dbpath
                subprocess.Popen(cmd, shell=True)

    def getStlCategory(self):
        return 'Gtags'

    def getStlCurDir(self):
        return escQuote(lfEncode(os.getcwd()))


#*****************************************************
# GtagsExplManager
#*****************************************************
class GtagsExplManager(Manager):
    def __init__(self):
        super(GtagsExplManager, self).__init__()
        self._match_ids = []

    def _getExplClass(self):
        return GtagsExplorer

    def _defineMaps(self):
        lfCmd("call leaderf#Gtags#Maps()")

    def _acceptSelection(self, *args, **kwargs):
        if len(args) == 0:
            return
        line = args[0]
        # {tagname}<Tab>{tagfile}<Tab>{tagaddress}[;"<Tab>{tagfield}..]
        tagname, tagfile, right = line.split('\t', 2)
        res = right.split(';"\t', 1)
        tagaddress = res[0]
        try:
            if kwargs.get("mode", '') == 't':
                lfCmd("tab drop %s" % escSpecial(tagfile))
            else:
                lfCmd("hide edit %s" % escSpecial(tagfile))
        except vim.error as e: # E37
            lfPrintError(e)

        if tagaddress[0] not in '/?':
            lfCmd(tagaddress)
        else:
            lfCmd("norm! gg")

            # In case there are mutiple matches.
            if len(res) > 1:
                result = re.search('(?<=\t)line:\d+', res[1])
                if result:
                    line_nr = result.group(0).split(':')[1]
                    lfCmd(line_nr)
                else: # for c, c++
                    keyword = "(class|enum|struct|union)"
                    result = re.search('(?<=\t)%s:\S+' % keyword, res[1])
                    if result:
                        tagfield = result.group(0).split(":")
                        name = tagfield[0]
                        value = tagfield[-1]
                        lfCmd("call search('\m%s\_s\+%s\_[^;{]*{', 'w')" % (name, value))

            pattern = "\M" + tagaddress[1:-1]
            lfCmd("call search('%s', 'w')" % escQuote(pattern))

        if lfEval("search('\V%s', 'wc')" % escQuote(tagname)) == '0':
            lfCmd("norm! ^")
        lfCmd("norm! zz")
        lfCmd("setlocal cursorline! | redraw | sleep 20m | setlocal cursorline!")

    def updateGtags(self, filename, single_update, auto=True):
        self._getExplorer().updateGtags(filename, single_update, auto)

    def _getDigest(self, line, mode):
        """
        specify what part in the line to be processed and highlighted
        Args:
            mode: 0, return the full path
                  1, return the name only
                  2, return the directory name
        """
        return line[:line.find('\t')]

    def _getDigestStartPos(self, line, mode):
        """
        return the start position of the digest returned by _getDigest()
        Args:
            mode: 0, return the start postion of full path
                  1, return the start postion of name only
                  2, return the start postion of directory name
        """
        return 0

    def _createHelp(self):
        help = []
        help.append('" <CR>/<double-click>/o : open file under cursor')
        help.append('" x : open file under cursor in a horizontally split window')
        help.append('" v : open file under cursor in a vertically split window')
        help.append('" t : open file under cursor in a new tabpage')
        help.append('" i/<Tab> : switch to input mode')
        help.append('" q/<Esc> : quit')
        help.append('" <F5> : refresh the cache')
        help.append('" <F1> : toggle this help')
        help.append('" ---------------------------------------------------------')
        return help

    def _afterEnter(self):
        super(GtagsExplManager, self)._afterEnter()
        id = int(lfEval('''matchadd('Lf_hl_tagFile', '^.\{-}\t\zs.\{-}\ze\t')'''))
        self._match_ids.append(id)
        id = int(lfEval('''matchadd('Lf_hl_tagType', ';"\t\zs[cdefFgmpstuv]\ze\(\t\|$\)')'''))
        self._match_ids.append(id)
        keyword = ["namespace", "class", "enum", "file", "function", "kind", "struct", "union"]
        for i in keyword:
            id = int(lfEval('''matchadd('Lf_hl_tagKeyword', '\(;"\t.\{-}\)\@<=%s:')''' % i))
            self._match_ids.append(id)

    def _beforeExit(self):
        super(GtagsExplManager, self)._beforeExit()
        for i in self._match_ids:
            lfCmd("silent! call matchdelete(%d)" % i)
        self._match_ids = []


#*****************************************************
# gtagsExplManager is a singleton
#*****************************************************
gtagsExplManager = GtagsExplManager()

__all__ = ['gtagsExplManager']

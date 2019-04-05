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
        self.gtags_cmd = None
        self._project_root = ""
        self._evalVimVar()

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
                print(e)

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

    def _root_dbpath(self, filename):
        """
        return the (root, dbpath,  whether gtags exists)
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
            db_folder = re.sub(r'[\\/]', '%', root.replace(':\\', '%', 1))
        else:
            db_folder = root.replace('/', '%')

        dbpath = os.path.join(self._db_location, db_folder)
        return (root, dbpath, os.path.exists(os.path.join(dbpath, "GTAGS")))

    def updateGtags(self, filename, single_update, auto):
        self._task_queue.put(partial(self._update, lfDecode(filename), single_update, auto))

    def _update(self, filename, single_update, auto):
        if filename == "":
            return

        if self._gtagsconf == '' and os.name == 'nt':
            self._gtagsconf = os.path.normpath(os.path.join(self._which("gtags.exe"), "..", "share", "gtags", "gtags.conf"))

        root, dbpath, exists = self._root_dbpath(filename)
        if single_update:
            if exists:
                cmd = 'cd "{}" && gtags {} --gtagslabel {} --single-update "{}" "{}"'.format(root,
                        "--gtagsconf " + self._gtagsconf if self._gtagsconf else "",
                        self._gtagslabel, filename, dbpath)
                subprocess.Popen(cmd, shell=True)
        elif not auto:
            self._executeCmd(root, dbpath)
        elif self._isVersionControl(filename):
            if not exists:
                self._executeCmd(root, dbpath)

    def _which(self, executable):
        for p in os.environ["PATH"].split(";"):
            if os.path.exists(os.path.join(p, executable)):
                return p

        return ""

    def _evalVimVar(self):
        """
        vim variables can not be accessed from a python thread,
        so we should evaluate the value in advance.
        """
        self._gtagsconf = lfEval("get(g:, 'Lf_Gtagsconf', '')")
        self._gtagslabel = lfEval("get(g:, 'Lf_Gtaglable', 'native-pygments')")

        if lfEval("get(g:, 'Lf_GtagsfilesFromFileExpl', 1)") == '0':
            self._Lf_GtagsfilesFromFileExpl = False
            self._Lf_GtagsfilesCmd = lfEval("g:Lf_GtagsfilesCmd")
            return
        else:
            self._Lf_GtagsfilesFromFileExpl = True

        if lfEval("exists('g:Lf_ExternalCommand')") == '1':
            self._Lf_ExternalCommand = lfEval("g:Lf_ExternalCommand") % dir.join('""')
            return

        self._Lf_ExternalCommand = None
        self._Lf_UseVersionControlTool = lfEval("g:Lf_UseVersionControlTool") == '1'
        self._Lf_WildIgnore = lfEval("g:Lf_WildIgnore")
        self._Lf_RecurseSubmodules = lfEval("get(g:, 'Lf_RecurseSubmodules', 0)") == '1'
        if lfEval("exists('g:Lf_DefaultExternalTool')") == '1':
            self._default_tool = {"rg": 0, "pt": 0, "ag": 0, "find": 0}
            tool = lfEval("g:Lf_DefaultExternalTool")
            if tool and lfEval("executable('%s')" % tool) == '0':
                raise Exception("executable '%s' can not be found!" % tool)
            self._default_tool[tool] = 1
        else:
            self._default_tool = {"rg": 1, "pt": 1, "ag": 1, "find": 1}
        self._is_rg_executable = lfEval("executable('rg')") == '1'
        self._Lf_ShowHidden = lfEval("g:Lf_ShowHidden") != '0'
        self._Lf_FollowLinks = lfEval("g:Lf_FollowLinks") == '1'
        self._is_pt_executable = lfEval("executable('pt')") == '1'
        self._is_ag_executable = lfEval("executable('ag')") == '1'
        self._is_find_executable = lfEval("executable('find')") == '1'

    def _exists(self, path, dir):
        """
        return True if `dir` exists in `path` or its ancestor path,
        otherwise return False
        """
        if os.name == 'nt':
            # e.g. C:\\
            root = os.path.splitdrive(os.path.abspath(path))[0] + os.sep
        else:
            root = '/'

        while os.path.abspath(path) != root:
            cur_dir = os.path.join(path, dir)
            if os.path.exists(cur_dir) and os.path.isdir(cur_dir):
                return True
            path = os.path.join(path, "..")

        cur_dir = os.path.join(path, dir)
        if os.path.exists(cur_dir) and os.path.isdir(cur_dir):
            return True

        return False

    def _buildCmd(self, dir, **kwargs):
        """
        this function comes from FileExplorer
        """
        if self._Lf_ExternalCommand:
            return self._Lf_ExternalCommand

        if self._Lf_UseVersionControlTool:
            if self._exists(dir, ".git"):
                wildignore = self._Lf_WildIgnore
                if ".git" in wildignore["dir"]:
                    wildignore["dir"].remove(".git")
                if ".git" in wildignore["file"]:
                    wildignore["file"].remove(".git")
                ignore = ""
                for i in wildignore["dir"]:
                    ignore += ' -x "%s"' % i
                for i in wildignore["file"]:
                    ignore += ' -x "%s"' % i

                if "--no-ignore" in kwargs.get("arguments", {}):
                    no_ignore = ""
                else:
                    no_ignore = "--exclude-standard"

                if self._Lf_RecurseSubmodules:
                    recurse_submodules = "--recurse-submodules"
                else:
                    recurse_submodules = ""

                cmd = 'git ls-files %s "%s" && git ls-files --others %s %s "%s"' % (recurse_submodules, dir, no_ignore, ignore, dir)
                return cmd
            elif self._exists(dir, ".hg"):
                wildignore = self._Lf_WildIgnore
                if ".hg" in wildignore["dir"]:
                    wildignore["dir"].remove(".hg")
                if ".hg" in wildignore["file"]:
                    wildignore["file"].remove(".hg")
                ignore = ""
                for i in wildignore["dir"]:
                    ignore += ' -X "%s"' % self._expandGlob("dir", i)
                for i in wildignore["file"]:
                    ignore += ' -X "%s"' % self._expandGlob("file", i)

                cmd = 'hg files %s "%s"' % (ignore, dir)
                return cmd

        default_tool = self._default_tool

        if default_tool["rg"] and self._is_rg_executable:
            wildignore = self._Lf_WildIgnore
            if os.name == 'nt': # https://github.com/BurntSushi/ripgrep/issues/500
                color = ""
                ignore = ""
                for i in wildignore["dir"]:
                    if self._Lf_ShowHidden or not i.startswith('.'): # rg does not show hidden files by default
                        ignore += ' -g "!%s"' % i
                for i in wildignore["file"]:
                    if self._Lf_ShowHidden or not i.startswith('.'):
                        ignore += ' -g "!%s"' % i
            else:
                color = "--color never"
                ignore = ""
                for i in wildignore["dir"]:
                    if self._Lf_ShowHidden or not i.startswith('.'):
                        ignore += " -g '!%s'" % i
                for i in wildignore["file"]:
                    if self._Lf_ShowHidden or not i.startswith('.'):
                        ignore += " -g '!%s'" % i

            if self._Lf_FollowLinks:
                followlinks = "-L"
            else:
                followlinks = ""

            if self._Lf_ShowHidden:
                show_hidden = "--hidden"
            else:
                show_hidden = ""

            if "--no-ignore" in kwargs.get("arguments", {}):
                no_ignore = "--no-ignore"
            else:
                no_ignore = ""

            if dir == '.':
                cur_dir = ''
            else:
                cur_dir = '"%s"' % dir

            cmd = 'rg --no-messages --files %s %s %s %s %s %s' % (color, ignore, followlinks, show_hidden, no_ignore, cur_dir)
        elif default_tool["pt"] and self._is_pt_executable and os.name != 'nt': # there is bug on Windows
            wildignore = self._Lf_WildIgnore
            ignore = ""
            for i in wildignore["dir"]:
                if self._Lf_ShowHidden or not i.startswith('.'): # pt does not show hidden files by default
                    ignore += " --ignore=%s" % i
            for i in wildignore["file"]:
                if self._Lf_ShowHidden or not i.startswith('.'):
                    ignore += " --ignore=%s" % i

            if self._Lf_FollowLinks:
                followlinks = "-f"
            else:
                followlinks = ""

            if self._Lf_ShowHidden:
                show_hidden = "--hidden"
            else:
                show_hidden = ""

            if "--no-ignore" in kwargs.get("arguments", {}):
                no_ignore = "-U"
            else:
                no_ignore = ""

            cmd = 'pt --nocolor %s %s %s %s -g="" "%s"' % (ignore, followlinks, show_hidden, no_ignore, dir)
        elif default_tool["ag"] and self._is_ag_executable and os.name != 'nt': # https://github.com/vim/vim/issues/3236
            wildignore = self._Lf_WildIgnore
            ignore = ""
            for i in wildignore["dir"]:
                if self._Lf_ShowHidden or not i.startswith('.'): # ag does not show hidden files by default
                    ignore += ' --ignore "%s"' % i
            for i in wildignore["file"]:
                if self._Lf_ShowHidden or not i.startswith('.'):
                    ignore += ' --ignore "%s"' % i

            if self._Lf_FollowLinks:
                followlinks = "-f"
            else:
                followlinks = ""

            if self._Lf_ShowHidden:
                show_hidden = "--hidden"
            else:
                show_hidden = ""

            if "--no-ignore" in kwargs.get("arguments", {}):
                no_ignore = "-U"
            else:
                no_ignore = ""

            cmd = 'ag --nocolor --silent %s %s %s %s -g "" "%s"' % (ignore, followlinks, show_hidden, no_ignore, dir)
        elif default_tool["find"] and self._is_find_executable and os.name != 'nt':
            wildignore = self._Lf_WildIgnore
            ignore_dir = ""
            for d in wildignore["dir"]:
                ignore_dir += '-type d -name "%s" -prune -o ' % d

            ignore_file = ""
            for f in wildignore["file"]:
                    ignore_file += '-type f -name "%s" -o ' % f

            if self._Lf_FollowLinks:
                followlinks = "-L"
            else:
                followlinks = ""

            if os.name == 'nt':
                redir_err = ""
            else:
                redir_err = " 2>/dev/null"

            if self._Lf_ShowHidden:
                show_hidden = ""
            else:
                show_hidden = '-name ".*" -prune -o'

            cmd = 'find %s "%s" -name "." -o %s %s %s -type f -print %s %s' % (followlinks,
                                                                               dir,
                                                                               ignore_dir,
                                                                               ignore_file,
                                                                               show_hidden,
                                                                               redir_err)
        else:
            cmd = None

        return cmd

    def _file_list_cmd(self, root):
        if self._Lf_GtagsfilesFromFileExpl:
            cmd = self._buildCmd(root)
        else:
            if os.path.exists(os.path.join(root, ".git")) and os.path.isdir(os.path.join(root, ".git")):
                cmd = self._Lf_GtagsfilesCmd[".git"]
            elif os.path.exists(os.path.join(root, ".hg")) and os.path.isdir(os.path.join(root, ".hg")):
                cmd = self._Lf_GtagsfilesCmd[".hg"]
            else:
                cmd = self._Lf_GtagsfilesCmd["default"]

        return cmd

    def _executeCmd(self, root, dbpath):
        if not os.path.exists(dbpath):
            os.makedirs(dbpath)
        cmd = self._file_list_cmd(root)
        if cmd:
            cmd = 'cd "{}" && {} | gtags {} --gtagslabel {} -f- "{}"'.format(root, cmd,
                        "--gtagsconf " + self._gtagsconf if self._gtagsconf else "",
                        self._gtagslabel, dbpath)
        else:
            cmd = 'cd "{}" && gtags {} --gtagslabel {} "{}"'.format(root,
                        "--gtagsconf " + self._gtagsconf if self._gtagsconf else "",
                        self._gtagslabel, dbpath)
        self.gtags_cmd = cmd
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

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
        self._executor = []
        self._pattern_regex = ""
        if os.name == 'nt':
            self._cd_option = '/d '
        else:
            self._cd_option = ''
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
        if "--recall" in kwargs.get("arguments", {}):
            return []

        if vim.current.buffer.name:
            filename = vim.current.buffer.name
        else:
            filename = os.path.join(os.getcwd(), 'no_name')

        if "--update" in kwargs.get("arguments", {}):
            if "--accept-dotfiles" in kwargs.get("arguments", {}):
                self._accept_dotfiles = "--accept-dotfiles "
            if "--skip-unreadable" in kwargs.get("arguments", {}):
                self._skip_unreadable = "--skip-unreadable "
            if "--skip-symlink" in kwargs.get("arguments", {}):
                self._skip_symlink = "--skip-symlink "
            self.updateGtags(filename, single_update=False, auto=False)
            return

        if "-d" in kwargs.get("arguments", {}):
            pattern = kwargs.get("arguments", {})["-d"][0]
            pattern_option = "-d -e %s " % pattern
        elif "-r" in kwargs.get("arguments", {}):
            pattern = kwargs.get("arguments", {})["-r"][0]
            pattern_option = "-r -e %s " % pattern
        elif "-s" in kwargs.get("arguments", {}):
            pattern = kwargs.get("arguments", {})["-s"][0]
            pattern_option = "-s -e %s " % pattern
        elif "-g" in kwargs.get("arguments", {}):
            pattern = kwargs.get("arguments", {})["-g"][0]
            pattern_option = "-g -e %s " % pattern
        else:
            pass

        if "--gtagsconf" in kwargs.get("arguments", {}):
            self._gtagsconf = kwargs.get("arguments", {})["--gtagsconf"][0]
        if "--gtagslabel" in kwargs.get("arguments", {}):
            self._gtagslabel = kwargs.get("arguments", {})["--gtagslabel"][0]

        if self._gtagsconf == '' and os.name == 'nt':
            self._gtagsconf = os.path.normpath(os.path.join(self._which("gtags.exe"), "..", "share", "gtags", "gtags.conf"))

        if "--literal" in kwargs.get("arguments", {}):
            literal = "--literal "
        else:
            literal = ""

        if "-i" in kwargs.get("arguments", {}):
            ignorecase = "-i "
        else:
            ignorecase = ""

        if "--append" not in kwargs.get("arguments", {}):
            self._pattern_regex = ""

        if ignorecase:
            case_pattern = r'\c'
        else:
            case_pattern = r'\C'

        # if len(pattern) > 1 and (pattern[0] == pattern[-1] == '"' or pattern[0] == pattern[-1] == "'"):
        #     p = pattern[1:-1]

        # if literal:
        #     if len(pattern) > 1 and pattern[0] == pattern[-1] == '"':
        #         p = re.sub(r'\\(?!")', r'\\\\', p)
        #     else:
        #         p = p.replace('\\', r'\\')

        #     self._pattern_regex = r'\V' + case_pattern + p
        # else:
        #     if word_or_line == '-w ':
        #         p = '<' + p + '>'
        #     self._pattern_regex = self.translateRegex(case_pattern + p, is_perl)

        # if pattern == '':
        #     pattern = '"" '

        root, dbpath, exists = self._root_dbpath(filename)

        env = os.environ
        env["GTAGSROOT"] = root
        env["GTAGSDBPATH"] = dbpath

        cmd = 'global {}--gtagslabel={} {} {}{}--color=never --result=ctags-mod'.format(
                    '--gtagsconf "%s" ' % self._gtagsconf if self._gtagsconf else "",
                    self._gtagslabel, pattern_option, literal, ignorecase)

        executor = AsyncExecutor()
        self._executor.append(executor)
        lfCmd("let g:Lf_Debug_GtagsCmd = '%s'" % escQuote(cmd))
        content = executor.execute(cmd, env=env)
        return content

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
                cmd = 'cd {}"{}" && gtags {}{}{}{}--gtagslabel {} --single-update "{}" "{}"'.format(self._cd_option, root,
                            self._accept_dotfiles, self._skip_unreadable, self._skip_symlink,
                            '--gtagsconf "%s" ' % self._gtagsconf if self._gtagsconf else "",
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
        self._accept_dotfiles =  "--accept-dotfiles " if lfEval("get(g:, 'Lf_GtagsAcceptDotfiles', '0')") == '1' else ""
        self._skip_unreadable =  "--skip-unreadable " if lfEval("get(g:, 'Lf_GtagsSkipUnreadable', '0')") == '1' else ""
        self._skip_symlink =  "--skip-symlink " if lfEval("get(g:, 'Lf_GtagsSkipSymlink', '0')") == '1' else ""
        self._gtagsconf = lfEval("get(g:, 'Lf_Gtagsconf', '')")
        self._gtagslabel = lfEval("get(g:, 'Lf_Gtagslable', 'default')")

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
        # do not use external command if the encoding of `dir` is not ascii
        if not isAscii(dir):
            return None

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
            if os.name == 'nt':
                cmd = 'cd {}"{}" && ( {} ) | gtags {}{}{}{}--gtagslabel {} -f- "{}"'.format(self._cd_option, root, cmd,
                            self._accept_dotfiles, self._skip_unreadable, self._skip_symlink,
                            '--gtagsconf "%s" ' % self._gtagsconf if self._gtagsconf else "",
                            self._gtagslabel, dbpath)
            else:
                cmd = 'cd {}"{}" && {{ {}; }} | gtags {}{}{}{}--gtagslabel {} -f- "{}"'.format(self._cd_option, root, cmd,
                            self._accept_dotfiles, self._skip_unreadable, self._skip_symlink,
                            '--gtagsconf "%s" ' % self._gtagsconf if self._gtagsconf else "",
                            self._gtagslabel, dbpath)
        else:
            cmd = 'cd {}"{}" && gtags {}{}{}{}--gtagslabel {} "{}"'.format(self._cd_option, root,
                        self._accept_dotfiles, self._skip_unreadable, self._skip_symlink,
                        '--gtagsconf "%s" ' % self._gtagsconf if self._gtagsconf else "",
                        self._gtagslabel, dbpath)
        self.gtags_cmd = cmd

        proc = subprocess.Popen(cmd, shell=True)
        proc.communicate()

    def getStlCategory(self):
        return 'Gtags'

    def getStlCurDir(self):
        return escQuote(lfEncode(os.getcwd()))

    def cleanup(self):
        for exe in self._executor:
            exe.killProcess()
        self._executor = []

    def getPatternRegex(self):
        return self._pattern_regex


#*****************************************************
# GtagsExplManager
#*****************************************************
class GtagsExplManager(Manager):
    def __init__(self):
        super(GtagsExplManager, self).__init__()
        self._match_ids = []
        self._match_path = False

    def _getExplClass(self):
        return GtagsExplorer

    def _defineMaps(self):
        lfCmd("call leaderf#Gtags#Maps()")

    def _acceptSelection(self, *args, **kwargs):
        if len(args) == 0:
            return

        line = args[0]
        file, line_num = line.split('\t', 2)[:2]
        if not os.path.isabs(file):
            if file.startswith(".\\") or file.startswith("./"):
                file = file[2:]
            file = os.path.join(self._getInstance().getCwd(), lfDecode(file))
            file = lfEncode(file)

        try:
            if kwargs.get("mode", '') == 't':
                lfCmd("tab drop %s | %s" % (escSpecial(file), line_num))
            else:
                lfCmd("hide edit +%s %s" % (line_num, escSpecial(file)))
            lfCmd("norm! zz")
            lfCmd("setlocal cursorline! | redraw | sleep 20m | setlocal cursorline!")
        except vim.error as e:
            lfPrintError(e)

    def updateGtags(self, filename, single_update, auto=True):
        self._getExplorer().updateGtags(filename, single_update, auto)

    def setArguments(self, arguments):
        self._arguments = arguments
        self._match_path = "--match-path" in arguments

    def _getDigest(self, line, mode):
        """
        specify what part in the line to be processed and highlighted
        Args:
            mode: 0, return the full path
                  1, return the name only
                  2, return the directory name
        """
        if self._match_path:
            return line

        return line[line.find('\t', line.find('\t')) + 1:]

    def _getDigestStartPos(self, line, mode):
        """
        return the start position of the digest returned by _getDigest()
        Args:
            mode: 0, return the start postion of full path
                  1, return the start postion of name only
                  2, return the start postion of directory name
        """
        if self._match_path:
            return 0

        return lfBytesLen(line[:line.find('\t', line.find('\t'))]) + 1

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
        id = int(lfEval('''matchadd('Lf_hl_gtagsFileName', '^.\{-}\ze\t')'''))
        self._match_ids.append(id)
        id = int(lfEval('''matchadd('Lf_hl_gtagsLineNumber', '\t\zs\d\+\ze\t')'''))
        self._match_ids.append(id)

    def _beforeExit(self):
        super(GtagsExplManager, self)._beforeExit()
        for i in self._match_ids:
            lfCmd("silent! call matchdelete(%d)" % i)
        self._match_ids = []
        if self._timer_id is not None:
            lfCmd("call timer_stop(%s)" % self._timer_id)
            self._timer_id = None

    def _bangEnter(self):
        super(GtagsExplManager, self)._bangEnter()
        if lfEval("exists('*timer_start')") == '0':
            lfCmd("echohl Error | redraw | echo ' E117: Unknown function: timer_start' | echohl NONE")
            return
        if "--recall" not in self._arguments:
            self._workInIdle(bang=True)
            if self._read_finished < 2:
                self._timer_id = lfEval("timer_start(1, 'leaderf#Gtags#TimerCallback', {'repeat': -1})")


#*****************************************************
# gtagsExplManager is a singleton
#*****************************************************
gtagsExplManager = GtagsExplManager()

__all__ = ['gtagsExplManager']

#!/usr/bin/env python

import os
import subprocess
import yaml
import datetime
import time
import logging
import sys
import shutil
import tempfile
import time
import fcntl
import hashlib
import re

work_dir = "/data/work"
zpaq_key = os.getenv("encryption_key", "")
use_ip_in_path = os.getenv("backup_use_ip_in_path", "true") == "true"
log_file_name = "/data/logs/backuper.log"
backup_config_dir = "/data/conf"
backup_tasks_dir = "/data/tasks"
backup_name_unique_counter = 0

backup_config = {
    "local": {
        "exclude": ["*.tmp", "*.jar"],
        "include_only": []
    },
    "keep_incremental_backup_count": 10,
    "keep_full_backup_count": 3,
}

logger = None

# backup config yaml format:
#
# local.exclude[]                array of exclusions
# local.include_only[]           array of include only
# keep_incremental_backup_count  how many incremental backups to keep
# keep_full_backup_count         how many full backups to keep


# abstraction over *nix process, supporting piping and parallel execution
class Proc:

    # cmd: [] list for Popen
    # error: error string to include to exception if command fails
    # stdin: if set, write this string to stdin of created process
    def __init__(self, cmd, error="", stdin=None):
        self.cmd = cmd
        self.error = error
        self.pipes = [[self]]
        self.stdin = stdin

    # pipe this proc to argument proc
    def pipe(self, proc):
        p = Proc(None, None)
        p.pipes = [[self, proc]]
        return p

    # run this proc in parallel with argument proc
    def par(self, proc):
        p = Proc(None, None)
        p.pipes = self.pipes + proc.pipes
        return p

    # run this proc, awaiting for result synchronously
    # stderr and stdout (where appropriate) goes to out
    def run(self, out):
        pars = self._run(None, out)

        while True:
            has_running = False
            error_msg = None
            for par in pars:
                code = par[0].poll()
                if code is None:
                    has_running = True
                elif code != 0 and error_msg is None:
                    error_msg = par[1]

            if error_msg is not None:
                for par in pars:
                    try:
                        par[0].kill()
                    except OSError:
                        pass
                raise IOError(error_msg)

            if not has_running:
                return
            time.sleep(0.05)

    def _run(self, in_, out):
        if self.cmd is not None:
            if self.stdin is not None:
                p = subprocess.Popen(self.cmd, stdout=out, stdin=subprocess.PIPE) # stderr=subprocess.STDOUT,
                p.stdin.write(self.stdin)
                p.stdin.close()
                return [[p, self.error]]
            else:
                return [[subprocess.Popen(self.cmd, stdout=out, stdin=in_), self.error]]

        result = []
        for p in self.pipes:
            if len(p) == 1:
                rr = p[0]._run(in_, out)
                result = result + rr
            else:
                rr1 = p[0]._run(in_, subprocess.PIPE)
                src = rr1[-1]

                rr2 = p[1]._run(src[0].stdout, out)

                result = result + rr1 + rr2

        return result

    @staticmethod
    def string_source(s):
        return Proc(["cat"], "", s)

    @staticmethod
    def source(fname):
        return Proc(["bash", "-c", "cat " + fname], "failed to open file" + fname)

    @staticmethod
    def sink(fname):
        return Proc(["bash", "-c", "cat >" + fname], "failed to write to file" + fname)


def unset_if_empty(envname):
    if envname in os.environ and os.environ[envname] == "":
        os.unsetenv(envname)


def init_logging():
    global logger

    if logger is None:
        logger = logging.getLogger("backuper")  # log_namespace can be replaced with your namespace
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            file_name = log_file_name
            try:
                handler = logging.FileHandler(file_name)
            except IOError as e:
                print("Unable to use log file " + file_name + ": " + str(e))
                print("Switching to stdout")
                handler = logging.StreamHandler(sys.stdout)
            # [2016-12-16T18:43:41.191Z] [sgs] [INFO]
            formatter = logging.Formatter('[%(asctime)s] [backuper] [%(name)s] [%(levelname)s]: %(message)s',
                                          '%Y-%m-%dT%H:%M:%SZ')
            logging.Formatter.converter = time.gmtime
            handler.setFormatter(formatter)
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)


def log_info(s):
    init_logging()
    logger.info(s.replace("\n", "\n  "))


def log_warn(s):
    init_logging()
    logger.warning(s.replace("\n", "\n  "))


def log_error(s):
    init_logging()
    logger.error(s.replace("\n", "\n  "))


def get_script_dir():
    import inspect
    if getattr(sys, 'frozen', False):  # py2exe, PyInstaller, cx_Freeze
        path = os.path.abspath(sys.executable)
    else:
        path = inspect.getabsfile(get_script_dir)
    return os.path.dirname(path)


def get_ip_address():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]


def parse_url(url):
    i = url.find(":")
    if i < 0:
        raise Exception("illegal url: " + url)
    class Url:
        def __init__(self):
            self.protocol = url[0:i]
            self.path = url[i+1:]
    return Url()


# upload single file
def upload(src, dst):
    u = parse_url(dst)
    return Proc([get_script_dir() + "/" + u.protocol + "/upload", src, u.path], "Upload " + src + " to " + dst + " failed")


# download single file
def download(src, dst):
    u = parse_url(src)
    return Proc([get_script_dir() + "/" + u.protocol + "/download", u.path, dst], "Download " + src + " to " + dst + " failed")


def delete(src):
    u = parse_url(src)
    return Proc([get_script_dir() + "/" + u.protocol + "/delete", u.path], "Delete " + src + " failed")


def full_local_dir(url):
    return work_dir + "/" + re.sub(r'\W', ".", url)


def full_remote_dir(url, full_backup_name):
    return almost_full_remote_dir(url) + "/" + full_backup_name


def almost_full_remote_dir(url):
    d = url

    if use_ip_in_path:
        d = d + "/" + get_ip_address()

    return d


def compress(url, tmp_dir, options):
    index_file = "a00000.zpaq"
    full_local = full_local_dir(url)

    if os.path.isfile(full_local + "/" + index_file):
        log_info("Starting INCREMENTAL backup of " + url)
    else:
        log_info("Starting FULL backup of " + url)

    zpaq_command = [get_script_dir() + "/zpaq",
                    "add",
                    tmp_dir + "/a?????"] + options + ["-index", tmp_dir + "/" + index_file]
    p = subprocess.Popen(zpaq_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    p.poll()

    if p.returncode != 0:
        log_error(out)
        log_error("zpaq invocation failed")
        raise IOError("zpaq invocation failed")
    else:
        log_info(out)


# local.exclude[]                array of exclusions
# local.include_only[]           array of include only
# keep_incremental_backup_count  how many incremental backups to keep
# keep_full_backup_count         how many full backups to keep
#
#  last_backup_timestamp: long
#  full_backups[].name
#  full_backups[].incremental_backups[]
#  upload.files_uploaded[]
#  upload.files_left[]
#  index_version: string
def load_state(url, password):
    with pipe() as p:
        with tempfile.NamedTemporaryFile(prefix="backuper-c-") as f:
            download(url + "/index.yaml", p) \
                .par(Proc.source(p)
                     .pipe(Proc(["openssl", "aes-256-cbc", "-a", "-d", "-md", "sha256", "-pbkdf2", "-k", password],
                                "state decryption failed, invalid password?"))
                     ).run(f)
            f.seek(0)
            return yaml.load(f.read())


def save_state(url, state, password):
    cfg = yaml.dump(state)

    with pipe() as p:
        Proc.string_source(cfg) \
            .pipe(Proc(["openssl", "aes-256-cbc", "-a", "-md", "sha256", "-pbkdf2", "-k", password])) \
            .pipe(Proc.sink(p)) \
            .par(upload(p, url + "/index.yaml")).run(sys.stdout)


def collect_options(local, password):
    s = []
    if local["exclude"] is not None:
        for e in local["exclude"]:
            s += ["-not", e]
    if local["include_only"] is not None:
        for i in local["include_only"]:
            s += ["-only", i]
    if password != "":
        s += ["-key", password]
    return s


def delete_full_backup(url, full_backup_name):
    rp = full_remote_dir(url, full_backup_name)
    try:
        delete(rp).run(sys.stdout)
    except IOError as e:
        log_warn(e.message)


def new_full_backup_name():
    global backup_name_unique_counter
    n = datetime.datetime.now().strftime('%Y-%m-%d__%H_%M_%S') + "_" + str(backup_name_unique_counter)
    backup_name_unique_counter += 1

    return n


def roll_full_backup(url, state, password):

    def start_new_full_backup():
        nm = new_full_backup_name()
        state["full_backups"].append({
            "name": nm,
            "incremental_backups": []
        })
        state["index_version"] = ""

    if len(state["full_backups"]) == 0:  # no backups at all? start new one!
        start_new_full_backup()

    current_full_backup = state["full_backups"][-1]

    if len(current_full_backup["incremental_backups"]) > state["keep_incremental_backup_count"]:
        # need to do full backup
        start_new_full_backup()

    backups_to_delete = []
    while len(state["full_backups"]) > state["keep_full_backup_count"]:
        backups_to_delete.append(state["full_backups"][0]["name"])
        del state["full_backups"][0]
    save_state(url, state, password)

    for name in backups_to_delete:
        delete_full_backup(url, name)


def perform_backup(url, dirs, password):
    state = load_state(url, password)
    roll_full_backup(url, state, password)

    current_full_backup = state["full_backups"][-1]

    full_remote = full_remote_dir(url, current_full_backup["name"])
    local_dir = full_local_dir(url)
    index_file = "a00000.zpaq"

    def remote_index(version):
        return full_remote + "/" + index_file + "." + version

    def clean_local_dir():
        shutil.rmtree(local_dir, True)
        os.makedirs(local_dir)

    def forall(l, iterable):
        for e in iterable:
            if not l(e):
                return False
        return True

    # we have pending upload if:
    # - uploaded and pending files are still there
    # - index file is still there
    # - at least one file is left
    is_upload_in_progress = "upload" in state \
        and "files_uploaded" in state["upload"] \
        and "files_left" in state["upload"] \
        and len(state["upload"]["files_left"]) > 0 \
        and os.path.isdir(local_dir) \
        and len(state["upload"]["files_left"]) \
        and os.path.isfile(local_dir + "/" + index_file) \
        and forall(lambda ff: os.path.isfile(local_dir + "/" + ff), state["upload"]["files_left"]) \
        and forall(lambda ff: os.path.isfile(local_dir + "/" + ff), state["upload"]["files_uploaded"])

    if not is_upload_in_progress:
        clean_local_dir()
        if state["index_version"] != "":
            download(remote_index(state["index_version"]), local_dir + "/" + index_file).run(sys.stdout)
        compress(url, local_dir, dirs + collect_options(state["local"], password))
        files = filter(lambda f: os.path.isfile(local_dir + "/" + f) and f != index_file, os.listdir(local_dir))
        state["upload"] = {"files_uploaded": [], "files_left": files}
    else:
        files = state["upload"]["files_left"]
        log_info("Resuming upload, files left are: " + str(state["upload"]["files_left"]))

    save_state(url, state, password)
    for f in files:
        upload(local_dir + "/" + f, full_remote + "/" + f).run(sys.stdout)
        state["upload"]["files_left"].remove(f)
        state["upload"]["files_uploaded"].append(f)
        save_state(url, state, password)

    index_version_old = state["index_version"]
    index_version_new = str(time.time())

    upload(local_dir + "/" + index_file, remote_index(index_version_new)).run(sys.stdout)

    state["index_version"] = index_version_new

    # totally commit
    state["last_backup_timestamp"] = int(time.time())
    current_full_backup["incremental_backups"].append(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    save_state(url, state, password)

    delete(remote_index(index_version_old)).run(sys.stdout)

    clean_local_dir()
    log_info("Backup " + url + " complete")


#
# []config
# []config.name
#  ....
# []state
# []state.last_backup_timestamp .....
def load_backup_configs():
    conf_files = []
    if not os.path.exists(backup_config_dir):
        os.makedirs(backup_config_dir)
    try:
        for f in os.listdir(backup_config_dir):
            ff = os.path.join(backup_config_dir, f)
            if os.path.isfile(ff) and f.endswith(".yml"):
                conf_files.append(ff)
    except OSError as e:
        log_warn("Unable to load backup configuration: " + str(e))
        return []

    result = []

    for f in conf_files:
        try:
            with open(f, "r") as ff:
                config = yaml.load(ff.read())
            state = load_state(config["name"])
            result.append({
                "config": config,
                "state": state
            })
        except Exception as e:
            log_warn("Failed to load config file " + f + ": " + str(e))

    return result


# [].version
# [].date
def restore_urls(state):
    r = []
    for fb in state["full_backups"]:
        i = 1
        for ib in fb["incremental_backups"]:
            r.append({
                "version": fb["name"] + ":" + str(i),
                "date": ib
            })
            i += 1
    return r


# restore backup by backup URL and version
# please note that archive keep absolute file names and extraction will work in the same way
# if you want to extract to somewhere else, use second parameter
def restore(url, version, password, to=""):
    parts = version.split(":")
    if len(parts) != 2:
        raise Exception("Incorrect version: " + version)
    name = parts[0]
    v = parts[1]
    base = full_remote_dir(url, name)
    work_dir = full_local_dir(url) + "/restore"

    state = load_state(url, password)
    download(base + "/a00000.zpaq." + state["index_version"], work_dir + "/a00000.zpaq").run(sys.stdout)

    # download archives
    for i in range(1, int(v) + 1):
        fname = "a" + str(i).zfill(5) + ".zpaq"
        download(base + "/" + fname, work_dir + "/" + fname).run(sys.stdout)

    # invoke zpaq
    args = [get_script_dir() + "/zpaq", "extract", work_dir + "/a?????.zpaq", "-until", v,
            "-force"]

    if to != "":
        args += ["-to", to]

    if password != "":
        args += ["-key", password]
    subprocess.call(args)
    pass


def create_backup(url, password, config):
    pass


def pipe():
    class Pipe:
        def __enter__(self):
            f = tempfile.NamedTemporaryFile(prefix="backuper-p-")
            f.close()
            self.fname = f.name
            Proc(["mkfifo", self.fname]).run(sys.stdout)
            return self.fname

        def __exit__(self, exc_type, exc_val, exc_tb):
            os.remove(self.fname)

    return Pipe()


def main():
    save_state("local:.", {
        "local": {
            "exclude": ["*.tmp"],
            "include_only": [],
        },
        "keep_incremental_backup_count": 10,
        "keep_full_backup_count": 3,
        "last_backup_timestamp": 0,
        "full_backups": [],
        "index_version": ""
    }, "password")
    print(load_state("local:.", "password"))
    return

    p1 = Proc(["bash", "-c", "sleep 1; echo hello"], "p1 failed")
    p2 = Proc(["bash", "-c", "echo world"], "p2 failed")

    s0 = Proc(["cat", "/home/asm/replay_pid12823.log"], "s0 failed")
    s1 = Proc(["gzip"], "s1 failed")
    s2 = Proc(["gzip", "-d"], "s2 failed")

    s0.pipe(s1).pipe(s2).pipe(Proc.sink("1")).run(sys.stdout)

    Proc.string_source("hello, world!").pipe(Proc(["base64"])).run(sys.stdout)

    p1.par(p2).run(sys.stdout)

    return
    pr = subprocess.Popen(["bash", "-c", "echo hello | gzip"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    fd = pr.stdout.fileno()
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    hasData = True
    while pr.poll() is None or hasData:
        try:
            s = pr.stdout.read(50)
            if len(s) > 0:
                sys.stdout.write(s)
            if pr.poll() is not None and len(s) == 0:
                hasData = False
        except IOError:
            pass
        time.sleep(0.1)
    return

    with string_pipe("hello, world!") as p:
        print(execute(["cat", p]))

    return

    print(executes([["sleep", "1s"], ["sleep", "5s"]], sys.stdout))
    return


    # aws cli does not like empty access keys - so if they are missing, unset them!
    unset_if_empty("AWS_ACCESS_KEY_ID")
    unset_if_empty("AWS_SECRET_ACCESS_KEY")

    log_info("Starting Backuper")
    conf = load_backup_configs()
    if len(conf) == 0:
        log_warn("No configuration files loaded")

    tick = 0
    while True:
        process_backup_tasks()

        if tick % 60 == 0:
            process_scheduled_backups()

        time.sleep(1)
        tick += 1


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import os
import subprocess
import yaml
import datetime
import sys
import shutil
import tempfile
import time
import fcntl
import re

work_dir = "/tmp/river"
use_ip_in_path = os.getenv("backup_use_ip_in_path", "true") == "false"
backup_name_unique_counter = 0
stdout = open("/dev/null", "w")  # sys.stdout

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
    def __init__(self, cmd, error=None, stdin=None):
        self.cmd = cmd
        self.error = error
        self.pipes = [[self]]
        if isinstance(stdin, str):
            self.stdin = bytearray(stdin, 'utf-8')
        else:
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
    # stdout (where appropriate) goes to out, stderr goes to err
    def run(self, out=None, err=None):
        pars = self._run(None, out, err)

        while True:
            has_running = False
            error_msg = None
            for par in pars:
                code = par[0].poll()
                if code is None:
                    has_running = True
                else:
                    if par[0].stdout is not None:
                        par[0].stdout.close()
                    if code != 0 and error_msg is None:
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

    def _run(self, in_, out, err):
        if self.cmd is not None:
            if self.stdin is not None:
                p = subprocess.Popen(self.cmd, stdout=out, stdin=subprocess.PIPE, stderr=err) # stderr=subprocess.STDOUT,
                p.stdin.write(self.stdin)
                p.stdin.close()
                return [[p, self.error]]
            else:
                return [[subprocess.Popen(self.cmd, stdout=out, stdin=in_, stderr=err), self.error]]

        result = []
        for p in self.pipes:
            if len(p) == 1:
                rr = p[0]._run(in_, out, err)
                result = result + rr
            else:
                rr1 = p[0]._run(in_, subprocess.PIPE, err)
                src = rr1[-1]

                rr2 = p[1]._run(src[0].stdout, out, err)

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
    addr = s.getsockname()[0]
    s.close()
    return addr


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
    d = url

    if use_ip_in_path:
        d = d + "/" + get_ip_address()

    return d + "/" + full_backup_name


def compress(tmp_dir, options):
    index_file = "a00000.zpaq"
    zpaq_command = [get_script_dir() + "/zpaq",
                    "add",
                    tmp_dir + "/a?????"] + options + ["-index", tmp_dir + "/" + index_file]

    with tempfile.NamedTemporaryFile(prefix="river-c-") as f:
        try:
            Proc(zpaq_command, "zpaq invocation failed").run(stdout, f)
        except Exception as e:
            f.seek(0)
            sys.stderr.write(f.read().decode('utf-8'))


# local.exclude[]                array of exclusions
# local.include_only[]           array of include only
# keep_incremental_backup_count  how many incremental backups to keep
# keep_full_backup_count         how many full backups to keep
#
#  last_backup_timestamp: long
#  full_backups[].name
#  full_backups[].index_version: string
#  full_backups[].incremental_backups[] # incremental backup timestamp
#  upload.files_uploaded[]
#  upload.files_left[]

def load_state(url, password):
    with pipe() as p:
        with tempfile.NamedTemporaryFile(prefix="river-c-") as f:
            if password != "":
                download(url + "/index.yaml", p).pipe(Proc.sink("/dev/null")) \
                    .par(Proc.source(p)
                         .pipe(Proc(["openssl", "aes-256-cbc", "-a", "-d", "-md", "sha256", "-pbkdf2", "-k", password],
                                    "state decryption failed, invalid password?"))
                         ).run(f)
            else:
                download(url + "/index.yaml", p).pipe(Proc.sink("/dev/null")) \
                    .par(Proc.source(p)).run(f)
            f.seek(0)
            result = yaml.safe_load(f.read())
            if "full_backups" not in result:
                raise Exception("State is encrypted, password required")
            return result


def save_state(url, state, password):
    cfg = yaml.dump(state)

    with pipe() as p:
        if password != "":
            Proc.string_source(cfg) \
                .pipe(Proc(["openssl", "aes-256-cbc", "-a", "-md", "sha256", "-pbkdf2", "-k", password])) \
                .pipe(Proc.sink(p)) \
                .par(upload(p, url + "/index.yaml")).run(stdout)
        else:
            Proc.string_source(cfg) \
                .pipe(Proc.sink(p)) \
                .par(upload(p, url + "/index.yaml")).run(stdout)


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
        delete(rp).run(stdout)
    except IOError as e:
        pass


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
            "index_version": "",
            "incremental_backups": []
        })

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
        if current_full_backup["index_version"] != "":
            download(remote_index(current_full_backup["index_version"]), local_dir + "/" + index_file).run(stdout)
        compress(local_dir, dirs + collect_options(state["local"], password))
        files = list(filter(lambda f: os.path.isfile(local_dir + "/" + f) and f != index_file, os.listdir(local_dir)))
        state["upload"] = {"files_uploaded": [], "files_left": list(files)}
    else:
        files = state["upload"]["files_left"]

    save_state(url, state, password)
    for f in files:
        upload(local_dir + "/" + f, full_remote + "/" + f).run(stdout)
        state["upload"]["files_left"].remove(f)
        state["upload"]["files_uploaded"].append(f)
        save_state(url, state, password)

    index_version_old = current_full_backup["index_version"]
    index_version_new = str(time.time())

    upload(local_dir + "/" + index_file, remote_index(index_version_new)).run(stdout)

    current_full_backup["index_version"] = index_version_new

    # totally commit
    state["last_backup_timestamp"] = int(time.time())
    current_full_backup["incremental_backups"].append(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    save_state(url, state, password)

    delete(remote_index(index_version_old)).pipe(Proc.sink("/dev/null")).run(stdout)

    clean_local_dir()


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
def restore(url, version, password, to="", verify=False):
    parts = version.split(":")
    if len(parts) != 2:
        raise Exception("Incorrect version: " + version)
    name = parts[0]
    v = parts[1]
    base = full_remote_dir(url, name)
    work_dir = full_local_dir(url) + "/restore"

    state = load_state(url, password)

    current_full_backup = None
    for bkp in state["full_backups"]:
        if bkp["name"] == name:
            current_full_backup = bkp

    if current_full_backup is None:
        raise Exception("Full backup not found, invalid url?")

    download(base + "/a00000.zpaq." + current_full_backup["index_version"], work_dir + "/a00000.zpaq").run(stdout)

    # download archives
    for i in range(1, int(v) + 1):
        fname = "a" + str(i).zfill(5) + ".zpaq"
        download(base + "/" + fname, work_dir + "/" + fname).run(stdout)

    # invoke zpaq
    zpaq_command = [get_script_dir() + "/zpaq", "extract", work_dir + "/a?????.zpaq", "-until", v,
                    "-force"]
    if verify:
        zpaq_command += ["-test"]

    if to != "":
        zpaq_command += ["-to", to]

    if password != "":
        zpaq_command += ["-key", password]

    with tempfile.NamedTemporaryFile(prefix="river-c-") as f:
        try:
            Proc(zpaq_command, "zpaq invocation failed").run(stdout, f)
        except Exception:
            f.seek(0)
            sys.stderr.write(f.read())


def pipe():
    class Pipe:
        def __init__(self):
            pass

        def __enter__(self):
            f = tempfile.NamedTemporaryFile(prefix="river-p-")
            f.close()
            self.fname = f.name
            Proc(["mkfifo", self.fname]).run(stdout)
            return self.fname

        def __exit__(self, exc_type, exc_val, exc_tb):
            os.remove(self.fname)

    return Pipe()


# river configuration file:
# exclude: []
# include_only: []
# keep_incremental_backup_count  how many incremental backups to keep
# keep_full_backup_count         how many full backups to keep

# river commands:
# new-config <config <file> or ->
# create <url> <config file or ->
# update <url> <config file or ->
# delete <url>
# list <url>
# backup <url> <dir(s) to backup>
# restore <url> <version> [target directory]


example_config = """# This is river configuration file
# Pass it to 'river create' or 'river update' command

# Comma-separated masks of files to exclude
# Example: ["*.tmp", "*/junk/*"]
exclude: []

# Comma-separated masks of files to include
# Example: ["*.jpg"]
include_only: []

# How many incremental backups to keep within single full backup
# When this limit is reached, new full backup will be started
keep_incremental_backup_count: 30

# How many full backups to keep
# When this limit is reached, oldest backup will be deleted
keep_full_backup_count: 3

# Encrypt backups if true
# Encryption key must be passed to river via river_key environment variable
use_encryption: false
"""


def help():
    sys.stderr.write("Usage: river.py [-v] <command> [backup url, if applicable] <command arguments>\n")
    sys.stderr.write("Backups directories to remote locations, supporting incremental backups,\n")
    sys.stderr.write("  compression, encryption, backup rolling and easy custom connectors.\n")
    sys.stderr.write("\n")
    sys.stderr.write("Backup url is <connector>:<connector-specific path>\n")
    sys.stderr.write("Supported connector names are directory names under this script\n")
    sys.stderr.write("  directory which contains connector scripts.\n")
    sys.stderr.write("\n")
    sys.stderr.write("Supported commands:\n")
    sys.stderr.write("new-config <config file>       Create example backup configuration file (use - for stdout)\n")
    sys.stderr.write("create <url> <config file>        Create new remote backup at this url with this config (use - for stdin)\n")
    sys.stderr.write("update <url> <config file>        Update configuration of existing remote backup (use - for stdin)\n")
    sys.stderr.write("delete <url>                      Delete remote backup, irreversibly\n")
    sys.stderr.write("list <url>                        Show remote backup configuration and available versions for "
                     "restore \n")
    sys.stderr.write("backup <url> <dirs>               Perform incremental backup on space-separated directories\n")
    sys.stderr.write("restore <url> <version> [target]  Restore backup at specified version. Files will be restored "
                     "under target\n")
    sys.stderr.write("                                  directory if provided, otherwise files will be restored inplace.\n")
    sys.stderr.write("verify <url> <version>            Verify backup correctness at specified version.\n")
    sys.stderr.write("\n")
    sys.stderr.write("If backup encryption is used, encryption password must be provided in river_key environment "
                     "variable.\n")


def help_on_error(result):
    if result is not None and "error" in result:
        sys.stderr.write("error: " + result["error"] + "\n")
        sys.stderr.write("\n")
        help()
        sys.exit(1)


def fail(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def parse_command(argv):
    if len(argv) < 2:
        return {"error": "Command not specified"}

    if argv[1] == "-v":
        argv = [argv[0]] + argv[2:]
        global stdout
        stdout = sys.stdout

    if argv[1] not in commands:
        return {"error": "Unknown command " + argv[1]}

    cmd = commands[argv[1]]
    param_count = len(argv) - 2

    if param_count < cmd[1]:
        return {"error": "Not enough arguments for command " + argv[1]}

    if cmd[2] is not None and param_count > cmd[2]:
        return {"error": "Too many arguments for command " + argv[1]}

    return {
        "cmd": cmd[0],
        "params": argv[2:]
    }


def normalize_url(url):
    if url.endswith("/"):
        return url[:-1]
    else:
        return url


def psw():
    if "river_key" in os.environ:
        return os.environ["river_key"]
    else:
        return ""


def update_config(state, cfg):
    def check_list(name):
        for e in cfg[name]:
            if not isinstance(e, str):
                fail(name + " must only contain strings")

    def check(name, tpe):
        if not isinstance(cfg[name], tpe):
            fail(name + " must be " + tpe)

    check_list("exclude")
    check_list("include_only")
    check("keep_incremental_backup_count", int)
    check("keep_full_backup_count", int)
    check("use_encryption", bool)

    state["local"]["exclude"] = cfg["exclude"]
    state["local"]["include_only"] = cfg["include_only"]
    state["keep_incremental_backup_count"] = cfg["keep_incremental_backup_count"]
    state["keep_full_backup_count"] = cfg["keep_full_backup_count"]
    state["use_encryption"] = cfg["use_encryption"]


def extract_config(state):
    return {
        "exclude": state["local"]["exclude"],
        "include_only": state["local"]["include_only"],
        "keep_incremental_backup_count": state["keep_incremental_backup_count"],
        "keep_full_backup_count": state["keep_full_backup_count"],
        "use_encryption": state["use_encryption"]
    }


def cmd_create_config(args):
    if args[0] == '-':
        print(example_config)
        return

    if os.path.exists(args[0]):
        fail("File " + args[0] + " already exists, refusing to overwrite")
    with open(args[0], "w") as f:
        f.write(example_config)
    pass


def cmd_create(args):
    url = normalize_url(args[0])
    cfg_file = args[1]
    if cfg_file == '-':
        cfg = yaml.safe_load(sys.stdin)
    else:
        if not os.path.exists(cfg_file):
            fail("Configuration file not found: " + cfg_file)

        with open(cfg_file) as f:
            cfg = yaml.safe_load(f.read())

    state = {
        "local": {
            "exclude": [],
            "include_only": [],
        },
        "keep_incremental_backup_count": 10,
        "keep_full_backup_count": 3,
        "last_backup_timestamp": 0,
        "full_backups": [],
        "use_encryption": False
    }

    update_config(state, cfg)

    try:
        download(url + "/index.yaml", "/dev/null").pipe(Proc.sink("/dev/null")).run(stdout, stdout)
        fail("Backup already exists at url " + args[0])
    except Exception as e:
        pass

    if psw() != "":
        if not state["use_encryption"]:
            fail("Password is provided via river_key env variable but encryption is disabled in config")
    else:
        if state["use_encryption"]:
            fail("Encryption is enabled in config but password not provided via river_key env variable")

    save_state(url, state, psw())


def cmd_update(args):
    url = normalize_url(args[0])
    cfg_file = args[1]

    if cfg_file == '-':
        cfg = yaml.safe_load(sys.stdin)
    else:
        if not os.path.exists(cfg_file):
            fail("Configuration file not found: " + cfg_file)

        with open(cfg_file) as f:
            cfg = yaml.safe_load(f.read())

    state = load_state(url, psw())

    update_config(state, cfg)

    if psw() != "":
        if not state["use_encryption"]:
            fail("Password is provided via river_key env variable but encryption is disabled in config")
    else:
        if state["use_encryption"]:
            fail("Encryption is enabled in config but password not provided via river_key env variable")

    save_state(url, state, psw())


def cmd_delete(args):
    delete(args[0]).run(stdout)
    pass


def cmd_list(args):
    url = normalize_url(args[0])
    state = load_state(url, psw())
    config = extract_config(state)
    versions = restore_urls(state)
    print("Configuration")
    print("")
    print(yaml.dump(config))
    print("Available backup versions")
    print("")
    print("Version                  \tTimestamp")
    for v in versions:
        print(v["version"] + "\t" + v["date"])


def cmd_backup(args):
    url = normalize_url(args[0])
    dirs = args[1:]
    perform_backup(url, dirs, psw())


def cmd_restore(args):
    url = normalize_url(args[0])
    version = args[1]
    if len(args) < 3:
        target = ""
    else:
        target = args[2]

    restore(url, version, psw(), target)


def cmd_verify(args):
    url = normalize_url(args[0])
    version = args[1]
    restore(url, version, psw(), verify=True)


commands = {
    "new-config": [cmd_create_config, 1, 1],
    "create": [cmd_create, 2, 2],
    "update": [cmd_update, 2, 2],
    "delete": [cmd_delete, 1, 1],
    "list": [cmd_list, 1, 1],
    "backup": [cmd_backup, 2, None],
    "restore": [cmd_restore, 2, 3],
    "verify": [cmd_verify, 2, 2]
}


def main():
    command = parse_command(sys.argv)
    help_on_error(command)

    r = command["cmd"](command["params"])
    help_on_error(r)


if __name__ == "__main__":
    main()

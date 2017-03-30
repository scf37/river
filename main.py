#!/usr/bin/env python

import os
import subprocess
import yaml
import datetime
import time
import logging
import sys
import shutil

work_dir = "/data/work"
remote_dir = os.getenv("backup_remote", "/data/remote")
remote_protocol = os.getenv("backup_protocol", "local")
zpaq_key = os.getenv("encryption_key", "")
use_ip_in_path = os.getenv("backup_use_ip_in_path", "true") == "true"
log_file_name = "/data/logs/backuper.log"
backup_config_dir = "/data/conf"
backup_tasks_dir = "/data/tasks"
backup_name_unique_counter = 0

backup_config = {
    "name": "qwe",
    "local": {
        "dirs": ["dir1", "dir2"],
        "exclude": ["*.tmp", "*.jar"],
        "include_only": []
    },

    "remote": "mybackupbucket",
    "keep_incremental_backup_count": 10,
    "keep_full_backup_count": 3,
    "backup_rate": "24h"
}

logger = None


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


# upload single file
def upload(src, dst):
    pr = subprocess.Popen([get_script_dir() + "/" + remote_protocol + "/upload", src, dst],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = pr.communicate()
    pr.poll()
    if pr.returncode == 0:
        log_info(out)
    else:
        log_warn(out)
        raise IOError("Upload " + src + " to " + dst + " failed")


# download single file
def download(src, dst, protocol=remote_protocol):
    pr = subprocess.Popen([get_script_dir() + "/" + protocol + "/download", src, dst],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = pr.communicate()
    pr.poll()
    if pr.returncode == 0:
        log_info(out)
    else:
        log_warn(out)
        raise IOError("Download " + src + " to " + dst + " failed")


def delete(src):
    pr = subprocess.Popen([get_script_dir() + "/" + remote_protocol + "/delete", src],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = pr.communicate()
    pr.poll()
    if pr.returncode == 0:
        log_info(out)
    else:
        log_warn(out)
        raise IOError("Delete " + src + " failed")


def full_local_dir(name):
    return work_dir + "/" + name


def full_remote_dir(name, remote, full_backup_name):
    return almost_full_remote_dir(name, remote) + "/" + full_backup_name


def almost_full_remote_dir(name, remote):
    if remote != "":
        d = remote_dir + "/" + remote + "/" + name
    else:
        d = remote_dir + "/" + name

    if use_ip_in_path:
        d = d + "/" + get_ip_address()

    return d


def compress(name, tmp_dir, options):
    index_file = name + "00000.zpaq"
    full_local = full_local_dir(name)

    if os.path.isfile(full_local + "/" + index_file):
        log_info("Starting INCREMENTAL backup of " + name)
        shutil.copyfile(full_local + "/" + index_file, tmp_dir + "/" + index_file)
    else:
        log_info("Starting FULL backup of " + name)

    zpaq_command = [get_script_dir() + "/zpaq",
                    "add",
                    tmp_dir + '/' + name + "?????"] + options + ["-index", tmp_dir + "/" + index_file]
    p = subprocess.Popen(zpaq_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, _ = p.communicate()
    p.poll()

    if p.returncode != 0:
        log_error(out)
        log_error("zpaq invocation failed")
        raise IOError("zpaq invocation failed")
    else:
        log_info(out)


def backup_upload(files, local_dir, full_remote):
    for f in files:
        upload(local_dir + "/" + f, full_remote + "/" + f)


def drop_incremental_backup_index(name):
    try:
        os.remove(full_local_dir(name) + "/" + name + "00000.zpaq")
    except OSError as e:
        log_warn(str(e))


# last_backup_timestamp: long
#  full_backups[].name
#  full_backups[].path
#  full_backups[].incremental_backups[]
#  upload
def load_state(name):
    ymlpath = full_local_dir(name) + "/" + name + ".yml"
    try:
        with open(ymlpath, mode="r") as f:
            return yaml.load(f.read())
    except IOError:
        return {
            "last_backup_timestamp": 0,
            "full_backups": []
        }


def save_state(name, state):
    try:
        os.makedirs(full_local_dir(name))
    except os.error:
        pass

    ymlpath = full_local_dir(name) + "/" + name + ".yml"
    with open(ymlpath, mode="w") as f:
        f.write(yaml.dump(state))


def collect_options(local):
    s = local["dirs"]
    if local["exclude"] is not None:
        for e in local["exclude"]:
            s += ["-not", e]
    if local["include_only"] is not None:
        for i in local["include_only"]:
            s += ["-only", i]
    if zpaq_key != "":
        s += ["-key", zpaq_key]
    return s


def delete_full_backup(name, remote, full_backup_name):
    rp = full_remote_dir(name, remote, full_backup_name)
    try:
        delete(rp)
    except IOError as e:
        log_warn(e.message)


def new_full_backup_name():
    global backup_name_unique_counter
    n = datetime.datetime.now().strftime('%Y-%m-%d__%H_%M_%S') + "_" + str(backup_name_unique_counter)
    backup_name_unique_counter += 1

    return n


def roll_full_backup(state, config):
    name = config["name"]

    def start_new_full_backup():
        nm = new_full_backup_name()
        state["full_backups"].append({
            "name": nm,
            "path": remote_protocol + ":" + name + ":" + full_remote_dir(name, config["remote"], nm),
            "incremental_backups": []
        })

    if len(state["full_backups"]) == 0:  # no backups at all? start new one!
        start_new_full_backup()

    current_full_backup = state["full_backups"][-1]

    if len(current_full_backup["incremental_backups"]) > config["keep_incremental_backup_count"]:
        # need to do full backup
        drop_incremental_backup_index(name)
        start_new_full_backup()

    while len(state["full_backups"]) > config["keep_full_backup_count"]:
        delete_full_backup(name, config["remote"], state["full_backups"][0]["name"])
        del state["full_backups"][0]


def perform_backup(state, config):
    name = config["name"]

    roll_full_backup(state, config)

    current_full_backup = state["full_backups"][-1]

    full_remote = full_remote_dir(name, config["remote"], current_full_backup["name"])
    full_local = full_local_dir(name)
    index_file = name + "00000.zpaq"
    tmp_dir = full_local + "/tmp"

    def clean_tmp_dir():
        shutil.rmtree(tmp_dir, True)
        os.makedirs(tmp_dir)

    try:
        clean_tmp_dir()
        compress(name, tmp_dir, collect_options(config["local"]))

        files = filter(lambda f: os.path.isfile(tmp_dir + "/" + f) and f != index_file, os.listdir(tmp_dir))

        backup_upload(files, tmp_dir, full_remote)

        # totally commit
        shutil.move(tmp_dir + "/" + index_file, full_local + "/" + index_file)
        state["last_backup_timestamp"] = int(time.time())
        current_full_backup["incremental_backups"].append(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

        save_state(name, state)

    finally:
        clean_tmp_dir()


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


def parse_backup_rate(s):
    if s.endswith("d"):
        return int(s[0:-1]) * 24 * 60 * 60
    if s.endswith("h"):
        return int(s[0:-1]) * 60 * 60
    if s.endswith("m"):
        return int(s[0:-1]) * 60
    raise Exception("Invalid backup rate, must be 1d / 1h / 1m:" + s)


def restore_names():
    conf = load_backup_configs()
    return map(lambda c: c["config"]["name"], conf)


# [].url
# [].date
def restore_urls(name):
    conf = load_backup_configs()
    for c in conf:
        if not c["config"]["name"] == name:
            continue

        r = []
        for fb in c["state"]["full_backups"]:
            i = 1
            for ib in fb["incremental_backups"]:
                r.append({
                    "url": fb["path"] + "#" + str(i),
                    "date": ib
                })
                i += 1
        return r

    return []


# restore backup by backup URL
# please note that archive keep absolute file names and extraction will work in the same way
# if you want to extract to somewhere else, use second parameter
def restore(url, to=""):
    i_first_colon = url.index(":")
    i_second_colon = url.index(":", i_first_colon + 1)

    protocol = url[0: i_first_colon]
    name = url[i_first_colon + 1: i_second_colon]
    real_url = url[i_second_colon + 1: url.rindex("#")]
    n = int(url[url.rindex("#") + 1:])

    # download archive
    for i in range(1, n + 1):
        fname = name + str(i).zfill(5) + ".zpaq"
        download(real_url + "/" + fname, work_dir + "/restore/" + fname, protocol)

    # invoke zpaq
    args = [get_script_dir() + "/zpaq", "extract", work_dir + "/restore/" + name + "?????.zpaq", "-until", str(n),
            "-force"]

    if to != "":
        args += ["-to", to]

    if zpaq_key != "":
        args += ["-key", zpaq_key]
    subprocess.call(args)
    pass


# [].file - short file name of task
# [].name - backup task name
def backup_tasks():
    if not os.path.exists(backup_tasks_dir):
        os.makedirs(backup_tasks_dir)

    result = []

    for f in os.listdir(backup_tasks_dir):
        p = os.path.join(backup_tasks_dir, f)
        if os.path.isfile(p) and not f.endswith("-ok") and not f.endswith("-error"):
            try:
                with open(p, "r") as ff:
                    name = ff.read().strip()
                    result.append({
                        "name": name,
                        "file": f
                    })
            except OSError as e:
                log_warn("Unable to open backup task " + f + ": " + str(e))
                pass

    result.sort(key=lambda a: a['file'])
    return result


def commit_backup_task(f, url, error):
    if not os.path.exists(backup_tasks_dir):
        os.makedirs(backup_tasks_dir)

    try:
        os.remove(os.path.join(backup_tasks_dir, f))

        if url != "":
            with open(os.path.join(backup_tasks_dir, f + "-ok"), "w") as ff:
                ff.write(url)
        else:
            with open(os.path.join(backup_tasks_dir, f + "-error"), "w") as ff:
                ff.write(error)
    except OSError:
        pass


def process_backup_tasks():
    tasks = backup_tasks()
    if len(tasks) == 0:
        return
    confs = load_backup_configs()

    def get_config(name):
        for conf in confs:
            if conf["config"]["name"] == name:
                return conf
        return None

    for task in tasks:
        c = get_config(task["name"])
        if c is None:
            err = "Failed to process task " + task["file"] + ": Unknown backup name " + task["name"]
            log_error(err)
            commit_backup_task(task["file"], "", err)

        perform_backup(c["state"], c["config"])
        last_backup = c["state"]["full_backups"][-1]
        url = last_backup["path"] + "#" + str(len(last_backup["incremental_backups"]))
        commit_backup_task(task["file"], url, "")


def process_scheduled_backups():
    conf = load_backup_configs()
    now = int(time.time())
    for c in conf:
        config = c["config"]
        try:
            state = c["state"]
            if now - state["last_backup_timestamp"] > parse_backup_rate(config["backup_rate"]):
                perform_backup(state, config)
        except Exception as e:
            log_error("Failed to backup " + str(config.get("name")) + ": " + str(e))


def main():
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

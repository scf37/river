#!/usr/bin/env python

# Confyrm application startup script
# It always starts first in docker image, loads and validates configuration and executes/replaces with next script
# Configuration is provided in service.yml and can be collected from:
# - env variables
# - /data/conf/<appname>.properties, where <appname> is "name" from service.yml
# Also this script provides stdout redirection and cool error reporting.

import yaml
import os
import sys
import shutil

service_yml = "/service.yml"
log_file = "/data/logs/stdout.log"
script_name = "/opt/app"
script_cmdline = []


def parse_cmdline():
    global script_name
    global script_cmdline
    global log_file

    i = 1
    while i < len(sys.argv):
        name = sys.argv[i]
        if name == "--script":
            if i + 1 == len(sys.argv):
                print("Missing argument for --script")
                exit(2)
            script_name = sys.argv[i + 1]
            i += 2
            continue
        if name == "--log-file":
            if i + 1 == len(sys.argv):
                print("Missing argument for --log-file")
                exit(2)
            log_file = sys.argv[i + 1]
            i += 2
            continue
        script_cmdline = sys.argv[i:]
        break


def log(s):
    global log_file

    if log_file == "stdout":
        print(s)
    else:
        try:
            os.makedirs(os.path.dirname(log_file))
        except OSError:
            pass

        try:
            with open(log_file, "a") as myfile:
                myfile.write(s + "\n")
        except IOError, e:
            print("Can't write to " + log_file + ": " + str(e))
            print("Using stdout.")
            log_file = "stdout"


def read_yaml():
    f = open(service_yml, 'r')
    r = yaml.load(f)
    f.close()
    return r


def extract_parameters(conf):
    result = []

    def append_param(p):
        if "param" in p:
            result.append(p)

    if "config" in conf:
        for p in conf["config"]:
            append_param(p)

    for service in conf["provides"]:
        append_param(service["service"]["name"])
        append_param(service["service"]["port"])

    for service in conf["consumes"]:
        s = service["service"]
        result.append(s["name"])
        if "auth" in s:
            for auth in s["auth"]:
                append_param(s["auth"][auth])

    return result


def print_usage(name, help_msg, parameters):
    print("Command-line parameters:")
    print("  --script <filename> Script to exercute inside the container and switch to, /opt/app by default")
    print("  --log-file <filename or stdout> Log file to redirect console logs into, /data/logs/stdout.log by default")
    print("  --help print this help message")
    print("Configuration parameters, accepted via env variables or /data/conf/" + name + ".properties:")
    required_params = []
    for p in parameters:
        if "default" not in p:
            required_params.append(p)

    print("  {: <30} {: <20} {: <20}".format("Name", "Default value", "Description"))
    for p in sorted(filter(lambda arg: "default" not in arg, parameters), key=lambda arg: arg["param"]):
        print("  {: <30} {: <20} {: <20}".format(p["param"], "<none>", p.get("description")))

    for p in sorted(filter(lambda arg: "default" in arg, parameters), key=lambda arg: arg["param"]):
        d = p.get("default")
        if d == "":
            d = "\"\""
        print("  {: <30} {: <20} {: <20}".format(p["param"], d, p.get("description")))
    if help_msg is not None:
        print(help_msg)


def load_config(fname):
    try:
        f = open(fname)
    except IOError:
        return []

    r = {}
    for l in f.readlines():
        l = l.strip()
        if l != "" and l[0] != '#':
            pair = str(l).split("=", 1)
            r[pair[0].strip()] = pair[1].strip()

    f.close()
    return r


def resolve_params_to_env(name, help_msg, parameters):
    fc = load_config("/data/conf/" + name + ".properties")
    missing_parameters = []

    for p in parameters:
        n = p["param"]
        if n in os.environ:
            continue
        if n in fc:
            os.environ[n] = fc[n]
            continue
        if "default" in p:
            os.environ[n] = p["default"]
            continue
        missing_parameters.append(n)

    if len(missing_parameters) != 0:
        print("Error: missing required parameter(s) " + ", ".join(missing_parameters))
        print("")
        print_usage(name, help_msg, parameters)
        exit(1)


def print_parameters(parameters):
    log("Starting with parameters:")
    for p in sorted(parameters, key=lambda arg: arg["param"]):
        name = p["param"]
        value = os.environ.get(name)
        if p.get("secret"):
            log("  {: <30} {}".format(name, "******"))
        else:
            log("  {: <30} {}".format(name, value))


def main():
    parse_cmdline()
    conf = read_yaml()

    log(conf["name"] + " - " + conf["description"])
    # param, default, description
    parameters = extract_parameters(conf)

    if len(sys.argv) > 1 and "--help" in sys.argv:
        print_usage(conf["name"], conf.get("help"), parameters)
        exit(0)

    resolve_params_to_env(conf["name"], conf.get("help"), parameters)
    print_parameters(parameters)
    shutil.copyfile(service_yml, "/data/" + os.path.basename(service_yml))

    if log_file != "stdout":
        sys.stdout = open(log_file, "a")
        sys.stderr = sys.stdout
        os.dup2(sys.stdout.fileno(), 1)
        os.dup2(sys.stderr.fileno(), 2)

    os.execv(script_name, [script_name] + script_cmdline)

main()

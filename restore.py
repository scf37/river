#!/usr/bin/env python

import sys

import main as m


def print_usage():
    print('Backuper restore utility')
    print('To restore, you must know backup name and backup url')
    print('use --names to list *locally known* backup names')
    print('use --urls <name> to list *locally known* backup urls')
    print('use --restore <url> to restore backup')
    print('Backups store absoluthe paths so files will be extracted to the same place where they were taken')
    print('to extract to specific path, use --to option: --restore <url> --to ~/tmp')
    print('In case local configuration is unavailable, backup url can be constructed manually:')
    print('[protocol]:[name]:[remote url]#[version]')
    print('  protocol - local or s3')
    print('  name - backup name. It is .zpaq archive name without numbers and extension. qwe00001.zpaq -> qwe')
    print('  remote url - full path to directory with .zpaq files')
    print('  version - version to extract (1 - n). integer identical to number in .zpaq file name.')
    exit(1)


def print_names():
    names = m.restore_names()
    for name in names:
        print(name)
    if len(names) == 0:
        print("No names are defined locally")


def print_urls(name):
    urls = m.restore_urls(name)
    for url in urls:
        print("{: <30}{}".format(url["date"], url["url"]))
    if len(urls) == 0:
        print("No urls are defined locally")


def restore(url, to=""):
    m.restore(url, to)


def main():
    if len(sys.argv) == 1:
        print("Error: missing required arguments")
        print_usage()
    elif len(sys.argv) == 2 and sys.argv[1] == "--names":
        print_names()
    elif len(sys.argv) == 3 and sys.argv[1] == "--urls":
        print_urls(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--restore":
        restore(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "--restore" and sys.argv[3] == "--to":
        restore(sys.argv[2], sys.argv[4])
    elif len(sys.argv) == 5 and sys.argv[1] == "--to" and sys.argv[3] == "--restore":
        restore(sys.argv[4], sys.argv[2])
    else:
        print("Error: invalid arguments")
        print_usage()


if __name__ == "__main__":
    main()

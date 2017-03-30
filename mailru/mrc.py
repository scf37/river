#!/usr/bin/python3

import json
import os
import sys
import time
import urllib
import urllib.parse
import requests
import hashlib
import yaml

# https://github.com/SerjPopov/cloud-mail-ru-php

_cookies = requests.utils.cookiejar_from_dict({})
_session = requests.Session()
_token = ''
_x_page_id = ''
_build = ''
_upload_url = ''
_download_url = ''
_user = ''
_domain = ''
verbose = False
# upload split size, mail.ru allows files for up to 2 Gb
split_size = 2000000000 - 1024


class SubFile:
    def __init__(self, f, _off, _len):
        self._f = f
        self._off = _off
        self._len = _len
        self._off_end = _off + _len
        f.seek(_off)

    def read(self, size=None):
        curr_off = self._f.tell()
        if size is None:
            sz = self._off_end - curr_off
        elif curr_off + size <= self._off_end:
            sz = size
        else:
            sz = self._off_end - curr_off

        return self._f.read(sz)
    pass


def _req(method: str, url: str, data=None, files=None, stream=False):
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "en-US,en;q=0.5",
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:44.0) Gecko/20100101 Firefox/44.0",
        "Referer": url
    }
    if files is None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if verbose:
        print(method + " " + url)
    if method == 'get':
        return _session.get(url, headers=headers, stream=stream)
    elif method == 'delete':
        return _session.delete(url, headers=headers, stream=stream)
    elif method == 'put':
        return _session.put(url, headers=headers, data=data, files=files, allow_redirects=False, stream=stream)
    elif method == 'post':
        return _session.post(url, headers=headers, data=data, files=files, allow_redirects=False, stream=stream)
    else:
        raise Exception("invalid http method: " + method)

#[].size
#[].type (file or folder)
#[].name
def ls(dir_: str):
    url_base = 'https://cloud.mail.ru/api/v2/folder?home=%2F&sort={%22type%22%3A%22name%22%2C%22order%22%3A%22asc%22}&offset=0&limit=500&api=2&'
    mail = _user + '@' + _domain

    url = url_base + urllib.parse.urlencode({
        'home': dir_,
        'build': _build,
        'x-page-id': _x_page_id,
        'email': mail,
        'x-email': mail,
        'token': _token,
        '_': str(int(time.time()))
    })

    resp = json.loads(_req('get', url).text)

    # list of {size, type, name}. type can be 'file' or 'folder'
    return resp['body']['list']


def mkdir(dir_: str):
    url = 'https://cloud.mail.ru/api/v2/folder/add'
    data = {
        'api': '2',
        'build': _build,
        'conflict': 'rename',
        'email': _user + '@' + _domain,
        'home': dir_,
        'token': _token,
        'x-email': _user + '@' + _domain,
        'x-page-id': _x_page_id
    }

    resp = _req('post', url, data)
    if resp.status_code >= 400:
        raise Exception("Can't create directory " + dir_ + ": " + resp.text)


def rm(file: str):
    # rm file or directory

    url = 'https://cloud.mail.ru/api/v2/file/remove'
    data = {
        'api': '2',
        'build': _build,
        'conflict': 'rename',
        'email': _user + '@' + _domain,
        'home': file,
        'token': _token,
        'x-email': _user + '@' + _domain,
        'x-page-id': _x_page_id
    }

    resp = _req('post', url, data)
    if resp.status_code >= 400:
        raise Exception("Can't remove file " + file + ": " + resp.text)


def __upload_state_fname(localFile: str, remoteFile: str):
    key = localFile + "*" + remoteFile + "*" + str(os.path.getsize(localFile))
    return "/data/_upload_state/" + str(hashlib.md5(key.encode('utf-8')).hexdigest())


#
#
#
def _load_upload_state(localFile: str, remoteFile: str):
    try:
        fname = __upload_state_fname(localFile, remoteFile)
        with open(fname, mode="r") as f:
            return yaml.load(f.read())
    except IOError:
        return {
            "off": 0,
            "suffix": 0
        }


def _save_upload_state(localFile: str, remoteFile: str, state):
    if not os.path.exists(localFile):
        return

    try:
        os.makedirs("/data/_upload_state")
    except os.error:
        pass

    if state is None:
        try:
            fname = __upload_state_fname(localFile, remoteFile)
            os.remove(fname)
        except IOError:
            pass
        return

    try:
        fname = __upload_state_fname(localFile, remoteFile)
        with open(fname, mode="w") as f:
            f.write(yaml.dump(state))
    except IOError:
        pass


def upload(localFile: str, remoteFile: str):
    sz = os.path.getsize(localFile)
    if sz < split_size:  # can upload as-is
        _upload(localFile, remoteFile, 0, sz)
    else:  # split file to upload into chunks of split_size bytes
        state = _load_upload_state(localFile, remoteFile)
        off = state["off"]
        suffix = state["suffix"]
        while off < sz:
            s = ''
            i = suffix
            while True:
                s += chr(ord('a') + (i % 26))
                i = int(i / 26)
                if i == 0:
                    break
            len_ = min(split_size, sz - off)
            _upload(localFile, remoteFile + ".part" + s, off, len_)
            off += len_
            suffix += 1
            state["off"] = off
            state["suffix"] = suffix
            _save_upload_state(localFile, remoteFile, state)
        _save_upload_state(localFile, remoteFile, None)


def _upload(localFile: str, remoteFile: str, off, sz):
    rm(remoteFile)

    def doUpload(localFile: str):
        # curl 'https://cloclo28-upload.cloud.mail.ru/upload/
        # ?cloud_domain=2&x-email=scf37%40mail.ru&fileapi148613862579710' -H 'Content-Type: multipart/form-data; boundary=----WebKitFormBoundaryLoqLLChEO0q3Vjal' -H 'Accept: */*' -H 'Cache-Control: no-cache' -H 'X-Requested-With: XMLHttpRequest' -H 'Cookie: p=+1UAAF4+7gAA; mrcu=86C5564F0D7951BAEFCA5D01A12E; _ym_uid=1466774502371218083; act=9ee53c858cca471eb9aea1653b12bfc7; c=GnE8WAAAADkNbAAhAAQAVQIBAAQA; i=AQDqC4tYBwATAAhSG3wAAdsAARwBAR8BAZoBARkCARsCAeoCAQADAUgEAZUEAR0GAaIGAQIHATcHAjwHAdsHAU0IAXMIAXYIAXcIAYkJAZoJAf4JASgKATcKAW4KAU4CCAQBKAABkwIINxJlAAFsAAFuAAFvAAFyAAF2AAGBAAHCAAH6AAH7AAERAQEVAQEeAQEsAQEvAQFEAQFFAQFGAQHcBAgEAQEAAeEECQEB4gQKBBwMvgfWBggEAQEAAQ==; b=LkMBADAtNVcAAQAQzmPiBgAA; searchuid=527586981448012070; _gat=1; t=obLD1AAAAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAACAAAEBbAcA; sdcs=0CGkdfRx62LYcoWz; _ga=GA1.2.1374535807.1448021369; s=fver=16; _ym_isad=2; VID=05X34p1bDW1Y0000060C14nY::1967099:; Mpop=1486138587:737d514261415365190502190805001b05031d02040d4b6a515f475a05010800091800000f1742535704021658505d5b174345:scf37@mail.ru:' -H 'Connection: keep-alive' -H 'Referer: https://cloud.mail.ru/home/' --data-binary $'------WebKitFormBoundaryLoqLLChEO0q3Vjal\r\nContent-Disposition: form-data; name="file"; filename="mrc-test-1486138492.9054418"\r\nContent-Type: application/octet-stream\r\n\r\n\r\n------WebKitFormBoundaryLoqLLChEO0q3Vjal\r\nContent-Disposition: form-data; name="_file"\r\n\r\nmrc-test-1486138492.9054418\r\n------WebKitFormBoundaryLoqLLChEO0q3Vjal--\r\n' --compressed
        url = _upload_url + '?cloud_domain=2&x-email=' + _user + '%40' + _domain + '&fileapi' + str(int(time.time())) + '0376'

        with open(localFile, "rb") as f:
            resp = _req('post', url, data=None, files=[('file', ('test.txt', SubFile(f, off, sz), 'application/octet-stream'))])

        r = resp.text.split(';')
        return {
            "hash": r[0].strip(),
            "size": r[1].strip()
        }

    def add(hash_, size, dir_):
        data = {
            'api': '2',
            'build': _build,
            'conflict': 'rename',
            'email': _user + '@' + _domain,
            'home': remoteFile,
            'hash': hash_,
            'size': size,
            'token': _token,
            'x-email': _user + '@' + _domain,
            'x-page-id': _x_page_id
        }
        url = 'https://cloud.mail.ru/api/v2/file/add'
        r = _req('post', url, data)
        if ':200' not in r.text:
            raise IOError("Upload failed: " + r.text)

    upl = doUpload(localFile)
    add(upl['hash'], upl['size'], remoteFile)


def download(remoteFile: str, localFile: str):
    try:
        _download(remoteFile, localFile)  # try file as-is
    except IOError:
        # may be it is split file? erase local one and append all found parts!
        with open(localFile, 'wb'):
            pass
        _download(remoteFile + ".parta", localFile, append=True)
        suffix = 1
        try:
            while True:
                s = ''
                i = suffix
                while True:
                    s += chr(ord('a') + (i % 26))
                    i = int(i / 26)
                    if i == 0:
                        break
                _download(remoteFile + ".part" + s, localFile, append=True)
                suffix += 1
        except IOError as e:
            if 'No such file ' not in str(e):
                raise e


def _download(remoteFile: str, localFile: str, append=False):
    # https://cloclo18.datacloudmail.ru/get/tmp/mrc-test-1486141096.1744552.txt?x-email=scf37%40mail.ru
    url = _download_url + remoteFile + "?x-email=" + _user + '%40' + _domain
    r = _req("get", url, stream=True)

    if r.status_code >= 300:
        raise IOError("No such file " + remoteFile)

    if append:
        mode = 'ab'
    else:
        mode = 'wb'

    with open(localFile, mode) as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:  # filter out keep-alive new chunks
                f.write(chunk)


def login(user_: str, domain_: str, password_: str):
    def json_value(text: str, key):
        try:
            i = text.index('"' + key + '":')
            i1 = text.index('"', i + len(key) + 3)
            i2 = text.index('"', i1 + 1)
            return text[i1 + 1:i2]
        except:
            raise Exception("can't locate json key '" + key + "'")

    def json_value_by_substr(text: str, substr: str):
        i = text.index(substr)
        i1 = text.rindex('"', 0, i)
        i2 = text.index('"', i)
        return text[i1 + 1:i2]

    data = {
        "page": "https://cloud.mail.ru/?from=promo",
        "FailPage": "",
        "Domain": domain_,
        "Login": user_,
        "Password": password_,
        "new_auth_form": "1",
        "saveauth": "1"
    }
    resp = _req('post', 'http://auth.mail.ru/cgi-bin/auth?lang=ru_RU&from=authpopup', data)
    if resp.status_code >= 400:
        print("Authentication failed: " + str(resp.status_code))
        print(resp.headers)
        exit(1)

    resp = _req('get', 'https://cloud.mail.ru/?from=promo&from=authpopup')
    if resp.status_code > 200 or '"csrf"' not in resp.text:
        print("Authentication failed(2): " + str(resp.status_code))
        print(resp.headers)
        exit(1)

    global _token
    global _x_page_id
    global _build
    global _upload_url
    global _download_url
    global _user
    global _domain

    _token = json_value(resp.text, 'csrf')
    _x_page_id = json_value(resp.text, 'x-page-id')
    _build = json_value(resp.text, 'BUILD')
    _upload_url = json_value_by_substr(resp.text, "mail.ru/upload/")
    _download_url = json_value_by_substr(resp.text, "datacloudmail.ru/get")

    _user = user_
    _domain = domain_

    if verbose:
        print("token = " + _token)
        print("x_page_id = " + _x_page_id)
        print("build = " + _build)
        print("upload_url = " + _upload_url)
        print("download_url = " + _download_url)


def _print_usage():
    print('Mail.ru Cloud client, with support for 2GB+ files')
    print('usage:')
    print('  mrc COMMAND <parameters>')
    print('Available commands:')
    print('  ls <dir> - display directory contents')
    print('  upload <localFile> <remoteFile> - upload single file to the cloud')
    print('  download <remoteFile> <localFile> - download single file from the cloud')
    print('  mkdir <directory> - create new directory')
    print('  rm <file or directory> - remove file or directory')
    print('Available parameters, can be set via env variables or -<name> <value>')
    print('  email - mail.ru account email, e.g. bob@mail.ru')
    print('  password - mail.ru account password')
    print('  verbose - Print network queries. true or false, default false')
    exit(1)


def _error(msg):
    print('ERROR: ' + msg)
    print()
    _print_usage()


# {cmd: str, params: name->value}
def _parse_cmdline():
    if len(sys.argv) == 1:
        _print_usage()

    available_commands = {'ls': 1, 'upload': 2, 'download': 2, 'mkdir': 1, 'rm': 1}
    available_parameters = ['email', 'password', 'verbose']

    cmd = sys.argv[1]

    if cmd not in available_commands:
        _error('Unknown command ' + cmd)

    if len(sys.argv) < 2 + available_commands[cmd]:
        _error('Not enough arguments for command ' + cmd)

    params = {}
    for p in available_parameters:
        if p in os.environ:
            params[p] = os.environ[p]

    for i in range(2 + available_commands[cmd], len(sys.argv), 2):
        k = sys.argv[i]
        if i + 1 == len(sys.argv):
            v = None
        else:
            v = sys.argv[i + 1]

        if not k.startswith('-'):
            _error('Parameter name does not start with "-": ' + k)

        if k[1:] not in available_parameters:
            _error('Unknown parameter name: ' + k[1:])

        if v is None:
            _error('No value provided for parameter ' + k[1:])

        params[k[1:]] = v

    return {
        'cmd': cmd,
        'params': params
    }


def _main():
    p = _parse_cmdline()
    cmd = p['cmd']
    params = p['params']

    if 'email' not in params or 'password' not in params:
        _error('email and password are mandatory')

    login(params['email'].split('@')[0], params['email'].split('@')[1], params['password'])

    if 'verbose' in params and params['verbose'] == 'true':
        global verbose
        verbose = True

    if cmd == 'ls':
        for e in ls(sys.argv[2]):
            print('{0:7}{1:>10} {2:20}'.format(e['type'], str(e['size']), e['name']))
    elif cmd == 'upload':
        upload(sys.argv[2], sys.argv[3])
    elif cmd == 'download':
        download(sys.argv[2], sys.argv[3])
    elif cmd == 'mkdir':
        mkdir(sys.argv[2])
    elif cmd == 'rm':
        rm(sys.argv[2])


if __name__ == '__main__':
    _main()

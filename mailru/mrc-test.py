#!/usr/bin/env python3
import unittest
import os
import time
import mrc
import getpass


class MyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        psw = getpass.getpass()
        mrc.login("scf37", "mail.ru", psw)

    def setUp(self):
        mrc.split_size = self.__split_size

    __c = 0
    __split_size = mrc.split_size

    def tmpfile(self):
        self.__c += 1
        return "/tmp/mrc-test-" + str(time.time()) + str(self.__c) + ".txt"

    def test_ls(self):
        self.assertTrue(len(mrc.ls("/")) != 0)

    def test_upload(self):
        f = self.tmpfile()
        ff = self.tmpfile()
        with open(f, "w") as f0:
            f0.write("hello, World!")

        mrc.upload(f, ff)
        rrr = list(filter(lambda a: a['name'] == ff[5:], mrc.ls("/tmp")))
        self.assertTrue(len(rrr) == 1)

    def test_mkdir_rmdir(self):
        f = self.tmpfile()
        mrc.mkdir(f)
        rrr = list(filter(lambda a: a['name'] == f[5:], mrc.ls("/tmp")))
        self.assertTrue(len(rrr) == 1)
        self.assertTrue(rrr[0]['type'] == 'folder')
        mrc.rm(f)
        rrr = list(filter(lambda a: a['name'] == f[5:], mrc.ls("/tmp")))
        self.assertTrue(len(rrr) == 0)

    def test_download(self):
        f = self.tmpfile()
        ff = self.tmpfile()
        fff = self.tmpfile()
        with open(f, "w") as f0:
            f0.write("hello, Download World!")
        mrc.upload(f, ff)
        mrc.download(ff, fff)
        assert(os.path.exists(fff))
        with open(fff, "r") as f0:
            s = f0.read()
        assert(s == "hello, Download World!")

    def test_file_split(self):
        mrc.split_size = 5

        f = self.tmpfile()
        ff = self.tmpfile()
        fff = self.tmpfile()
        with open(f, "w") as f0:
            f0.write("hello, Split World!")
        mrc.upload(f, ff)
        mrc.download(ff, fff)
        assert(os.path.exists(fff))
        with open(fff, "r") as f0:
            s = f0.read()
        assert(s == "hello, Split World!")


if __name__ == '__main__':
    unittest.main()

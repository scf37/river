#!/usr/bin/env python
import unittest
import main
import os
import time
import yaml

# To work, this tests except zpaq binary in current directory
class MyTest(unittest.TestCase):
    base = ""

    def remote_dir(self):
        return "/tmp/backuper-test-" + self.base + "/remote"

    def base_dir(self):
        return "/tmp/backuper-test-" + self.base

    def remote_url(self):
        return "local:" + self.remote_dir()
    remote_protocol = "local"
    password = "hello"

    def setUp(self):
        self.base = str(time.time())
        main.work_dir = "/tmp/backuper-test-" + self.base + "/work"
        main.log_file_name = "./backuper.log"

    def test_get_ip_address(self):
        self.assertNotEqual(main.get_ip_address(), "")

    def test_state_save_load(self):
        state0 = {
            "local": {
                "exclude": ["*.tmp"],
                "include_only": [],
            },
            "keep_incremental_backup_count": 10,
            "keep_full_backup_count": 3,
            "last_backup_timestamp": 0,
            "full_backups": []
        }
        main.save_state(self.remote_url(), state0, self.password)
        state = main.load_state(self.remote_url(), self.password)
        self.assertIsNotNone(state)
        self.assertIn("last_backup_timestamp", state)
        self.assertIn("full_backups", state)
        self.assertEqual(state["last_backup_timestamp"], 0)

        state["last_backup_timestamp"] = 123

        main.save_state(self.remote_url(), state, self.password)
        state = main.load_state(self.remote_url(), self.password)
        self.assertEqual(state["last_backup_timestamp"], 123)

        main.save_state(self.remote_url() + "2", state0, self.password)

        self.assertNotEqual(main.load_state(self.remote_url() + "2", self.password)["last_backup_timestamp"], 123)

    def test_collect_options(self):
        args = main.collect_options({
            "exclude": ["*.tmp", "*.jar"],
            "include_only": ["a*", "b?"]
        }, "")
        self.assertEqual(args, "-not *.tmp -not *.jar -only a* -only b?".split(" "))

    def test_perform_backup(self):

        def assert_exists(fname):
            p = self.remote_dir() + fname
            self.assertTrue(os.path.isfile(p), "File is missing: " + fname + " (" + p + ")")

        def assert_missing(fname):
            p = "/tmp/backuper-test-" + self.base + fname
            self.assertFalse(os.path.isfile(p), "File exists: " + fname + " (" + p + ")")

        dirs = [self.base_dir() + "/source"]
        state = {
            "local": {
                "exclude": [],
                "include_only": []
            },
            "keep_incremental_backup_count": 10,
            "keep_full_backup_count": 3,

            "last_backup_timestamp": 0,
            "full_backups": []
        }

        def assert_full_backup_is_sane(full_backup_name):
            base = "1/" \
                   + main.get_ip_address() + "/" + full_backup_name
            assert_exists(base + "/" + "a00001.zpaq")

        os.makedirs(dirs[0])
        url = self.remote_url() + "1"

        main.save_state(url, state, self.password)

        def perform_backup():
            with open(dirs[0] + "/some.file", "w") as f:
                f.write("some content" + str(time.time()))
            main.perform_backup(url, dirs, self.password)

        perform_backup()

        state = main.load_state(url, self.password)

        # archive header and data is uploaded
        remote_first_backup_base = "1/" + main.get_ip_address() + "/" + state["full_backups"][0]["name"]
        assert_full_backup_is_sane(state["full_backups"][0]["name"])

        # backup timestamp changed
        self.assertNotEqual(state["last_backup_timestamp"], 0)

        perform_backup()

        # second tome is added
        assert_exists(remote_first_backup_base + "/a00002.zpaq")

        # run another 9 incremental backups
        for _ in range(9):
            perform_backup()

        state = main.load_state(url, self.password)

        # state contains one full backup and 10 incremental ones
        self.assertEqual(len(state["full_backups"]), 1)
        self.assertEqual(len(state["full_backups"][0]["incremental_backups"]), 11)  # total number of backups

        # full backup is present on disk
        assert_full_backup_is_sane(state["full_backups"][0]["name"])
        assert_exists(remote_first_backup_base + "/a00011.zpaq")

        # rolling out another full backup
        perform_backup()

        state = main.load_state(url, self.password)

        # it is on disk
        assert_full_backup_is_sane(state["full_backups"][1]["name"])

        # state contains TWO full backups
        self.assertEqual(len(state["full_backups"]), 2)
        self.assertEqual(len(state["full_backups"][0]["incremental_backups"]), 11)
        self.assertEqual(len(state["full_backups"][1]["incremental_backups"]), 1)

        # run 10 incremental backups for second full backup
        for _ in range(10):
            perform_backup()

        # run third full backup and its 10 incremental backups
        for _ in range(11):
            perform_backup()

        # start FOURTH full backup
        perform_backup()

        state = main.load_state(url, self.password)

        # first full backup should be deleted by now
        self.assertEqual(len(state["full_backups"]), 3)

        # old first backup is gone, last three are present
        assert_full_backup_is_sane(state["full_backups"][0]["name"])
        assert_full_backup_is_sane(state["full_backups"][1]["name"])
        assert_full_backup_is_sane(state["full_backups"][2]["name"])

    def test_restore(self):
        state = {
            "local": {
                "exclude": [],
                "include_only": []
            },
            "keep_incremental_backup_count": 4,
            "keep_full_backup_count": 3,

            "last_backup_timestamp": 0,
            "full_backups": []
        }

        main.save_state(self.remote_url(), state, self.password)

        state = main.load_state(self.remote_url(), self.password)
        files_dir = self.base_dir() + "/source"
        os.makedirs(files_dir)

        def perform_backup(n):
            with open(files_dir + "/" + str(n) + ".file", "w") as f:
                f.write(str(n))
            main.perform_backup(self.remote_url(), [files_dir], self.password)

        for n in range(1, 11):
            perform_backup(n)

        state = main.load_state(self.remote_url(), self.password)

        urls = main.restore_urls(state)
        self.assertEqual(len(urls), 10)

        def assert_content(n):
            self.assertEqual(sorted(os.listdir(files_dir)), sorted(map(lambda a: str(a) + ".file", range(1, n + 1))))

        import subprocess
        subprocess.call(["bash", "-c", "rm " + files_dir + "/*"])
        assert_content(0)

        for n in range(1, 11):
            subprocess.call(["bash", "-c", "rm " + files_dir + "/*"])
            main.restore(self.remote_url(), urls[n - 1]["version"], self.password)
            assert_content(n)

        for n in range(10, 0, -1):
            subprocess.call(["bash", "-c", "rm " + files_dir + "/*"])
            main.restore(self.remote_url(), urls[n - 1]["version"], self.password)
            assert_content(n)


if __name__ == '__main__':
    unittest.main()

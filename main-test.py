#!/usr/bin/env python
import unittest
import main
import os
import time
import yaml


class MyTest(unittest.TestCase):
    base = ""

    def remote_dir(self):
        return "/tmp/backuper-test-" + self.base + "/remote"
    remote_protocol = "local"

    def setUp(self):
        self.base = str(time.time())
        main.work_dir = "/tmp/backuper-test-" + self.base + "/work"
        main.remote_dir = self.remote_dir()
        main.remote_protocol = self.remote_protocol
        main.log_file_name = "./backuper.log"

    def test_get_ip_address(self):
        self.assertNotEqual(main.get_ip_address(), "")

    def test_state_save_load(self):
        state = main.load_state("name1")
        self.assertIsNotNone(state)
        self.assertIn("last_backup_timestamp", state)
        self.assertIn("full_backups", state)
        self.assertEqual(state["last_backup_timestamp"], 0)

        state["last_backup_timestamp"] = 123

        main.save_state("name1", state)
        state = main.load_state("name1")
        self.assertEqual(state["last_backup_timestamp"], 123)

        self.assertNotEqual(main.load_state("name2")["last_backup_timestamp"], 123)

    def test_collect_options(self):
        args = main.collect_options({
            "dirs": ["dir1", "dir2"],
            "exclude": ["*.tmp", "*.jar"],
            "include_only": ["a*", "b?"]
        })
        self.assertEqual(args, "dir1 dir2 -only *.tmp -only *.jar -not a* -not b?".split(" "))

    def test_perform_backup(self):

        def assert_exists(fname):
            p = "/tmp/backuper-test-" + self.base + fname
            self.assertTrue(os.path.isfile(p), "File is missing: " + fname + " (" + p + ")")

        def assert_missing(fname):
            p = "/tmp/backuper-test-" + self.base + fname
            self.assertFalse(os.path.isfile(p), "File exists: " + fname + " (" + p + ")")

        config = {
            "name": "backup-name",
            "local": {
                "dirs": ["/tmp/backuper-test-" + self.base + "/source"],
                "exclude": [],
                "include_only": []
            },

            "remote": "remote-bucket",
            "keep_incremental_backup_count": 10,
            "keep_full_backup_count": 3,
            "backup_rate": "24h"
        }

        def assert_full_backup_is_sane(full_backup_name):
            base = "/remote/" + "/" + config["remote"] + "/" + config["name"] + "/" \
                   + main.get_ip_address() + "/" + full_backup_name
            assert_exists(base + "/" + config["name"] + "00001.zpaq")

        os.makedirs(config["local"]["dirs"][0])

        state = main.load_state("backup-name")

        def perform_backup():
            with open(config["local"]["dirs"][0] + "/some.file", "w") as f:
                f.write("some content" + str(time.time()))
            main.perform_backup(state, config)

        perform_backup()

        # state is saved
        assert_exists("/work/backup-name/backup-name.yml")

        # archive header is kept locally
        assert_exists("/work/backup-name/backup-name00000.zpaq")

        # archive header and data is uploaded
        remote_first_backup_base = "/remote/remote-bucket/backup-name/" + main.get_ip_address() + "/" + state["full_backups"][0]["name"]
        assert_full_backup_is_sane(state["full_backups"][0]["name"])

        # backup timestamp changed
        self.assertNotEqual(state["last_backup_timestamp"], 0)

        perform_backup()

        # second tome is added
        assert_exists(remote_first_backup_base + "/backup-name00002.zpaq")

        # run another 9 incremental backups
        for _ in range(9):
            perform_backup()

        # state contains one full backup and 10 incremental ones
        self.assertEqual(len(state["full_backups"]), 1)
        self.assertEqual(len(state["full_backups"][0]["incremental_backups"]), 11)  # total number of backups

        # full backup is present on disk
        assert_full_backup_is_sane(state["full_backups"][0]["name"])
        assert_exists(remote_first_backup_base + "/backup-name00011.zpaq")

        # rolling out another full backup
        perform_backup()

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

        # first full backup should be deleted by now
        self.assertEqual(len(state["full_backups"]), 3)

        # old first backup is gone, last three are present
        assert_full_backup_is_sane(state["full_backups"][0]["name"])
        assert_full_backup_is_sane(state["full_backups"][1]["name"])
        assert_full_backup_is_sane(state["full_backups"][2]["name"])

    def test_load_backup_configs(self):
        main.backup_config_dir = "/tmp/backuper-test-" + self.base + "/conf"
        os.makedirs(main.backup_config_dir)
        with open(main.backup_config_dir + "/a.yml", "w") as f:
            f.write("name: a\nremote: \"\"")
        with open(main.backup_config_dir + "/b.yml", "w") as f:
            f.write("name: b\nremote: \"\"")
        with open(main.backup_config_dir + "/c.yml", "w") as f:
            f.write("")

        configs = main.load_backup_configs()

        self.assertEqual(len(configs), 2)
        for c in configs:
            self.assertIn("config", c)
            self.assertIn("name", c["config"])
            self.assertIn("state", c)
            self.assertIn("last_backup_timestamp", c["state"])

    def test_restore(self):
        main.backup_config_dir = "/tmp/backuper-test-" + self.base + "/conf"
        os.makedirs(main.backup_config_dir)

        config = {
            "name": "backup-restore",
            "local": {
                "dirs": ["/tmp/backuper-test-" + self.base + "/source"],
                "exclude": [],
                "include_only": []
            },

            "remote": "remote-bucket",
            "keep_incremental_backup_count": 3,
            "keep_full_backup_count": 3,
            "backup_rate": "24h"
        }

        with open(main.backup_config_dir + "/conf.yml", "w") as f:
            f.write(yaml.dump(config))

        os.makedirs(config["local"]["dirs"][0])

        state = main.load_state("backup-name")

        def perform_backup(n):
            with open(config["local"]["dirs"][0] + "/" + str(n) + ".file", "w") as f:
                f.write(str(n))
            main.perform_backup(state, config)

        for n in range(1, 11):
            perform_backup(n)
        self.assertEqual(main.restore_names(), ["backup-restore"])

        self.assertEqual(main.restore_urls("backup-restor"), [])
        urls = main.restore_urls("backup-restore")
        self.assertEqual(len(urls), 10)

        base = "/tmp/backuper-test-" + self.base + "/source"

        def assert_content(n):
            self.assertEqual(sorted(os.listdir(base)), sorted(map(lambda a: str(a) + ".file", range(1, n + 1))))

        import subprocess
        subprocess.call(["bash", "-c", "rm " + base + "/*"])
        assert_content(0)

        for n in range(1, 11):
            subprocess.call(["bash", "-c", "rm " + base + "/*"])
            main.restore(urls[n - 1]["url"])
            assert_content(n)

        for n in range(10, 0, -1):
            subprocess.call(["bash", "-c", "rm " + base + "/*"])
            main.restore(urls[n - 1]["url"])
            assert_content(n)

    def test_backup_tasks(self):
        main.backup_tasks_dir = "/tmp/backuper-test-" + self.base + "/tasks"
        os.makedirs(main.backup_tasks_dir)

        def add(f, name):
            with open(main.backup_tasks_dir + "/" + f, "w") as ff:
                ff.write(name)

        def assert_file(f, content):
            p = main.backup_tasks_dir + "/" + f
            self.assertTrue(os.path.isfile(p), "File " + p + " does not exist")
            with open(p, "r") as ff:
                self.assertEqual(content, ff.read())

        add("task-file1", "task1")
        add("task-file2", "task2")
        add("task-file3", "task3")

        self.assertEqual(main.backup_tasks(), [
            {"file": "task-file1", "name": "task1"},
            {"file": "task-file2", "name": "task2"},
            {"file": "task-file3", "name": "task3"}
        ])

        main.commit_backup_task("task-file1", "backup-url", "")
        self.assertEqual(main.backup_tasks(), [
            {"file": "task-file2", "name": "task2"},
            {"file": "task-file3", "name": "task3"}
        ])
        assert_file("task-file1-ok", "backup-url")

        main.commit_backup_task("task-file2", "", "my-error")
        self.assertEqual(main.backup_tasks(), [
            {"file": "task-file3", "name": "task3"}
        ])
        assert_file("task-file2-error", "my-error")


if __name__ == '__main__':
    unittest.main()

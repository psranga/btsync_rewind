import unittest
import os
import tempfile
import time
import shutil

import core


class TestBase:
    """Routines common to all testcases like creating the root dir."""

    def make_root_dir(self):
        """Creates self.root_dir if set, or sets a unique dir and sets
        self.root_dir."""
        if not hasattr(self, 'root_dir'):
            self.root_dir = tempfile.mkdtemp(dir='/dev/shm',
                                             prefix='btsync_rewind_test-')
        if not os.path.exists(self.root_dir):
            os.makedirs(self.root_dir)
        if not os.path.exists(self.archive_dir()):
            os.makedirs(self.archive_dir())

    def delete_root_dir(self):
        shutil.rmtree(self.root_dir)

    def archive_dir(self):
        return os.path.join(self.root_dir, '.sync/Archive')

    def resolve_to_rel_path(self, timestamp, rel_path):
        """Converts to absolute path to relative path rooted at self.root_dir.
        Make test comparisons easier."""
        ts_and_abs_path = core.resolve_file(timestamp, rel_path, self.root_dir)
        if ts_and_abs_path != None:
            return (ts_and_abs_path[0], os.path.relpath(ts_and_abs_path[1],
                                                        self.root_dir))
        else:
            return None

    def create_file(self, timestamp, rel_path, size=0, contents=None):
        """Creates a file at self.root_dir/rel_path. If 'contents' is not None,
        that becomes the file contents. Otherwise the contents is the letter x
        repeated 'size' times."""

        assert not os.path.isabs(rel_path)
        path = os.path.join(self.root_dir, rel_path)
        dirname = os.path.dirname(path)
        if not os.path.exists(dirname):
            os.makedirs(dirname)

        fh = open(path, 'w')
        if contents:
            fh.write(contents)
        else:
            fh.write('x' * size)
        fh.close()

        # set timestamp on file. set fake atime. we don't use it.
        os.utime(path, (0, timestamp))

        # set timestamp on containing dir. set fake atime. we don't use it.
        os.utime(dirname, (0, timestamp))

        return path


class TestResolveFileSimple(TestBase, unittest.TestCase):
    """Tests whether we can figure out which version of a file should be
    used at different points in time. Tests the simple cases where a path
    does not change from file to dir or vice versa."""

    def setUp(self):
        self.make_root_dir()

    def tearDown(self):
        self.delete_root_dir()

    def test_live_and_two_versions(self,
                                   live_path='f1',
                                   last_backup_path='.sync/Archive/f1.1',
                                   second_last_backup_path='.sync/Archive/f1'):

        # Aliases for readability.
        test_path = live_path
        t0 = 100000

        # File at top-level with one live version and two previous versions.
        self.create_file(t0 - 100, second_last_backup_path)
        self.create_file(t0, last_backup_path)
        self.create_file(t0, live_path)

        # live version for all times after live version's creation time.
        ts_and_path = self.resolve_to_rel_path(t0 + 1, test_path)
        self.assertEqual((t0, live_path), ts_and_path)

        # Should pick live version even if the last backup version and live
        # version were created at the same time. E.g., tiny files,
        # "transactional" replacement etc.
        ts_and_path = self.resolve_to_rel_path(t0, test_path)
        self.assertEqual((t0, live_path), ts_and_path)

        # Last backup version immediately before 'now'.
        ts_and_path = self.resolve_to_rel_path(t0 - 1, test_path)
        self.assertEqual((t0, last_backup_path), ts_and_path)

        # Last backup version *at* penultimate backup version creation time.
        # Same reason as to why live should be picked over backup, even if both
        # have the same time.
        ts_and_path = self.resolve_to_rel_path(t0 - 100, test_path)
        self.assertEqual((t0, last_backup_path), ts_and_path)

        # Last backup version for just before penultimate backup version
        # creation time.
        ts_and_path = self.resolve_to_rel_path(t0 - 101, test_path)
        self.assertEqual((t0 - 100, second_last_backup_path), ts_and_path)

        # Last backup version for all times before penultimate backup version
        # creation time.
        ts_and_path = self.resolve_to_rel_path(t0 - 200, test_path)
        self.assertEqual((t0 - 100, second_last_backup_path), ts_and_path)

    def test_live_and_two_versions_subdir(self):
        return self.test_live_and_two_versions(
            'dir1/f3', '.sync/Archive/dir1/f3.1', '.sync/Archive/dir1/f3')

    def test_no_live_two_versions(self,
                                  live_path='f2',
                                  last_backup_path='.sync/Archive/f2.1',
                                  second_last_backup_path='.sync/Archive/f2'):

        # Aliases for readability.
        test_path = live_path
        t0 = 100000

        # Deleted file in top level with two previous versions.
        self.create_file(t0 - 1000, second_last_backup_path)
        self.create_file(t0 - 800, last_backup_path)

        # File shouldn't exist "in the future".
        ts_and_path = self.resolve_to_rel_path(t0 + 1, test_path)
        self.assertEqual(None, ts_and_path)

        # File shouldn't exist "now". Tests that backup file timestamp of "now"
        # is interpreted correctly.
        ts_and_path = self.resolve_to_rel_path(t0, test_path)
        self.assertEqual(None, ts_and_path)

        # File shouldn't exist until the last backup version was created.
        ts_and_path = self.resolve_to_rel_path(t0 - 1, test_path)
        self.assertEqual(None, ts_and_path)

        # File should exist before the last backup version was created.
        ts_and_path = self.resolve_to_rel_path(t0 - 900, test_path)
        self.assertEqual((t0 - 800, last_backup_path), ts_and_path)

    def test_no_live_two_versions_subdir(self):
        return self.test_no_live_two_versions(
            'dir2/f4', '.sync/Archive/dir2/f4.1', '.sync/Archive/dir2/f4')


class TestReadDirSimple(TestBase, unittest.TestCase):
    """Tests listing directory contents. Tests the simple cases where a path
    does not change from file to dir or vice versa."""

    def setUp(self):
        self.make_root_dir()

    def tearDown(self):
        #self.delete_root_dir()
        pass

    def test_live_and_two_versions(self,
                                   live_path='f1',
                                   last_backup_path='.sync/Archive/f1.1',
                                   second_last_backup_path='.sync/Archive/f1'):

        # Aliases for readability.
        rel_path = live_path
        rel_dir = os.path.dirname(rel_path)
        basename = os.path.basename(rel_path)
        t0 = 100000

        # File at top-level with one live version and two previous versions.
        self.create_file(t0 - 100, second_last_backup_path)
        self.create_file(t0, last_backup_path)
        self.create_file(t0, live_path)

        # file should appear at the root dir at a times after "now" - 100.
        for test_timestamp in [t0 + 1, t0, t0 - 1, t0 - 100]:
            dirents = core.readdir(test_timestamp, rel_dir, self.root_dir)
            self.assertEqual(['.', '..', basename], sorted(dirents))

    def test_no_live_two_versions(self,
                                  live_path='f2',
                                  last_backup_path='.sync/Archive/f2.1',
                                  second_last_backup_path='.sync/Archive/f2'):

        # Aliases for readability.
        rel_path = live_path
        rel_dir = os.path.dirname(rel_path)
        basename = os.path.basename(rel_path)
        t0 = 100000

        # File at top-level two previous versions.
        self.create_file(t0 - 100, second_last_backup_path)
        self.create_file(t0, last_backup_path)

        # file should not appear at the root dir at t0 and later.
        for test_timestamp in [t0, t0 + 1, t0 + 100]:
            dirents = core.readdir(test_timestamp, rel_dir, self.root_dir)
            self.assertEqual(['.', '..'], sorted(dirents))

        # file should appear at the root dir at a times earlier than t0.
        for test_timestamp in [t0 - 1, t0 - 100, t0 - 200]:
            dirents = core.readdir(test_timestamp, rel_dir, self.root_dir)
            self.assertEqual(['.', '..', basename], sorted(dirents))

    def test_no_live_two_versions_subdir(self):
        return self.test_no_live_two_versions(
            'dir2/f4', '.sync/Archive/dir2/f4.1', '.sync/Archive/dir2/f4')

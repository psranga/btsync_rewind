#!/usr/bin/env python
"""This is the file you should execute to mount a Bittorrent Sync (BTSync)
directory as a rewindable file system.

Example:

    python btsync_rewind.py ~/btsync-data/photos /mnt

Now BTSync Rewind will, on the fly, show snapshots of your archive at
various points in time at directory /mnt/<timestamp>.

The timestamp for which you want the snapshot is indicated by using a
number as the first subdirectory of /mnt (e.g., /mnt/1451059200/file.txt).
Don't worry, you should hardly ever have to type in the mystery number
yourself.

The number is the number of seconds between Unix's "epoch" and the
point if time for which we want the snapshot. The Unix utility 'date' is
a very powerful tool to convert human-friendly date strings to the
number needed by BTSync Rewind.

Example:

    ls /mnt/1451059200

can be rewritten with just a little more typing as:

    ls /mnt/$(date --date="2015-12-25 8:00 PST" +%s)

To view the version of 'file.txt' that existed on July 1, 2015:

    less /mnt/$(date --date="2015-07-01 PST" +%s)/file.txt

"""

import os
import sys
import errno
import logging

from fusepy.fuse import FUSE, FuseOSError, Operations

import core


class BTSyncRewinder(Operations):
    """A thin wrapper to adapt the functions in core.py to the fusepy's API."""

    # The most important methods are open, readdir, and getattr.

    def __init__(self, root_dir):
        self.root_dir = root_dir

    # Supported file operations
    # -------------------------

    def open(self, virt_abs_path, flags):
        if (flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT |
                     os.O_TRUNC)) != 0:
            raise FuseOSError(errno.EROFS)
        timestamp, rel_path = core.get_timestamp_and_rel_path(virt_abs_path)
        file_timestamp, real_abs_path = core.resolve_file(timestamp, rel_path,
                                                          self.root_dir)
        if real_abs_path == None:
            raise FuseOSError(errorno.ENOENT)
        return os.open(real_abs_path, flags)

    def read(self, virt_abs_path, length, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, length)

    def readdir(self, virt_abs_path, fh):
        timestamp, rel_path = core.get_timestamp_and_rel_path(virt_abs_path)
        return core.readdir(timestamp, rel_path, self.root_dir)

    def getattr(self, virt_abs_path, fh=None):
        timestamp, rel_path = core.get_timestamp_and_rel_path(virt_abs_path)
        if rel_path != '':
            file_timestamp, real_abs_path = core.resolve_file(
                timestamp, rel_path, self.root_dir)
        else:
            file_timestamp, real_abs_path = (0, self.root_dir)

        if real_abs_path == None:
            # Return fake info if not found. Optimistically assume this call is
            # for a dir, not a file and return fake info. TODO: fix this.
            real_abs_path = self.root_dir
        st = os.lstat(real_abs_path)
        return dict((key, getattr(st, key))
                    for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode',
                                'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

    def access(self, virt_abs_path, mode):
        # Optimistically say all files are accessible.
        return True

    def flush(self, virt_abs_path, fh):
        return os.fsync(fh)

    def release(self, virt_abs_path, fh):
        return os.close(fh)

    def fsync(self, virt_abs_path, fdatasync, fh):
        return self.flush(virt_abs_path, fh)

    # Unsupported file operations
    # ---------------------------

    def readlink(self, virt_abs_path):
        # BTSync Rewind doesn't support symlinks.
        raise FuseOSError(errno.EACCES)

    def statfs(self, virt_abs_path):
        # Unimplemented API. Information about the containing filesystem.
        raise FuseOSError(errno.EACCES)

    def chmod(self, virt_abs_path, mode):
        raise FuseOSError(errno.EROFS)

    def chown(self, virt_abs_path, uid, gid):
        raise FuseOSError(errno.EROFS)

    def mknod(self, virt_abs_path, mode, dev):
        raise FuseOSError(errno.EROFS)

    def rmdir(self, virt_abs_path):
        raise FuseOSError(errno.EROFS)

    def mkdir(self, virt_abs_path, mode):
        raise FuseOSError(errno.EROFS)

    def unlink(self, virt_abs_path):
        raise FuseOSError(errno.EROFS)

    def symlink(self, name, target):
        raise FuseOSError(errno.EROFS)

    def rename(self, old, new):
        raise FuseOSError(errno.EROFS)

    def link(self, target, name):
        raise FuseOSError(errno.EROFS)

    def utimens(self, virt_abs_path, times=None):
        raise FuseOSError(errno.EACCES)

    def create(self, virt_abs_path, mode, fi=None):
        raise FuseOSError(errno.EROFS)

    def write(self, virt_abs_path, buf, offset, fh):
        raise FuseOSError(errno.EROFS)

    def truncate(self, virt_abs_path, length, fh=None):
        raise FuseOSError(errno.EROFS)


def main(mountpoint, root):
    FUSE(BTSyncRewinder(root), mountpoint, nothreads=True, foreground=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[2], sys.argv[1])

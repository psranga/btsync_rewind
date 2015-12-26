#!/usr/bin/env python

import os
import re
import errno
from collections import defaultdict
from fusepy.fuse import FuseOSError
import logging


def get_timestamp_and_rel_path(fuse_path):
    """Parse the incoming path from FUSE of the form /<timestamp> or
    /<timestamp>/file.txt or /<timestamp>/dir/file.txt and return the
    timestamp and a relative path (no leading slash) as tuple.

    The first element of the tuple is the int timestamp and the second
    element is the relative path. An error result is indicated by setting
    the first element to -1.

    If the timestamp is a floating point number, it will be truncated to
    an int.

    Returns error if fuse_path has a trailing slash, doesn't contain
    a valid timestamp, or is an empty string.

    >>> get_timestamp_and_rel_path('')
    (-1, '')

    >>> get_timestamp_and_rel_path('/')
    (-1, '')

    >>> get_timestamp_and_rel_path('foo')
    (-1, '')

    >>> get_timestamp_and_rel_path('foo/')
    (-1, '')

    >>> get_timestamp_and_rel_path('/2000')
    (2000, '')

    >>> get_timestamp_and_rel_path('/2000/file.txt')
    (2000, 'file.txt')

    >>> get_timestamp_and_rel_path('/2000/dir/file.txt')
    (2000, 'dir/file.txt')

    >>> get_timestamp_and_rel_path('/2000.20/dir/file.txt')
    (2000, 'dir/file.txt')

    >>> get_timestamp_and_rel_path('/-2000.20/dir/file.txt')
    (-1, '')

    >>> get_timestamp_and_rel_path('/a/dir/file.txt')
    (-1, '')

    >>> get_timestamp_and_rel_path('/a200/dir/file.txt')
    (-1, '')

    >>> get_timestamp_and_rel_path('/200a/dir/file.txt')
    (-1, '')

    >>> get_timestamp_and_rel_path('/200/dir/')
    (-1, '')

    >>> get_timestamp_and_rel_path('//file.txt')
    (-1, '')

    >>> get_timestamp_and_rel_path('/120//file.txt')
    (-1, '')
    """
    error_result = (-1, '')

    if not fuse_path.startswith('/') or fuse_path.endswith('/'):
        return error_result

    second_slash_location = fuse_path.find('/', 1)

    if second_slash_location == -1:
        timestamp_str = fuse_path[1:]
        rel_path = ''
    else:
        timestamp_str = fuse_path[1:second_slash_location]
        rel_path = fuse_path[second_slash_location + 1:]

    try:
        timestamp = int(float(timestamp_str))
    except ValueError:
        return error_result

    if timestamp < 0:
        return error_result

    if rel_path.startswith('/'):
        return error_result

    return (timestamp, rel_path)


def live_file_creation_time(real_abs_path):
    assert not os.path.isdir(real_abs_path)
    st = os.lstat(real_abs_path)
    # TODO: Add option to allow ctime here.
    crtime = int(getattr(st, 'st_mtime'))
    return crtime


def archive_file_creation_time(real_abs_path):
    assert not os.path.isdir(real_abs_path)
    st = os.lstat(real_abs_path)
    # mtime because a dir that becomes a file get a ctime newer than its mtime.
    # in such cases sorting by ctime produces states in the wrong order.
    crtime = int(getattr(st, 'st_mtime'))
    return crtime


def resolve_file(timestamp, rel_path, root_dir):
    if rel_path.startswith('/') or rel_path.endswith('/') or rel_path == '':
        raise FuseOSError(errno.EINVAL)

    if not os.path.exists(root_dir):
        raise FuseOSError(errno.ENOENT)

    if not os.path.isdir(root_dir):
        raise FuseOSError(errno.ENOTDIR)

    live_path = os.path.join(root_dir, rel_path)
    live_crtime = -1
    if os.path.isfile(live_path):
        live_crtime = live_file_creation_time(live_path)
        # By definition, the live dir contains the newest state of a file.
        # If the live file was created at 'live_crtime', the no further
        # changes can have occurred to the file since then. Hence the file
        # *must* must exist at all times after 'live_crtime' also.
        if timestamp >= live_crtime:
            return (live_crtime, live_path)

    # We need a state before the last state of the file. Look in the archive
    # for previous states. The creation time of a file 'f' there tells us the
    # *last* time until which 'rel_path' contained the bytes stored in 'f'.
    dirname = os.path.dirname(rel_path)
    basename = os.path.basename(rel_path)
    re_previous_version_filenames = re.compile('^' + basename + '(\.[0-9]+)?$')

    archive_path = os.path.join(root_dir, '.sync/Archive', dirname)
    ts_and_paths = []
    for filename in os.listdir(archive_path):
        #print 'filename:', filename
        if re_previous_version_filenames.match(filename):
            #print 'filename:', filename, 'matches'
            full_path = os.path.join(archive_path, filename)
            if os.path.isfile(full_path):
                crtime = archive_file_creation_time(full_path)
                ts_and_paths.append((crtime, full_path))

    # sort the previous states with most recent last.
    ts_and_paths.sort(key=lambda ts_and_path: ts_and_path[0])

    # Erase any latency between beginning of last state (live) and end of
    # penultimate one.  Conceptually, they occur simultaneously, and any delays
    # are system artifacts that can be ignored.
    if (live_crtime != -1) and len(ts_and_paths) > 0:
        ts_and_paths[-1] = (live_crtime, ts_and_paths[-1][1])

    for last_valid_timestamp, path in ts_and_paths:
        if timestamp < last_valid_timestamp:
            return (last_valid_timestamp, path)

    return None


def readdir(timestamp, rel_path, root_dir):
    """List files from the live dir and the archive dir. Map each file in the
    archive dir to its original name. For each unique file, decide whether it
    was present at the required timestamp.

    Optimistically say that a directory present at any instant was present at
    all past and future instants too. This will result in weird output like
    same filename occurring twice if a filename starts as a file and then
    becomes a dir etc.  TODO: Resolve directories better."""
    live_path = os.path.join(root_dir, rel_path)
    archive_path = os.path.join(root_dir, '.sync/Archive', rel_path)

    # decoded filename to live creation times.
    live_crtimes = defaultdict(lambda: -1)

    files_to_be_added = set()
    dirs_to_be_added = set()

    if os.path.isdir(live_path):
        for filename in os.listdir(live_path):
            full_path = os.path.join(live_path, filename)
            if os.path.isfile(full_path):
                live_crtime = live_file_creation_time(full_path)
                live_crtimes[filename] = live_crtime
                if timestamp >= live_crtime:
                    files_to_be_added.add(filename)
            elif (rel_path != '') or (filename != '.sync'):
                # Don't BTsync archive dir at top level.
                dirs_to_be_added.add(filename)

    # decoded filename to creation times of each previous version.
    archive_crtimes = defaultdict(list)

    if os.path.isdir(archive_path):
        for filename in os.listdir(archive_path):
            decoded_filename = re.sub('\.[0-9]+$', '', filename)
            full_path = os.path.join(archive_path, filename)
            if os.path.isfile(full_path):
                archive_crtime = archive_file_creation_time(full_path)
                archive_crtimes[decoded_filename].append((archive_crtime,
                                                          full_path))
            else:
                dirs_to_be_added.add(decoded_filename)

    for decoded_filename, ts_and_paths in archive_crtimes.iteritems():
        # sort the previous states with most recent at index 0.
        ts_and_paths.sort(reverse=True, key=lambda ts_and_path: ts_and_path[0])

        # Erase any latency between beginning of last state (live) and end of
        # penultimate one.
        if live_crtimes[decoded_filename] != -1:
            ts_and_paths[0] = (live_crtimes[decoded_filename],
                               ts_and_paths[0][1])

        for last_valid_timestamp, path in ts_and_paths:
            if timestamp < last_valid_timestamp:
                files_to_be_added.add(decoded_filename)

    return ['.', '..'] + list(files_to_be_added) + list(dirs_to_be_added)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import doctest
    doctest.testmod()

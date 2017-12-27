import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Tuple

import m3u8

from .utils import chdir, generate_m3u8, logger


# Returns None if the merge succeeds, or the basename of the first bad
# segment if non-monotonous DTS is detected.
def attempt_merge(m3u8_file: pathlib.Path, output: pathlib.Path) -> str:
    logger.info(f'attempting to merge {m3u8_file} into {output}')
    regular_pattern = re.compile(r"Opening '(?P<path>.*\.ts)' for reading")
    error_pattern = re.compile('Non-monotonous DTS in output stream')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'info',
               '-f', 'hls', '-i', str(m3u8_file), '-c', 'copy', '-y', str(output)]
    p = subprocess.Popen(command, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         universal_newlines=True, bufsize=1,
                         encoding='utf-8', errors='backslashreplace')
    last_read_segment = None
    for line in p.stderr:
        sys.stderr.write(line)
        sys.stderr.flush()
        m = regular_pattern.search(line)
        if m:
            last_read_segment = os.path.basename(m['path'])
            continue
        if error_pattern.search(line):
            assert last_read_segment
            logger.warning(f'DTS jump detected in {last_read_segment}')
            return last_read_segment
    returncode = p.wait()
    if returncode != 0:
        logger.error(f'ffmpeg failed with exit status {returncode}')
        raise RuntimeError('unknown error occurred during merging')
    else:
        return None


# Split the source m3u8 file into two destination m3u8 files, at
# split_point, which is the URL of a segment. split_point belongs to the
# second file after splitting.
#
# It's safe to overwrite the source file with one of the destinations.
def split_m3u8(source: pathlib.Path, destinations: Tuple[pathlib.Path, pathlib.Path],
               split_point: str) -> None:
    logger.info(f'splitting {source} at {split_point}')
    m3u8_obj = m3u8.load(source.as_posix())
    target_duration = m3u8_obj.target_duration
    part1_segments = []
    part2_segments = []
    reached_split_point = False
    for segment in m3u8_obj.segments:
        if segment.uri == split_point:
            reached_split_point = True
        tup = (segment.uri, segment.duration)
        if reached_split_point:
            part2_segments.append(tup)
        else:
            part1_segments.append(tup)
    dest1, dest2 = destinations
    with open(dest1, 'w') as fp:
        fp.write(generate_m3u8(target_duration, part1_segments))
    logger.info(f'wrote {dest1}')
    with open(dest2, 'w') as fp:
        fp.write(generate_m3u8(target_duration, part2_segments))
    logger.info(f'wrote {dest2}')


# m3u8_file should not be named '1.m3u8'; in fact, avoid naming it
# '<number>.m3u8', or it may be overwritten in the process.
def incremental_merge(m3u8_file: pathlib.Path, output: pathlib.Path):
    directory = m3u8_file.parent
    playlist_index = 1
    playlist = directory / f'{playlist_index}.m3u8'
    shutil.copyfile(m3u8_file, playlist)

    intermediate_dir = directory / 'intermediate'
    intermediate_dir.mkdir(exist_ok=True)

    while True:
        merge_dest = intermediate_dir / f'{playlist_index}.ts'
        split_point = attempt_merge(playlist, merge_dest)
        if not split_point:
            break
        playlist_index += 1
        next_playlist = directory / f'{playlist_index}.m3u8'
        split_m3u8(playlist, (playlist, next_playlist), split_point)
        split_point = attempt_merge(playlist, merge_dest)
        playlist = next_playlist

    with chdir(intermediate_dir):
        with open('concat.txt', 'w') as fp:
            for index in range(1, playlist_index + 1):
                print(f'file {index}.ts', file=fp)

        command = ['ffmpeg', '-hide_banner', '-loglevel', 'info',
                   '-f', 'concat', '-i', 'concat.txt',
                   '-c', 'copy', '-movflags', 'faststart', '-y', str(output)]
        try:
            logger.info('merging intermediate products...')
            subprocess.run(command, stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            logger.error(f'ffmpeg failed with exit status {e.returncode}')
            raise RuntimeError('unknown error occurred during merging')
        else:
            logger.info(f'merged into {output}')

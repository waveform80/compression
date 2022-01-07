#!/usr/bin/python3

import io
import sys
import shlex
import sqlite3
import argparse
import tempfile
import datetime as dt
import subprocess as sp
from select import select, PIPE_BUF
from time import sleep


create_sql = """
PRAGMA foreign_keys = 1;

CREATE TABLE tests (
    compressor TEXT NOT NULL,
    options    TEXT NOT NULL,
    level      TEXT NOT NULL,

    CONSTRAINT options_pk PRIMARY KEY (compressor, options, level)
);

CREATE VIEW compressors AS
    SELECT DISTINCT compressor FROM tests;

CREATE VIEW options AS
    SELECT DISTINCT compressor, options FROM tests;

CREATE TABLE results (
    machine          TEXT         NOT NULL,
    arch             TEXT         NOT NULL,
    compressor       TEXT         NOT NULL,
    options          TEXT         NOT NULL,
    level            TEXT         NOT NULL,
    succeeded        INTEGER      NOT NULL DEFAULT 0,
    comp_duration    NUMERIC(8,2) NOT NULL,
    comp_max_mem     INTEGER      NOT NULL,
    decomp_duration  NUMERIC(8,2) NOT NULL,
    decomp_max_mem   INTEGER      NOT NULL,
    input_size       INTEGER      NOT NULL,
    output_size      INTEGER      NOT NULL,

    CONSTRAINT compression_pk
        PRIMARY KEY (machine, arch, compressor, options, level),
    CONSTRAINT compression_options_fk
        FOREIGN KEY (compressor, options, level)
        REFERENCES tests (compressor, options, level) ON DELETE CASCADE,
    CONSTRAINT compression_valid_ck CHECK (
        succeeded IN (0, 1)
        AND comp_duration >= 0.0
        AND decomp_duration >= 0.0
        AND comp_max_mem >= 0
        AND decomp_max_mem >= 0
        AND input_size >= 0
        AND output_size >= 0
    )
);

CREATE INDEX results_options ON results(compressor, options, level);
"""

insert_sql = "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

populate_sql = """
WITH RECURSIVE
c(compressor, options, min_level, max_level) AS (
    VALUES
        ('zstd',  '',    1, 19),
        ('zstd',  '-T0', 1, 19),
        ('gzip',  '',    1, 9),
        ('lz4',   '',    1, 12),
        ('xz',    '',    0, 9),
        ('xz',    '-e',  0, 9),
        ('bzip2', '-s',  1, 9),
        ('bzip2', '',    1, 9),
        ('lzip',  '',    0, 9)
),
t(level, option) AS (
    VALUES (0, '-0')
    UNION ALL
    SELECT level + 1, '-' || CAST(level + 1 AS TEXT)
    FROM t
    WHERE level <= 20
)
INSERT OR IGNORE INTO tests
    SELECT c.compressor, c.options, t.option
    FROM c JOIN t ON t.level BETWEEN c.min_level AND c.max_level

INSERT INTO tests VALUES ('cat', '', '');
"""

query_sql = """
WITH all_machines(machine, arch) AS (
    VALUES (?, ?)
),
all_runs AS (
    SELECT machine, arch, compressor, options, level
    FROM all_machines CROSS JOIN tests
)
SELECT machine, arch, compressor, options, level FROM all_runs
EXCEPT
SELECT machine, arch, compressor, options, level FROM results
"""


def get_db(filename):
    conn = sqlite3.connect(filename)

    with conn:
        try:
            conn.executescript(create_sql)
        except sqlite3.OperationalError as exc:
            # Tables already exist; don't bother trying to populate
            pass
    with conn:
        conn.executescript(populate_sql)
    conn.row_factory = sqlite3.Row
    return conn


def parse_time_mem(s):
    duration, mem, *_ = s.split()
    duration_m, duration = duration.split(':', 1)
    duration_s, duration_f = duration.split('.', 1)
    elapsed = dt.timedelta(
        minutes=int(duration_m),
        seconds=int(duration_s),
        microseconds=int(duration_f) * 10 ** (6 - len(duration_f)))
    return elapsed.total_seconds(), int(mem) * 1024


def run_test(compressor, options, level, filename):
    with io.open(filename, 'rb') as input_stream, \
            tempfile.TemporaryFile() as output_stream:
        if compressor == 'cat':
            # Make an exception if it's just cat as no "compressor" would
            # actually be run in this case anyway
            input_stream.seek(0, io.SEEK_END)
            return (0.0, 0, 0.0, 0, input_stream.tell(), input_stream.tell())
        cmdline = ['time', '-f', '%E %M', compressor, level]
        cmdline += shlex.split(options)
        print(shlex.join(cmdline), file=sys.stderr)
        result = sp.run(
            cmdline, stdin=input_stream, stdout=output_stream, stderr=sp.PIPE,
            check=True, timeout=300)
        comp_time, comp_mem = parse_time_mem(result.stderr.decode('ascii'))
        input_size = input_stream.tell()
        output_size = output_stream.tell()
        output_stream.seek(0)
        cmdline = ['time', '-f', '%E %M', compressor, '-d']
        print(shlex.join(cmdline), file=sys.stderr)
        result = sp.run(
            cmdline, stdin=output_stream, stdout=sp.DEVNULL, stderr=sp.PIPE,
            check=True, timeout=300)
        decomp_time, decomp_mem = parse_time_mem(result.stderr.decode('ascii'))
        return (
            comp_time, comp_mem,
            decomp_time, decomp_mem,
            input_size, output_size)


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-m', '--machine',
        help="A (brief) description of this machine, e.g. 'Pi Zero 2'")
    parser.add_argument(
        '-d', '--database', default='compression.db',
        help="The name of the database to populate (default: %(default)s)")
    parser.add_argument(
        'data',
        help="The filename of the (uncompressed) data to use")

    if args is None:
        args = sys.argv[1:]
    config = parser.parse_args(args)

    if not config.machine:
        print(f'You must specify a --machine type', file=sys.stderr)
        return 1
    config.arch = sp.run(['dpkg', '--print-architecture'], check=True,
                         capture_output=True, text=True).stdout.strip()

    db = get_db(config.database)
    # Check all the compressors are installed before wasting lots of time
    for row in db.execute("SELECT compressor FROM compressors"):
        try:
            sp.run([row['compressor']], stdin=sp.DEVNULL, stdout=sp.DEVNULL,
                   check=True)
        except sp.CalledProcessError:
            print(f'Please install missing {compressor}', file=sys.stderr)
            return 1

    for row in db.execute(query_sql, (config.machine, config.arch)):
        key = (config.machine, config.arch,
               row['compressor'], row['options'], row['level'])
        try:
            attrs = run_test(row['compressor'], row['options'], row['level'],
                             config.data)
        except RuntimeError:
            results = key + (False, 0.0, 0, 0.0, 0, 0, 0)
        else:
            results = key + (True,) + attrs
        with db:
            db.execute(insert_sql, results)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/python3

import io
import sys
import shlex
import sqlite3
import argparse
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
    machine      TEXT         NOT NULL,
    arch         TEXT         NOT NULL,
    compressor   TEXT         NOT NULL,
    options      TEXT         NOT NULL,
    level        TEXT         NOT NULL,
    succeeded    INTEGER      NOT NULL DEFAULT 0,
    elapsed      NUMERIC(8,2) NOT NULL,
    max_resident INTEGER      NOT NULL,
    ratio        NUMERIC(8,7) NOT NULL,

    CONSTRAINT compression_pk
        PRIMARY KEY (machine, arch, compressor, options, level),
    CONSTRAINT compression_options_fk
        FOREIGN KEY (compressor, options, level)
        REFERENCES tests (compressor, options, level) ON DELETE CASCADE,
    CONSTRAINT compression_succeeded_ck CHECK (succeeded IN (0, 1)),
    CONSTRAINT compression_elapsed_ck CHECK (elapsed >= 0.0),
    CONSTRAINT compression_resident_ck CHECK (max_resident >= 0),
    CONSTRAINT compression_ratio_ck CHECK (ratio >= 0)
);

CREATE INDEX results_options ON results(compressor, options, level);
"""

populate_sql = """
WITH RECURSIVE
c(compressor, options, min_level, max_level) AS (
    VALUES
        ('zstd', '',    1, 19),
        ('zstd', '-T0', 1, 19),
        ('gzip', '',    1, 9),
        ('lz4',  '',    1, 9),
        ('xz',   '',    0, 9),
        ('xz',   '-e',  0, 9)
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

insert_sql = "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"


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


def run_test(compressor, options, level, filename):
    with io.open(filename, 'rb') as data:
        input_size = data.seek(0, io.SEEK_END)
        data.seek(0)
        cmdline = ['time', '-f', '%E %M', compressor, level]
        cmdline += shlex.split(options)
        print(shlex.join(cmdline), file=sys.stderr)
        proc = sp.Popen(
            cmdline, bufsize=0,
            stdin=data, stdout=sp.PIPE, stderr=sp.PIPE)
        output_size = 0
        while True:
            buf = proc.stdout.read(PIPE_BUF)
            if not buf:
                break
            output_size += len(buf)
        output = proc.stderr.read().decode('ascii')
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError('Compression failed')
        duration, max_res, *_ = output.split()
        duration_m, duration = duration.split(':', 1)
        duration_s, duration_f = duration.split('.', 1)
        elapsed = dt.timedelta(
            minutes=int(duration_m),
            seconds=int(duration_s),
            microseconds=int(duration_f) * 10 ** (6 - len(duration_f)))
        return elapsed.total_seconds(), output_size / input_size, int(max_res)


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
        try:
            elapsed, ratio, max_resident = run_test(
                row['compressor'], row['options'], row['level'], config.data)
        except RuntimeError:
            results = (
                config.machine, config.arch,
                row['compressor'], row['options'], row['level'],
                False, 0.0, 0, 0)
        else:
            results = (
                config.machine, config.arch,
                row['compressor'], row['options'], row['level'],
                True, elapsed, max_resident, ratio)
        with db:
            db.execute(insert_sql, results)


if __name__ == '__main__':
    sys.exit(main())

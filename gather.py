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

CREATE TABLE compressors (
    compressor TEXT NOT NULL,

    CONSTRAINT compressors_pk PRIMARY KEY (compressor)
);

CREATE TABLE options (
    compressor TEXT NOT NULL,
    options    TEXT NOT NULL,

    CONSTRAINT options_pk PRIMARY KEY (compressor, options),
    CONSTRAINT options_compressor_fk FOREIGN KEY (compressor)
        REFERENCES compressors (compressor) ON DELETE CASCADE
);

CREATE TABLE results (
    machine      TEXT         NOT NULL,
    arch         TEXT         NOT NULL,
    compressor   TEXT         NOT NULL,
    options      TEXT         NOT NULL,
    succeeded    INTEGER      NOT NULL DEFAULT 0,
    elapsed      NUMERIC(8,2) NOT NULL,
    max_resident INTEGER      NOT NULL,
    ratio        NUMERIC(8,7) NOT NULL,

    CONSTRAINT compression_pk PRIMARY KEY (machine, arch, compressor, options),
    CONSTRAINT compression_options_fk FOREIGN KEY (compressor, options)
        REFERENCES options (compressor, options) ON DELETE CASCADE,
    CONSTRAINT compression_succeeded_ck CHECK (succeeded IN (0, 1)),
    CONSTRAINT compression_elapsed_ck CHECK (elapsed >= 0.0),
    CONSTRAINT compression_resident_ck CHECK (max_resident >= 0),
    CONSTRAINT compression_ratio_ck CHECK (ratio >= 0)
);

CREATE INDEX results_options ON results(compressor, options);
"""

populate_sql = """
INSERT OR IGNORE INTO compressors VALUES
    ('zstd'),
    ('gzip'),
    ('lz4'),
    ('xz');

WITH RECURSIVE t(level, options) AS (
    VALUES (0, '-0')
    UNION ALL
    SELECT level + 1, '-' || CAST(level + 1 AS TEXT)
    FROM t
    WHERE level <= 20
)
INSERT OR IGNORE INTO options
    SELECT 'zstd', options FROM t WHERE level BETWEEN 1 AND 19
    UNION ALL
    SELECT 'zstd', '-T0 ' || options FROM t WHERE level BETWEEN 1 AND 19
    UNION ALL
    SELECT 'gzip', options FROM t WHERE level BETWEEN 1 AND 9
    UNION ALL
    SELECT 'lz4', options FROM t WHERE level BETWEEN 1 AND 9
    UNION ALL
    SELECT 'xz', options FROM t WHERE level BETWEEN 0 AND 9
    UNION ALL
    SELECT 'xz', '-e ' || options FROM t WHERE level BETWEEN 0 AND 9;
"""

query_sql = """
WITH all_machines(machine, arch) AS (
    VALUES (?, ?)
),
all_runs AS (
    SELECT machine, arch, compressor, options
    FROM all_machines CROSS JOIN options
)
SELECT machine, arch, compressor, options FROM all_runs
EXCEPT
SELECT machine, arch, compressor, options FROM results
"""

insert_sql = "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?)"


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


def run_test(compressor, options, filename):
    with io.open(filename, 'rb') as data:
        input_size = data.seek(0, io.SEEK_END)
        data.seek(0)
        cmdline = ['time', '-f', '%E %M', compressor] + shlex.split(options)
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
        print(f'Testing {row["compressor"]} {row["options"]}', file=sys.stderr)
        try:
            elapsed, ratio, max_resident = run_test(
                row['compressor'], row['options'], config.data)
        except RuntimeError:
            results = (
                config.machine, config.arch, row['compressor'], row['options'],
                0, 0.0, 0, 0)
        else:
            results = (
                config.machine, config.arch, row['compressor'], row['options'],
                1, elapsed, max_resident, ratio)
        with db:
            db.execute(insert_sql, results)


if __name__ == '__main__':
    sys.exit(main())

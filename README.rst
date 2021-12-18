====================
Compression Analysis
====================

An analysis of various compressors with a variety of options across several
architectures and machine sizes.


Requirements
============

You will need the following packages installed if you wish to perform data
collection with the ``gather.py`` script:

* python3
* lz4
* xz-utils
* gzip
* zstd

You will need the following packages installed to read (and play with) the
analysis in ``analysis.ipynb``:

* python3-matplotlib
* python3-docutils
* jupyter-notebook

Once installed, simply run ``jupyter notebook`` in your clone of the repo, and
select ``analysis.ipynb`` in the browser window that opens.


Data Gathering
==============

We are particularly interested in the compression of an initramfs CPIO archive,
the compression ratio achieved, the time taken, and the maximum resident memory
used as the current default compression scheme used in Ubuntu is zstd with -19
which is not only extremely slow (even on large scale machines like an AMD
Ryzen) but also takes an amount of memory that results in OOM crashes on
smaller machines (e.g. a Pi Zero 2 or 3A+ which only has 512MB of RAM).

The ``gather.py`` script was used to measure the aforementioned parameters. The
typical method of execution (on a fully updated Jammy image) was to extract the
current ``initrd.img`` archive from the boot partition, and run the
``gather.py`` script with a suitable machine label. For example::

    $ git clone https://github.com/waveform80/compression
    $ cd compression
    $ zstdcat $(find /boot -name "initrd.img") > initrd.cpio
    $ ./gather.py initrd.cpio --machine "My Machine with 16GB RAM"

Provide some appropriate description with the ``--machine`` switch. Before the
run begins, the script also checks that all compressors to be tested are
executable and will prompt you to install any that are missing (you may need to
install ``lz4`` as that is not currently seeded).

The script is sufficiently intelligent not to re-run tests that already exist
in the database for the specified machine label. This helps dealing with the
smaller machines that had a tendency to crash entirely when pushed to their
limits.


Database Structure
==================

The script creates (or updates) the ``compression.db`` SQLite database which
has the following schema:


tests
-----

This table stores the list of all combinations of compressors,
compressor-specific options, and compression levels to test. Example: ``('xz',
'-e', '-6')``.

+--------------+------+---------------------------------------+
| Name         | Type | Description                           |
+==============+======+=======================================+
| *compressor* | TEXT | The name of the compressor            |
+--------------+------+---------------------------------------+
| *options*    | TEXT | The options to execute the compressor |
|              |      | with (if any)                         |
+--------------+------+---------------------------------------+
| *level*      | TEXT | The compression level to use          |
+--------------+------+---------------------------------------+

Views that derive from this table are **compressors** (which simply lists
distinct *compressor* values), and **options** (which lists distinct
*compressor* and *options* combinations).


results
-------

This is the "main" table, storing the results of all compression runs. It is
keyed by the machine's label, architecture, the compressor being tested, and
its command line options. The non-key attributes track the success of the
operation(s), the time they took, the maximum resident memory used, and the
compression ratio achieved.

+-----------------+--------------+-------------------------------------------+
| Name            | Type         | Description                               |
+=================+==============+===========================================+
| *machine*       | TEXT         | The label provided on by ``--machine`` on |
|                 |              | the command line                          |
+-----------------+--------------+-------------------------------------------+
| *arch*          | TEXT         | The ``dpkg`` architecture of the machine  |
+-----------------+--------------+-------------------------------------------+
| *compressor*    | TEXT         | The name of the compressor                |
+-----------------+--------------+-------------------------------------------+
| *options*       | TEXT         | The options to execute the compressor     |
|                 |              | with (if any)                             |
+-----------------+--------------+-------------------------------------------+
| *level*         | TEXT         | The compression level to use              |
+-----------------+--------------+-------------------------------------------+
| succeeded       | INTEGER      | 1 if the compression run succeeded, and 0 |
|                 |              | if it failed                              |
+-----------------+--------------+-------------------------------------------+
| comp_duration   | NUMERIC(8,2) | The number of seconds compression took    |
|                 |              | (wall clock time)                         |
+-----------------+--------------+-------------------------------------------+
| comp_max_mem    | INTEGER      | The maximum resident memory during        |
|                 |              | compression, in bytes                     |
+-----------------+--------------+-------------------------------------------+
| decomp_duration | NUMERIC(8,2) | The number of seconds decompression took  |
|                 |              | (wall clock time)                         |
+-----------------+--------------+-------------------------------------------+
| decomp_max_mem  | INTEGER      | The maximum resident memory during        |
|                 |              | decompression, in bytes                   |
+-----------------+--------------+-------------------------------------------+
| input_size      | INTEGER      | The size of the input file provided       |
+-----------------+--------------+-------------------------------------------+
| output_size     | INTEGER      | The size of the compressed output         |
+-----------------+--------------+-------------------------------------------+

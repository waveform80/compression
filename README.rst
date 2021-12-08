====================
Compression Analysis
====================

An analysis of various compressors with a variety of options across several
architectures and machine sizes.

We are particularly interested in the compression of an initramfs CPIO archive,
the compression ratio achieved, the time taken, and the maximum resident memory
used as the current default compression scheme used in Ubuntu is zstd with -19
which is not only extremely slow (even on large scale machines like an AMD
Ryzen) but also takes an amount of memory that results in OOM crashes on
smaller machines (e.g. a Pi Zero 2 or 3A+ which only has 512MB of RAM).


Requirements
============

You will need the following packages installed to read the analysis in
``analysis.ipynb``:

* python3-matplotlib
* python3-docutils
* jupyter-notebook

Once installed, simply run ``jupyter notebook`` in your clone of the repo, and
select ``analysis.ipynb`` in the browser window that opens.


Data Gathering
==============

To that end, the ``gather.py`` script was used to measure the aforementioned
parameters. The typical method of execution (on a fully updated Jammy image)
was to extract the current initrd.img archive, and run the ``gather.py`` script
with a suitable machine label. For example::

    $ zstdcat $(find /boot -name "initrd.img") > initrd.cpio
    $ ./gather.py initrd.cpio --machine "AMD Opteron 8GB"

The architecture of the machine will be queried by the script (via ``dpkg
--print-architecture``). Before the run begins, the script also checks that all
compressors to be tested are executable and will prompt you to install any that
are missing (you may need to install ``lz4`` as that is not currently seeded).

Finally, the script is sufficiently intelligent not to re-run tests that
already exist in the database for the specified machine label. This helps
dealing with the smaller machines that had a tendency to crash entirely when
pushed to their limits.


Results Structure
=================

The output of the script is the ``compression.db`` SQLite database which has
the following schema:

compressors
-----------

This table stores the list of all compressors to be tested. Example:
``('lz4',)``.

+--------------+------+----------------------------+
| Name         | Type | Description                |
+==============+======+============================+
| *compressor* | TEXT | The name of the compressor |
+--------------+------+----------------------------+


options
-------

This table stores the list of all combinations of compressors and command
line options to be tested by the script. Example: ``('lz4', '-9')``.


+--------------+------+---------------------------------------+
| Name         | Type | Description                           |
+==============+======+=======================================+
| *compressor* | TEXT | The name of the compressor            |
+--------------+------+---------------------------------------+
| *options*    | TEXT | The options to execute the compressor |
|              |      | with                                  |
+--------------+------+---------------------------------------+


results
-------

This is the "main" table, storing the results of all compression runs. It is
keyed by the machine's label, architecture, the compressor being tested, and
its command line options. The non-key attributes are a boolean (0 or 1)
indicating whether the test succeeded, the number of seconds elapsed during
the test, the maximum resident memory used (in kilobytes), and the
compression ratio achieved (a value > 0.0 and hopefully < 1).

+--------------+--------------+-------------------------------------------+
| Name         | Type         | Description                               |
+==============+==============+===========================================+
| *machine*    | TEXT         | The label provided on by ``--machine`` on |
|              |              | the command line                          |
+--------------+--------------+-------------------------------------------+
| *arch*       | TEXT         | The ``dpkg`` architecture of the machine  |
+--------------+--------------+-------------------------------------------+
| *compressor* | TEXT         | The name of the compressor                |
+--------------+--------------+-------------------------------------------+
| *options*    | TEXT         | The options to execute the compressor     |
|              |              | with                                      |
+--------------+--------------+-------------------------------------------+
| succeeded    | INTEGER      | 1 if the compression run succeeded, and 0 |
|              |              | if it failed                              |
+--------------+--------------+-------------------------------------------+
| elapsed      | NUMERIC(8,2) | The number of seconds execution took      |
|              |              | (wall clock time)                         |
+--------------+--------------+-------------------------------------------+
| max_resident | INTEGER      | The maximum resident memory during        |
|              |              | execution, in kilobytes                   |
+--------------+--------------+-------------------------------------------+
| ratio        | NUMERIC(8,7) | The compression ratio achieved            |
+--------------+--------------+-------------------------------------------+

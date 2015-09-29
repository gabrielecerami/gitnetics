Workflow
========

The gitnetics workflow can be split in two paths of 3 steps each

1. original to replica workflow
    1. original commits handling (performed by **poll-original** subcommand)
    2. recombinations test (perfomed by **prepare-tests** subcommand, an
       arbitrary test suite run, and a **vote-recombinations** subcommmand)
    3. replica advancement (performed by **merge-recombinations** subcommand)
2. patches to replica workflow
    1. patches commits handling (performed by **poll-replica** subcommand)
    2. recombinations tests (perfomed by **prepare-test** subcommand, an
       arbitrary test suite run, and a **vote-recombinations** subcommmand)
    3. patches update (performed by **merge-recombinations** subcommand)


Workflow jobs
-------------

To make gitnetics effective in CI frameworks like jenkins, a minimum of 4 jobs
must be created. (see a sample jenkins-jobs-builder configuration in examples/
directory of this documentation as a reference.)

- a job that launches **poll-original** subcommand

  It should be triggered by a timer, without arguments, to check on all
  projects, or with --watch-methods poll to check only git-based original
  repositories. The job may be triggered by a gerrit event too, but in this case
  *--projects* should be specified with the proper project name

- a job that prepare tests, launches tests suite, collect results and vote on
  recombinations

  This job should be triggered by patchset create event for recomb-* branches
  in replica gerrit. It can be the same for both recombinations type since they
  both should be testing the future branch-tag.

- a job that launches **merge-recombinations** subcommand

  It should be triggered by comment added event on any recomb-* branches in
  replica gerrit. Same subcommand will handle both recombination types.

- a job that launches **poll-replica** subcommand

  It should be triggered by patchset create event for *-patches branch in
  replica gerrit

Creating a job that launches the cleanup subcommand triggered by timer is
strongly recommended.

As a final note, a consideration for gerrit events may be in order. They are a
nice way to make steps in the workflow synchronous with what's happening in the
original or replica repositories, but they are not a reliable message passing
method. They can be lost very easily for a large number of reasons, and cannot
be replayed in any way.

We strongly suggest to add timed triggers to all the jobs, to check all the
projects and all the branches for something that the frameworks may have missed
from the gerrit repositories.

Every subcommand has the ability to perform batch operations on all the projects
specified in projects files, and replica update process is studied to not rely
much on such events, and to always detect and recover what's missing from the
interval that needs to be examined.


TODS:
    get score criteria (we probably want to just know if the test was run or not)
    recombination tets distribution (1 job per test)


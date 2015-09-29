Command line
===========

gitnetics can be run with

    python gitnetics.py

Common arguments
----------------

- Mandatory
    * *--projects-conf*: to specify the path of projects.yaml file
    * *--base-dir*: base dir of operations, where local copies of projects will
      be created

- Optional:
    * *--projects*: a comma separated list of projects names to filter on what
      projects run the subcommand, based on project name
    * *--watch-methods*: a comma separated list of watch methods to filter on
      what project run the subcommand, based on watch-method in project
      configuration
    * *--watch-branches*: a comma separated list of branches to filter on what
      branches on the filtered list of project run the subcommand.
    * *--no-fetch*: do not fetch remote updates in local git repositories,
      speeding up the commands (useful only for re-runs)

All paths must be absolute.

Subcommands
-----------

- **poll-original**: for each branch on each project, examine the commit in the
  interval replica HEAD -> original HEAD, and handle the original-diversity
  recombinations as their status require
  * no arguments needed

- **poll-replica**: if called without other arguments: for each branch-patches
  on each project, check for new changes in branch-patches, and create
  replica-mutation recombinations
  * *--change-id*: specify a change to check

- **prepare-tests**: if called without other arguments: for each untested
  recombination on each project, download recombination code and prepare a
  directory structure containing the informations needed by the test suite to
  test the recombination
  * *--tests-basedir*: (mandatory) base dir of the tests directory structure
  * *--recombination-id*: prepare tests only for the specified recombination

- **vote-recombinations**: it will scan the directory structure and vote on
  recombinations that passed the tests
  * *--tests-basedir*: (mandatory) base dir of the tests directory structure
  * *--recombination-id*: scan tests only for the specified recombination

- **merge-recombinations**: if called without other arguments: for each branch
  on each project, will check approved recombinations
    + on original-diversity recombinations, the command will call the same scan
      function as poll-original to handle recombination list, so this command
      may actually create some missing reviews, and merge some others too.
    + on replica-mutation recombinations, it will merge the recombination, force
      push target-branch to branch-tag and approve and submit the mutation on
      branch-patches too
  * *--recombination-id*: specify a recombination to check

- **cleanup**: it will perform maintenance tasks on replica and any mirrors of
  replica repositories
    + stale branches deletion: will detect and delete temporary target- and
      recomb- branches that are not referred by any recombination
    + delete mirror branches: gerrit repositories tend to replicate everything
      and delete nothing from their git mirrors counterparts. This task will
      delete any target- and recomb- branches from mirror repositories. They
      are only needed by replica base repositories
  * no arguments needed


Intro
====
Goals
----

When an upstream project is needed to be followed closely, it's often necessary
to start making fork at a certain point, to add local modifications, that will
inevitably diverge from the upstream project and have to be costantly rebased,
updated and maintained.

Gitnetics is a tool to help the task of maintaining a different, slightly
modified copy of an upstream project. It does so automatically following
upstream changes, attempting merges with your local modifications, test the
result of such merge for compliance with your environment, and finally push the
tested result to the local copy

Gitnetics can work with both git or gerrit upstream projects but relies heavily
on a working gerrit instance for the local repo.

It operates using the following tenets
- Upstream watched branches and correspondent local branches must have the same
  exact history
    * Merge all the patches and in the original order
    * Cannot deny a patch to be merged, only react in certain ways to test
      failures
- Human intervention must be kept to a minimum

Branching model on replica repositories
--------------

From now on, we will use these two terms to identify the repositories.
- **original**: the repo we are trying to replicate
- **replica**: the repo to where we want to replicate the original

Every branch from original is handled in replica using three different branches
- **replica/branch** is the exact clone of the original branch, updated
  gradually after verifications
- **replica/branch-patches** contains the local modifications on the original
  branch needed by replica repository. Should be properly rebased on original
  branch
- **replica/branch-tag** contains the results of merges between original branch
  and replica branch-patches. It's a service only branch, handled completely but
  gitnetics

replica/branch-tag may also be called 'target branch', and is the one that
should be used to create package from the repo.

Recombinations
==============

To update properly a branch-tag in replica, we have to be sure that the gradual
merges between branch and branch-patches do not lead to conflicts. Even if the
merge is successful, before pushing the result of a merge, we have to test it.

Definitions
-----------

Most of the terms that could be used for the various components it these types
of workflows were overused and ambiguous. For this reason, We decided to borrow
terms from biology related to the process of DNA replication.
- **recombination** is the name of a successful merge attempt between branch and
  branch-patches commits that is uploaded for testing. It is created in form of
  a gerrit change uploaded to replica repository, on a temporary, disposable
  branch (not directly on branch-tag).

We have to distinguish two kinds of sources of commits from branch-patches
- **diversity**: a branch-patches HEAD in replica repository
- **mutation**: a change in review on replica gerrit with branch-patches as
  target branch

Types
-----

Only two types of recombinations are allowed

- *original-diversity*

    created when a change is coming from original repo. Produces eventually a
    merge to commit into branch-tag branch, and an advancement in the replica

- *replica-mutation*

    created when a mutation is uploaded, a new review for the branch-patches
    branch. Produces eventually an updated branch-patches and again a merge to
    push to branch-tag branch in replica repo


Merge attempt process
-------------------------

When attempting the merge of a new change from original repo with local
modifications in branch-patches (original-diversity recombination) two temporary
branches for each original commit are used to store temporary snapshots in
replica repository

- recomb-original-\<original_branch_name>-\<original_commit_id\>
- target-original-\<original_branch_name\>-\<original_commit_id\>

These two branches are created with their HEAD set to the first parent of the
original commit, and pushed to replica. A squashed merge is then attempted on
the top of recomb-original-branch using original commit and branch-patches HEAD
as commit ids for the merge.

If the merge is successful, the result of this attempt is uploaded as review to
replica on the recomb-original-branch.

A second non squashed merge is then performed on top of target-original-branch,
and force pushed directly to replica/target-branch without a review. Those two
branches represent respectively the recombination, and the future branch-tag.

The merge on recomb-original-branch must be squashed because updates from
original repo could be merge commits, and gerrit will not accept multiple
commits as a review. That's why a second branch with non squashed commits is
needed.

When attempting the merge of a new change in branch-patches with replica repo
(replica-mutation recombination) the process is the same, with the only
difference that replica HEAD and branch-patches new commmit are used as ids in
the merge steps

Gerrit review fields
-------------

Each review created on replica gerrit follows this scheme:

- **branch**: temporary recomb-branch
- **topic**: original commit Change-Id (for gerrit originals) or commit-id (for
  git-only originals). Ids in topic are used for faster recombination searches
- **commit message**: as commit message a valid yaml document is uploaded. This
  is an example commit message


```yaml
    Recombination: original:72998e-diversity:6a9f94/master

    sources:
        main:
             branch: master
             id: 72998ebbfd22e5cafc350527be1deab1c6fb90ac
             name: original
             revision: 72998ebbfd22e5cafc350527be1deab1c6fb90ac
        patches:
             branch: master-patches
             id: 6a9f9492af6a3a59b74f043ce6bb8227909224b2
             name: diversity
             revision: 6a9f9492af6a3a59b74f043ce6bb8227909224b2
    target-replacement-branch: target-original-master-72998ebbfd22e5cafc350527be1deab1c6fb90ac
```

The first line serves as subject and contains a summary of the recombination.
From this first line we can detect the recombination type, the commit ids merged
and the original branch

The rest of the commit message contains detailed an complete informations on the
components that form the recombination.

The last line contains the name of the target-branch that will be force pushed
to branch-tag (master-tag in this case) when the recombination will be approved
and merged.

The yaml document inside commit message will be used to retrieve informations
during recombinations search, load and analysis

Automatic conflict resolution
-----------------------------
If a merge attempt fails, gitnetics will attempt to remove commits from
branch-patches one by one, starting from the least recent, until the merge
succeed (It will eventually succeed when branch-patches HEAD will become a
perfect ancestor of the main source HEAD). It will then add to the commit
message a removed-patches-commits variable containing a list of removed commits
and force push the resulting branch to branch-patches in replica repo.

Force pushing a new branch-patches could seem a little drastic, but
recombinations will not need the old branch-patches because the merge is already
stored in target-branch, and advancement for replica cannot continue if that
particular commit in branch-patches causes a merge failure.

Replica update process
----------------------

To achieve compliance with original ordering, every time a new change is detected
in the original repo the entire list of commits in the interval replica branch
HEAD -> original branch HEAD is examined. Each commit in this interval is then
assigned to a recombination and each recombination may have one of these
statuses

- **MISSING**: Recombination associated to this commit in original repo has not
  been attempted or created. In this case merge attempt and recombination
  creation process is activated.
- **PRESENT**: Recombination associated to this commit in original repo has been
  attempted, the attempt was successful and a change is in review in replica
  gerrit waiting for tests. In this case nothing is done, the recombination has
  to wait for approval
- **APPROVED**: Recombination associated to this commit in original repo has
  been created, tested, and test completed successfully (for a certain
  definition of successful) in this case push to branch-tag and replica branch
  advancement processes are activated, after resolving the commit ordering
  constraints. If an approved recombination is not "next in line" to be merged,
  procedures will stop.
- **MERGED**: Recombination associated to this commit in original repo has been
  created, tested, approved, and its result pushed to branch-tag. If it's still
  showing up in the interval it means that something went wrong during the
  advancement of replica branch to the associated original commit. In this case
  an advancement is retried.

While examining the list in the original order, statuses lists must respect these
constraints:

- no recombination with status MISSING can precede one with any other status
- no recombination with status PRESENT or APPROVED can precede in order one with
  status MERGED
- a recombination in APPROVED status can be merged, its result pushed to
  branch-tag, and replica branch advanced only if there are no preceding
  recombination in list, or all the recombinations with MERGED status have been
  processed properly

If one of the constraints is not respected, procedure will stop.

Taking as an example these list of commits in replica -> original interval
- **MERGED, APPROVED, PRESENT, MISSING** is a valid list, MERGED will be
  advanced, approved will be merged and advanced, present will wait for test
  completion, MISSING will be created
- **MERGED, PRESENT, APPROVED, MISSING** is a valid list too, this probably
  means that the tests for APPROVED finished before the tests for PRESENT. When
  PRESENT will be approved it will change its status, and both APPROVED
  recombinations will be merged _in order_ in the same pass.
- **MISSING, APPROVED, PRESENT** is a _invalid_ list, with a recoverable
  situation.
- **MISSING, MERGED** is an _invalid_ list and it's a broken replica repo.


Projects configuration
======================

Gitnetics is able to maintain multiple project and multiple branches. The
details of these projects must be placed into a yaml file, and its path passed
to gitnetics as a mandatory argument to the command line

Here's an example of a project configuration:

```yaml
    puppetlabs-xinetd:
        deploy-name: xinetd
        original:
            location: github
            name: puppetlabs/puppetlabs-xinetd
            type: git
            watch-branches:
            - master
            watch-method: poll
        replica:
            location: gerrithub-rdoci
            name: rdo-puppet-modules/puppetlabs-xinetd
            tests:
                - stability
                - upstream
        test-deps:
            puppetlabs-concat: classes
            puppetlabs-stdlib: functions
```

Basic configuration
-------------------

- the key of the variable dict is the name of the project
- **deploy-name** is the name of the project during deployment (e.g. name of the
  directory that contains the project after installation)
- **original**: contains the informations on the original repo such as:
    * **location**: is the name of the original repo as defined in ssh
      config. Gitnetics only supports ssh access to git repositories. it is
      required for each location mentioned to have a definition in ssh config
      file
    * **name**: name of the project in git location
    * **type**: either git or gerrit are supported for the original repos
- **replica**:
    * **location**: name of the replica repo
    * **name**: name of project in git location
    * *type* cannot be selected, replica repository **must** be a gerrit
      instance
    * **tests**: is a list of names referring to tests types that should be run
      on each recombination. The list will be passed to the test suite

Advanced features
-----------------
- **original/watched-branches**: is a list of branch from original repo we want
  to follow. If not specified, all original branches will be examined
    * watches-branches may contain a map of branches we want to follow, with a
      translation in another branch name. (e.g. master from original will be
      replicated to stable in replica)
- **replica/revision_lock**: is a map that specify that for a certain branch we
  don't want to advance replica behind a certain commit id
- **test-deps**: a list of other projects names on which this project depends. A
  list of comma separated tags may be specified to mark the type of dependency.
  test-deps will be used during testing phase to extract reverse dependencies
  information on each running test.


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


Tests
=====

The subcommand **prepare_tests** called for a project (target_project) will:

- pack contents of projects.yaml in project-vars.yaml file containing a single
  dictionary with all projects.
- search for unapproved (Code-Review < 2, Verified < 1 ) recombination on a
  specified branch, and download them
- for each recombination to test
    + extract reverse dependencies informations for the target project
    + for each reverse dependency, extract informations on tests to run on them
- finally, assemble all the informations above and create the directory
  structure shown below

    * **tests-base/project-var.yml**: contains the projects-vars.yaml with
      projects configurations
    * **tests_base/\<target_project_name\>/\<recomb_id\>/code**: contains the
      recombination code to use in the tests.
    * **tests_base/\<target_project_name\>/\<recomb_id\>/vars.yaml**: contains
      variables pertaining a certain recombination to test, assembled as
      follows:


```yaml
    recombination_dir: puppet-keystone/245318/code
    recombination_id: '245318'
    target-project: puppet-keystone
    tests:
        puppet-ceilometer:
            types:
                stability: puppet-keystone/245318/results/stability/puppet-ceilometer_results.xml
                upstream: puppet-keystone/245318/results/upstream/puppet-ceilometer_results.xml
        puppet-glance:
            types:
                stability: puppet-keystone/245318/results/stability/puppet-glance_results.xml
                upstream: puppet-keystone/245318/results/upstream/puppet-glance_results.xml
```

Path variables contain relative paths for the directory structure itself, and
types.type will hint where to put the results of that type of test for a certain
project

* **tests_base/\<target_project_name\>/\<recomb_id\>/results/\<test_type\>/**
  should contain result files for every project (target and dependencies) tested
  in the recombination

Test suite is expected to fill this directory with the test result of each
single component, as shown in vars.yaml file.

For example

    tests_base/<project_name>/<recomb_id>/results/<test_type>/<target_project_name>.xml
    tests_base/<project_name>/<recomb_id>/results/<test_type>/<project_dependency1_name>.xml
    tests_base/<project_name>/<recomb_id>/results/<test_type>/<project_dependency2_name>.xml


The subcommand **vote-recombinations** will then look at test results inside
this updated directory structure, and following vote criteria, it will approve
(Code-Review +2 , Verified +1) the corresponding recombinations

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


Intro
-----
Goals
====

When you follow closely an upstream project, you start making fork at a certain point, that will inevitably diverge from the upstream project and have to be
costantly rebased, updated, maintained
Gitnetics is a tool to help the task of maintaining a different, slightly modified repository of an upstream project.
It does so automatically following upstream changes, attempting merges with your local modifications, and test the result of such merge for compliance with your environment.

Gitnetics can work with git or gerrit upstream projects but relies heavily on a working gerrit installation for the personal repo.

It operates using the following tenets
- Upstream watched branch and correspondent local branch must have the same exact history
    * Merge all the patches and in the original order
    * Cannot deny a patch to be merged, only react in certain ways to
    test failures
- Human intervention must be kept to a minimum

Definitions
===========
- original -> the repo we are trying to replicate
       (upstream)
- replica -> the repo to which we want to replicate the
       original (midstream)

Branching model
==============

Every original branch is handled in replica using three different branches
- replica/branch is the exact clone of the original branch, updated gradually after verifications
- replica/branch-patches contains the local modifications on the original branch needed by replica repository
- replica/branch-tag contains the result of merges between original branch and replica branch-patches

replica/branch-tag is the target branch, and the one that should be used to create package from the repo.

git strategy slides
the idea is: when an update arrives, we merge it with master-patches, check if merge is possible, then test the result of the merge and test if it work in our environemnt.


Recombinations theory
---------------------

To update properly a branch-tag in replica, we have to be sure that the merge between branch and branch-patches doesn't lead to conflicts.
Even if the merge is successful, before pushing the result of a merge, we have to test it.

definitions
===========

Most of the terms that can be used for the various components are overused and ambiguous
For this reason, I decided to borrow terms from biology related to the process of DNA replication.

- recombination is the name of a successful merge attempt between branch and branch-patches that is uploaded for testing.
  it is created in form of a gerrit change uploaded to replica repository, on a temporary, disposable branch (not directly on branch-tag).

We have to distinguish two kinds of sources from branch-patches
- diversity -> any branch-patches HEAD in replica repository
- mutation -> any change in in review on replica gerrit with branch-patches as target branch

types
=====

Only two types of recombinations are allowed
- original-diversity
        created when a change is coming from our original repo (upstream in this case)
        produces  merge to commit into master-tag branch, and a new updated master branch in the replica
- replica-mutation
        created when we have a mutation, for example a new patch for the master-patches branch
        produces an updated master-patches and again a merge to commit to master-tag branch


Recombination in practice
=========================

the merge attemmt process
-------------------------
        temporary branches
            recomb branch (squashed) imagining a master-patches with multiple commits to merge, gerrit requires you to squash those commits before uploading for review
            target branch (not squashed)
    the real merge process

recombination review structure
------------------------------
            commit message
            topic

replica update process
----------------------

To achieve compliance with original ordering every time a new change is detected in the original repo the entire list of commits in the interval
replica branch HEAD -> original branch HEAD is examined. Each commit in this interval is then assigned to a recombination and each recombination may have one of these statuses
- MISSING: Recombination associated to this commit in original repo has not been attempted or created.
  in this case merge attempt and recombination creation process is activated.
- PRESENT: Recombination associated to this commit in original repo has been attempted, the attempt was successful and a change is in review in replica gerrit waiting for tests
  in this case nothing is done, the recombination has to wait for approval
- APPROVED: Recombination associated to this commit in original repo has been created, tested, and test completed successfully (for a certain definition of successful)
  in this case push to branch-tag and replica branch advancement process are activate, after resolving the commit ordering constraints. If an approved recombination is not "next in line" to be merged, procedures will stop.
- MERGED: Recombination associated to this commit in original repo has been created, tested, approved, and its result pushed to branch-tag. If it's still showing up in the interval means that something went wrong during the advancement of replica branch to the associated original commit
  In this case an advancement is retried.

examining the list in the original order, status must respect these constraints:

no recombination with status MISSING can precede one with any other status
no recombination with status PRESENT or APPROVED can precede in order one with status MERGED or MISSING
a recombination in APPROVED status can be merged, its result pushed to branch-tag, and replica branch advanced only if there are no preceding recombination in list, or all the recombinations with MERGED status have been processed properly

Taking as an example these list of commits in replica -> original interval
- MERGED, APPROVED, PRESENT, MISSING is a valid list, MERGED will be advanced, approved will be merged and advanced, present will wait for test completion, MISSING will be created
- MERGED, PRESENT, APPROVED, MISSING is a valid list too, this probably means that the tests for APPROVED finished before the tests for present. When PRESENT will be approved, both APPROVED will be merged _in order_ in the same pass.
- MISSING, APPROVED, PRESENT is a _invalid_ list, with a recuperable situation.
- MISSING, MERGED is an _invalid_ list and it's a broken replica repo.



Projects configuration
======================

gitnetics uses a configuration file in yaml passed as a mandatory argument to the command line
that contains all the informations need to maintain the replication process
It contains this variables:

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
            tests: null
        test-deps:
            puppetlabs-concat: classes
            puppetlabs-stdlib: functions

basic informations
------------------

features
--------
        branch selection
        branch mapping
        tests selection
        revision lock
        dependency handling
        conflict resolution


command line
------------
subcommands
===========
        poll-original
            for each commit that is upstream but not midstream, attempt the merge and upload the result as a review


Tests
-----

the subcommand *prepare_tests* called for a project (target_project) will:

- pack contents of projects.yaml in yaml file containing a single dictionary
- search for unapproved (Code-Review < 2, Verified < 1 ) recombination on a specified branch, and download them
- for each recombination to test
    + extract reverse dependencies informations for the target project
    + for each reverse dependency, extract informations on tests to run
- finally, assemble all the informations above and create the directory structure shown below


* tests-base/project-var.yml: contains the projects.yaml information under the 'project' superdict
* tests_base/<target_project_name>/<recomb_id>/code: contains the recombination code to use in the tests.
* tests_base/<target_project_name>/<recomb_id>/vars.yaml: contains variables pertaining a certain recombination to test in this form:

    ---
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

path variables contain relative paths for the directory structure itself.
types.type will hint where to put the results of that type of test for a certain project

* tests_base/<target_project_name>/<recomb_id>/results/<test_type>/ should contain result files for every project (target and dependencies) tested in the recombination

Test suite is expected to fill this directory with the test result of each single component, as shown in vars.yaml file.
for example
    tests_base/<project_name>/<recomb_id>/results/<test_type>/<target_project_name>.xml
    tests_base/<project_name>/<recomb_id>/results/<test_type>/<project_dependency1_name>.xml
    tests_base/<project_name>/<recomb_id>/results/<test_type>/<project_dependency2_name>.xml


the subcommand *vote_recombination* will then look at test results inside this updated directory structure, and following vote criteria, it will approve (Code-Review +2 , Verified +1) the correspoding recombinations

workflow jobs
-------------
    general considerations 
        (event triggers, time triggers)
        gerrit event trigger a scan on the project
        batch operations
    example

typical workflow
================


OMGS:
    get score criteria (we probably want to just know if the test was run or not)
    recombination tets distribution (1 job per test)


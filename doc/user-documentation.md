Intro
-----
Goals
====
    Upstream master and midstream master must have the same exact history
    ○ We merge all the patches and in the original order
    ○ We cannot deny a patch to be merged, only react in certain ways to
    test failures
    Human intervention must be kept to a minimum
    we have one midstream repository for each of the upstream repositories
    (58 in total) that must be tested and updated to form a single package
    git model
        upstream branch
        local branch
        local branch-tag
        local branch-patches
        git strategy slides
        the idea is: when an update arrives, we merge it with master-patches, check if all is ok, then test the result of the merge and test if it work in our environemnt.


1 Recombinations theory
   definitions

        A big problem I encountered when designing this workflow is that I found any terms I could use for the various components overused and ambiguous, so various times I got confused because I was using the same term to indicate two different things
        For this reason, I decided to borrow terms from biology related to the process of DNA replication

       before pushing the merge we create a merge attempt that we call recombination
       Recombinations are our attempt to assemble a merge between for example master and master-patches
       that will be eventually pushed to master-tag branch
       When we do our tests we do them on recombinations, not the single change that comes from upstream
       Recombination is Our basic unit of operation
       original -> the repo we are trying to replicate
       (upstream)
       ○ replica -> the repo to which we want to replicate the
       original (midstream)
       ○ diversity -> essentially any -patches branch in replica
       repo
       ○ mutation -> a change in replica gerrit destined to be submitted to a -patches branch in replica repo
    types
      original-diversity
        created when a change is coming from our original repo (upstream in this case)
        produces  merge to commit into master-tag branch, and a new updated master branch in the replica
      replica-mutatio
        created when we have a mutation, for example a new patch for the master-patches branch
        produces an updated master-patches and again a merge to commit to master-tag branch

2 update strategy
    we don't merge anything in different order
    original-replica interval
    Recombination in practice
        statuses
            MERGED:  (this usually means that a job got interrupted between approving the recombination and pushing the result to -tag branch).
        change structure
            commit message
            topic
    the merge attemmt process
        conflict resolution
        temporary branches
            recomb branch (squashed) imagining a master-patches with multiple commits to merge, gerrit requires you to squash those commits before uploading for review
            target branch (not squashed)
    the real merge process

3 tests
    tests preparation
    test informations structure
    recombination approval


2 gitnetics
    features
    projects file
    cli subcommands
        poll-original
            for each commit that is upstream but not midstream, attempt the merge and upload the result as a review


3 workflow jobs
    general considerations 
        (event triggers, time triggers)
        gerrit event trigger a scan on the project
        batch operations
    examples


OMGS:
    get score criteria (we probably want to just know if the test was run or not)
    recombination tets distribution (1 job per test)


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

When we merge with branch we have to distinguish what kind of commit we want to
pick from branch-patches
- **diversity**: is branch-patches HEAD in replica repository
- **mutation**: is a change in review on replica gerrit with branch-patches as
  target branch

Types
-----

Only two types of recombinations are allowed

- *original-diversity*

    created when a change is coming from original repo. Eventually produces a
    merge to commit into branch-tag branch, and an advancement in the replica

- *replica-mutation*

    created when a mutation is uploaded and updated for every patchset in the
    review. Produces eventually an updated branch-patches and again a merge to
    push to branch-tag branch in replica repo


Merge attempt process
-------------------------

Since we are *attempting* a recombination, we don't directly create a review for
one of the main branches. We store the results of the merge in two separate
temporary, disposable branches, that last for the time it takes to approve the
recombination. One, with the merge squashed, is used to store the merge in
gerrit, because gerrit needs eventual multiple commits to be squashed. The
other, non-squashed, is the effective merge, stored in a temporary branch so as
much as all the other branches around involved are are modified, we'all always
have a copy of the effective result of that recombination.

For example, when attempting the merge of a new change from the original repo
with local modifications in branch-patches (original-diversity recombination)
two temporary branches for each original commit are used to store temporary
snapshots in replica repository

- recomb-original-\<original_branch_name>-\<original_commit_id\>
- target-original-\<original_branch_name\>-\<original_commit_id\>

These two branches are created with their HEAD set to the first parent of the
original commit, and pushed to replica. We are basically creating (locally and
remotely) two branches each one step behind the merge.

A squashed merge is then attempted on the top of recomb-original-branch using
original commit and branch-patches HEAD as commit ids for the merge.

If the merge is successful, the result of this attempt is pushed as review to
replica gerrit for the recomb-original-X-X branch.

A second non squashed merge is then performed locally on top of
target-original-X-X branch, and pushed directly to replica/branch-tag without
passing through a review.

Those two branches represent now respectively the recombination, and the future
branch-tag.

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

Each review created on replica gerrit have standard fields filled as follows:

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
The yaml contains only additional informations gerrit is not able to provide.

The first line serves as subject and contains a summary of the recombination.
From this first line we can detect the recombination type, the commit ids merged
and the original branch

The rest of the commit message contains detailed and complete information on the
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
in the original repo the entire list of commits in the interval: replica branch
HEAD -> original branch HEAD is examined. Each commit in this interval is then
associated to an existing recombination or will form a new recombination.
Each recombination may have one of these statuses

- **MISSING**: Recombination associated with this commit in original repo has
  not been attempted or created. In this case merge attempt and recombination
  creation process is activated.
- **PRESENT**: Recombination associated with this commit in original repo has
  been attempted, the attempt was successful and a change is in review in
  replica gerrit waiting for tests. In this case nothing is done, the
  recombination has to wait for approval
- **APPROVED**: Recombination associated with this commit in original repo has
  been created, tested, and test completed successfully (for a certain
  definition of successful) in this case push to branch-tag and replica branch
  advancement processes are activated, after resolving the commit ordering
  constraints. If an approved recombination is not the one we have to merge next,
  procedures will stop.
- **MERGED**: Recombination associated with this commit in original repo has
  been created, tested, approved, and its result pushed to branch-tag. If it's
  still showing up in the interval it means that something went wrong during the
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

Take these lists as examples of lists of commits in replica -> original interval
- **MERGED, APPROVED, PRESENT, MISSING** is a valid list, MERGED will be
  advanced, approved will be merged and advanced, present will wait for test
  completion, MISSING will be created
- **MERGED, PRESENT, APPROVED, MISSING** is a valid list too, this probably
  means that the tests for APPROVED finished before the tests for PRESENT. When
  PRESENT will be approved it will change its status, and both APPROVED
  recombinations will be merged _in order_ in the same pass.
- **MISSING, APPROVED, PRESENT** is a _invalid_ list, two recombinations were
  created without considering a commit that precedes both of them. This should
  be a manually recoverable situation, since nothing has been pushed on main
  branches
- **MISSING, MERGED** is an _invalid_ list, because upstream order was not
  respected, and upstream/branch and replica/branch will diverge. This means
  that replica branch repo is broken and should manually be recreated


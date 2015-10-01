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


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


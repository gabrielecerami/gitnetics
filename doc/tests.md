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

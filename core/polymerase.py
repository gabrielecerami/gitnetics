import copy
import traceback
from colorlog import log, logsummary
from project import Project
import sys


class Polymerase(object):

    def __init__(self, projects_conf, base_dir, filter_projects=None, filter_method=None, filter_branches=None, fetch=True):
        self.projects = dict()
        self.projects_conf = projects_conf
        self.base_dir = base_dir
        # extract reverse dependencies
        for project in self.projects_conf:
            self.projects_conf[project]["rev-deps"] = {}
        for project in self.projects_conf:
            if "test-teps" in self.projects_conf[project]:
                for test_dep in self.projects_conf[project]["test-deps"]:
                    rev_dep = {
                        project : {
                        "tags" :self.projects_conf[project]["test-deps"][test_dep],
                        "tests":self.projects_conf[project]["replica"]["tests"]
                        }
                    }
                    self.projects_conf[test_dep]["rev-deps"].update(rev_dep)

        # restrict project to operate on
        projects = copy.deepcopy(projects_conf)
        project_list = list(projects)
        if filter_method:
            new_projects = dict()
            log.info('Filtering projects with watch method: %s' % filter_method)
            for project_name in projects:
                if projects[project_name]['original']['watch-method'] == filter_method:
                    new_projects[project_name] = projects[project_name]
            projects = new_projects
        if filter_projects:
            new_projects = dict()
            log.info('Filtering projects with names: %s' % filter_projects)
            project_names = filter_projects.split(',')
            for project_name in project_names:
                if project_name not in project_list:
                    log.error("Project %s is not present in projects configuration" % project_name)
                try:
                    new_projects[project_name] = projects[project_name]
                except KeyError:
                    log.warning("Project %s already discarded by previous filter" % project_name)
            projects = new_projects
        if filter_branches:
            log.info("Filtering branches: %s" % filter_branches)
            branches = filter_branches.split(',')
            for project_name in projects:
                projects[project_name]['original']['watch-branches'] = branches

        if not projects:
            log.error("Project list to operate on is empty")
            raise ValueError
        log.debugvar('projects')

        logsummary.info("initializing and updating local repositories for relevant projects")

        for project_name in projects:
            try:
                self.projects[project_name] = Project(project_name, projects[project_name], self.base_dir + "/"+ project_name, fetch=fetch)
                logsummary.info("Project: %s initialized" % project_name)
            except Exception, e:
                traceback.print_exc(file=sys.stdout)
                log.error(e)
                logsummary.error("Project %s skipped, reason: %s" % (project_name, e))

    def poll_original(self):
        logsummary.info('Polling original for new changes. Checking status of all changes.')
        success = True
        for project_name in self.projects:
            logsummary.info('Project: %s' % project_name)
            project = self.projects[project_name]
            #try:
            #    project.poll_original_branches()
            project.poll_original_branches()
            #except Exception, e:
            #   logsummary.info("Problem with project %s: %s. Skipping" % (project_name, e))
        return success

    def poll_replica(self, project_name=None, patches_change_id=None):
        success = True
        for project_name in self.projects:
            project=self.projects[project_name]
            if patches_change_id:
                if not project.new_replica_patch(patches_change_id):
                    success = False
            else:
                if not project.scan_replica_patches():
                    success = False
        return success

    def prepare_tests(self, tests_basedir, recomb_id=None):
        logsummary.info('Fetching untested recombinations')
        tester_vars = dict()
        tester_vars['projects_conf'] = { 'projects': self.projects_conf }
        for project_name in self.projects:
            logsummary.info('Project: %s' % project_name)
            project = self.projects[project_name]
            log.debugvar('recomb_id')
            #try:
            changes_infos = project.fetch_untested_recombinations(tests_basedir, recomb_id=recomb_id)
            for change_number in changes_infos:
                tester_vars[change_number] = changes_infos[change_number]
           # except Exception, e:
            #    logsummary.info("Problem with project %s: %s. Skipping" % (project_name, e))
        return tester_vars

    def vote_recombinations(self, test_results, recomb_id=None):
        for target_project in test_results:
            if target_project in self.projects:
                project = self.projects[target_project]
                project_test_results = test_results[target_project]
                if recomb_id != None:
                    if recomb_id in project_test_results:
                        project.vote_recombinations(project_test_results, recomb_id=recomb_id)
                else:
                    project.vote_recombinations(project_test_results)

    def check_approved_recombinations(self, project_name=None, recomb_id=None):
        success = True
        if recomb_id:
            project = self.projects[project_name]
            recombination = project.get_recombination(recomb_id)
            project.check_approved_recombinations(recombination=recombination)
        else:
            for project_name in self.projects:
                log.info("Checking project '%s'" % project_name)
                project = self.projects[project_name]
                project.check_approved_recombinations()

    def janitor(self):
        for project_name in self.projects:
            project = self.projects[project_name]
            project.delete_service_branches()
            log.info("delete stale branches")
            project.delete_stale_branches()
            # non-existing:
            # for branch in watched branches
            # if branch-tag not it branches:
            # git branch branch-tag branch
            # if branch-patches not it branches:
            # git branch branch-tag branch


            # upload projects_config WIP
            #git fetch origin refs/meta/config:refs/remotes/origin/meta/config
            #git checkout meta/config
            #grep descr project.config
            #git diff project.config
            #git diff groups
            #cp project.config conf/groups .
            #git commit -a -m "Changing Ownership"; git push origin HEAD:refs/meta/config ; cd .
            # update gerrit trigger configuration based on projects.yaml

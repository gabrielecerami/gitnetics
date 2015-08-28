import copy
from colorlog import log
from project import Project


class Polymerase(object):

    def __init__(self, projects_conf, base_dir, filter_projects=None, filter_method=None, filter_branches=None):
        self.projects = dict()
        self.projects_conf = projects_conf
        self.base_dir = base_dir
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
            branches = args.watch_branches.split(',')
            for project_name in projects:
                projects[project_name]['original']['watch-branches'] = branches

        if not projects:
            log.error("Project list to operate on is empty")
            raise ValueError
        log.debugvar('projects')

        log.info("initializing local repositories for relevant projects")

        for project_name in projects:
            log.debug("Initializing project: %s locally" % project_name)
            try:
                self.projects[project_name] = Project(project_name, projects[project_name], self.base_dir + "/"+ project_name)
            except Exception, e:
                log.error(e)
                log.error("Project %s not available, skipping" % project_name)

    def poll_original(self):
        success = True
        for project_name in self.projects:
            project = self.projects[project_name]
            project.poll_original_branches()
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

    def download_untested_recombinations(self, base_dir, recomb_id=None):
        tester_vars = dict()
        tester_vars['projects'] = self.projects_conf
        for project_name in self.projects:
            project = self.projects[project_name]
            log.debugvar('recomb_id')
            changes_infos = project.download_untested_recombinations(download_dir, recomb_id=recomb_id)
        for seq, test_infos in enumerate(changes_infos):
            test_id = 'test-%s' % seq
            tester_vars[test_id] = test_infos
        return tester_vars

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

import pprint
import re
import sys
import yaml
import copy
from colorlog import log
from collections import OrderedDict
from datastructures import Change, Recombination
from repotypes.git import LocalRepo, Git, RemoteGit
from repotypes.gerrit import Gerrit

class TestError(Exception):
    pass
class RecombinationSubmitError(object):
    pass
class RecombinationSyncReplicaError(object):
    pass


class Project(object):

    status_impact = {
        "MERGED": 2,
        "APPROVED": 1,
        "PRESENT": 1,
        "MISSING": 0
    }

    def __init__(self, project_name, project_info, local_dir):
        self.project_name = project_name
        self.recombinations = dict()
        self.commits = dict()

        log.info('Current project:\n' + pprint.pformat(project_info))
        self.original_project = project_info['original']
        self.replica_project = project_info['replica']
        self.deploy_name = project_info['deploy-name']

        self.underlayer = LocalRepo(project_name, local_dir)

        self.underlayer.add_gerrit_remote('replica', self.replica_project['location'], self.replica_project['name'])

        self.replica_remote = self.underlayer.remotes['replica']

        if self.original_project['type'] == 'gerrit':
            self.underlayer.add_gerrit_remote('original', self.original_project['location'], self.original_project['name'])

        elif self.original_project['type'] == 'git':
            self.underlayer.add_git_remote('original', self.original_project['location'], self.original_project['name'])

        self.original_remote = self.underlayer.remotes['original']
        self.recomb_remote = self.replica_remote
        self.patches_remote = self.replica_remote

        self.underlayer.add_git_remote('replica-mirror', 'github', self.replica_project['name'])
        # get branches from original
        #self.original_branches = self.underlayer.list_branches('original')
        self.original_branches = project_info['original']['watch-branches']
        ob = self.original_branches
        log.debugvar('ob')

        # reverse map branches

        self.replica_branches = dict()
        for original_branch in self.original_branches:
            # apply mapping to find target branch
            try:
                replica_branch = project_info['replica']['branch-mappings'][original_branch]
            except KeyError:
                replica_branch = original_branch
            self.replica_branches[original_branch] = replica_branch
            self.recombinations[replica_branch] = None
            self.commits[replica_branch] = {}

        self.target_branches = dict()
        self.patches_branches = dict()
        for replica_branch in self.replica_branches:
            self.target_branches[replica_branch] = '%s-tag' % replica_branch
            self.patches_branches[replica_branch] = '%s-patches' % replica_branch

        p = self.__dict__
        log.debugvar('p')
        #self.recombinations_attempts = []

    def get_slices(self, recombinations):
        slices = {
            "MERGED": [],
            "APPROVED": [],
            "PRESENT": [],
            "MISSING": [],
        }
        previous_status = None
        previous_impact = None
        current_slice = {}

        # Slice
        for index, recomb_id in enumerate(list(recombinations)):
            replica_change = recombinations[recomb_id]

            # creates slices to apply to change list
            # every status may have multiple slices, but this situation is tolerated
            # only between PRESENT' and 'APPROVED' statuses
            # any other complicated mix is a violation of upstream order
            status = replica_change.status
            impact =  self.status_impact[status]
            previous_change_id = None
            # Handle current status slice, archive previous slice
            try:
                segment = current_slice[status]
            except KeyError:
                if previous_status:
                    slices[previous_status].append(copy.deepcopy(current_slice[previous_status]))
                    del(current_slice[previous_status])
                current_slice[status] = {}
                segment = current_slice[status]
                segment['start'] = index
                segment['end'] = index + 1
            # init/extend current slice
            if previous_status:
                if impact > previous_impact:
                    log.critical("Constraint violation error: status %s at index %d (change:%s) of changes list in interval is more advanced than previous status %s at index %d (change: %s)" % (status, index, recomb_id, previous_status, index-1, previous_change_id))
                    log.critical("This means that midstream is broken")
                    raise ConstrainViolationError
                if status == previous_status:
                    segment['end'] = segment['end'] + 1
            # end of status list
            if index == len(list(recombinations)) - 1:
                    slices[status].append(copy.deepcopy(current_slice[status]))
                    del(current_slice[status])

            previous_status = status
            previous_impact = impact
            previous_change_id = recomb_id

        return slices

    def scan_original_distance(self, original_branch):
        log.debug("Scanning distance from original branch %s" % original_branch)
        self.recombinations[original_branch] = self.get_recombinations_by_interval(original_branch)
        slices = self.get_slices(self.recombinations[original_branch])
        replica_branch = self.replica_branches[original_branch]
        target_branch = self.target_branches[replica_branch]
        recombinations = self.recombinations[original_branch]


        log.debugvar('slices')
        # Master sync on merged changes
        # we really need only the last commit in the slice
        # we advance the master to that, and all the others will be merged too
        if slices['MERGED']:
            # one or more changes are merged in midstream, but missing in master
            # master is out of sync, changes need to be pushed
            # but check first if the change was changed with a merge commit
            # if yes, push THAT to master, if not, it's just a fast forward
            log.warning("branch is out of sync with original")
            segment = slices['MERGED'][0]
            recomb_id = list(recombinations)[segment['end'] - 1]
            recombination = recombinations[recomb_id]
            recombination.sync_replica(replica_branch)

        # Gerrit operations from approved changes
        # NOthing 'approved' can be merged if it has some "present" before in the history
        skip_list = set()
        for index, approved_segment in enumerate(slices['APPROVED']):
            for present_segment in slices['PRESENT']:
                if present_segment['start'] < approved_segment['start']:
                    skip_list.add(index)

        for index in list(skip_list)[::-1]:
            segment = slices['APPROVED'].pop(index)
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                log.warning("Change %s is approved but waiting for previous unapproved changes, skipping" % recomb_id)

        # Merge what remains
        for segment in slices['APPROVED']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                try:
                    recombination.submit(target_branch)
                except RecombinationSubmitError:
                    log.error("Recombination not submitted")
                try:
                    recombination.sync_replica(replica_branch)
                except RecombinationSyncReplicaError:
                    log.error("Replica could not be synced")

        # Notify of presence
        for segment in slices['PRESENT']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                recombination = recombinations[recomb_id]
                log.warning("Change %s already present in midstream gerrit as change %s and waiting for approval" % (recomb_id, recombination.number))

        # Gerrit operations for missing changes
        for segment in slices['MISSING']:
            for recomb_id in list(recombinations)[segment['start']:segment['end']]:
                log.warning("Change %s is missing from midstream gerrit" % recomb_id)
                recombination = recombinations[recomb_id]
                try:
                    recombination.test()
                except TestError:
                    log.error("Recombination attempt unsuccessful")
                    return False

        return True

    def get_recombination_by_search_key(self, search_key, search_field='change', key_field='id', branch=None):
        infos = self.replica_remote.get_changes_info([search_key], search_field=search_field, key_field=key_field, branch=branch)
        if search_key in infos:
            recombination = Recombination(self, infos=infos[search_key])
            return recombination
        return None

    def recombine_from_patches(self, patches_change_id):
        recombinations = OrderedDict()

        recombination = self.get_recombination_by_search_key(patches_change_id, search_field='topic', key_field='topic')

        if not recombination:
            patches_change = self.replica_remote.get_changes_by_id([patches_change_id])[patches_change_id]
            recombination = Recombination(self)
            recombination.patches = patches_change
            recombination.patches.repo = self.replica_remote

            recombination.original = Change(repo=self.original_remote)
            recombination.original.branch = re.sub('-patches','', recombination.patches.branch)

            change = Change(repo=self.replica_remote)
            change.branch = recombination.original.branch
            change.revision = self.underlayer.get_revision("remotes/replica/%s" % recombination.original.branch)
            change.parent = self.underlayer.get_revision("remotes/replica/%s~1" % recombination.original.branch)
            change.previous_commit = change.parent
            change.uuid = change.revision


            recombination.replica = change

            recombination.branch = "recomb-patches-%s-%s" % (recombination.replica.branch, recombination.replica.revision)
            recombination.topic = patches_change_id
            recombination.status = "MISSING"

        recombinations[patches_change_id] = recombination
        return recombinations

    def scan_replica_patches(self):
        for original_branch in self.original_branches:
            replica_branch = self.replica_branches[original_branch]
            patches_branch = self.patches_branches[replica_branch]
            patches_changes = self.patches_remote.get_changes_by_id([patches_branch], search_field='branch', branch=patches_branch )
            for change in patches_changes:
                self.replica_patch(change)

    def replica_patch(self, change_id):
        recombination = self.get_recombination_by_patch_change(change_id)
        if recombination.status == "MISSING":
            if not recombination.test('replica', 'mutation'):
                log.error("Recombination attempt unsuccessful")
                return False
            recombination.upload()
        else:
           log.warning("Master patches recombination present as number %s and waiting for approval" % recombination.number)
        return True

    def poll_original_branches(self):
        for branch in self.original_branches:
            self.scan_original_distance(branch)

    def get_recombinations_by_interval(self, original_branch):
        revision_start = 'remotes/replica/%s' % (original_branch)
        replica_branch = self.replica_branches[original_branch]
        revision_end = 'remotes/original/%s' % (replica_branch)
        patches_branch = self.patches_branches[replica_branch]
        diversity_refname = "remotes/replica/%s" % (patches_branch)
        self.commits[replica_branch] = self.underlayer.get_commits(revision_start, revision_end)
        commits = self.commits[replica_branch]
        ids = self.original_remote.get_original_ids(commits)
        log.debugvar("ids")

        recombinations = OrderedDict()
        if ids:
            # Just sets the right order
            for recomb_id in ids:
                recombinations[recomb_id] = None

            original_changes = self.original_remote.get_changes_by_id(ids, branch=original_branch)
            log.debugvar('original_changes')
            replicas_infos = self.replica_remote.get_changes_info(ids, search_field='topic', key_field='topic')
            #replica_revision = self.underlayer.get_revision("remotes/replica/%s" % replica_branch)
            diversity_revision = self.underlayer.get_revision(diversity_refname)
            diversity_change = self.underlayer.get_changes_by_id([diversity_revision], branch=patches_branch)[diversity_revision]

            for recomb_id in ids:
                if recomb_id in replicas_infos:
                    # relative recombination exists, load informations
                    recombinations[recomb_id] = Recombination(self.underlayer, 'original-diversity', remote=self.recomb_remote, infos=replicas_infos[recomb_id], original_remote=self.original_remote)
                else:
                    # relative recombination missing, creating empty one
                    recombinations[recomb_id] = Recombination(self.underlayer, 'original-diversity', remote=self.recomb_remote)
                    recombinations[recomb_id].status = "MISSING"
                    recombinations[recomb_id].branch = "recomb-original-%s-%s" % (original_branch, original_changes[recomb_id].revision)
                    recombinations[recomb_id].topic = recomb_id
                #recombinations[recomb_id].replica = Change(repo=self.replica_remote)
                #recombinations[recomb_id].replica.revision = replica_revision
                #recombinations[recomb_id].replica.branch = replica_branch

                recombinations[recomb_id].original_change = original_changes[recomb_id]

                recombinations[recomb_id].diversity_change = diversity_change

            for recomb_id in ids:
                log.debugvar('recomb_id')
                recomb = recombinations[recomb_id].__dict__
                log.debugvar('recomb')

        return recombinations

    def merge_tested_recombinations():
        pass

    def scan_patches_branch(self, branch):
        branch_patches = 'recomb-patches-%s.*' % branch
        infos = self.replica_remote.get_approved_change_infos(branch_patches)
        for change_number in infos:
            recombination = Recombination(self,infos=infos[change_number])
            self.merge_replica_mutation_recombination(recombination)

    def merge_replica_mutation_recombination(self, recombination):
        if recombination.patches.status != "MERGED":
            if not recombination.patches.approve():
                log.error("Originating change approval failed")
                return False
            if not recombination.patches.submit():
                log.error("Originating change submission failed")
                return False
        if recombination.status != "MERGED":
            return recombination.submit()
        else:
            log.warning("Recombination already submitted")
        # update existing recombination from upstream changes
        # for change in midstream_gerrit.gather_current_merges(patches_revision):
        #    local_repo.merge_fortests(change['upstream_revision'], patches_revision)
        #    upload new patchset with updated master-patches and updated message on midstream changes with old master_patches

    def check_approved_recombinations(self, recombination=None):
        if recombination:
            if recombination.type == 'replica-mutation':
                self.merge_replica_mutation_recombination(recombination)
            elif recombination.type == 'original-diversity':
                return self.scan_original_distance(branch=recombination.original.branch)
        else:
            for branch in self.original_branches:
                self.scan_patches_branch(branch)
                self.scan_original_distance(branch)


    def download_untested_recombinations(self, download_dir, recomb_id=None):
        dirlist = self.replica_remopte.download_review(download_dir, recomb_id=recomb_id)
        changes_infos = list()
        if dirlist:
            for test_dir in dirlist:
                project_shortname = re.sub('puppet-','', self.project_name)
                changes_infos.append({ 'project_name': self.project_name, 'project_shortname': project_shortname, 'recombination_dir': test_dir})
        else:
            log.info("Project '%s': no untested recombinations" % self.project_name)
        return changes_infos

    def delete_service_branches(self):
        # cleanup github repos from recomb branches WIP
        log.info("Deleting recomb branches from mirror for project %s" % self.project_name)
        service_branches = self.underlayer.list_branches('replica-mirror', pattern='recomb*')
        self.underlayer.delete_remote_branches('replica-mirror', service_branches)

    def delete_stale_branches(self):
        recomb_active_branches = list()
        recomb_all_branches = self.underlayer.list_branches('replica', pattern='recomb*')
        infos = self.replica_remote.query_changes_json('"status:open AND project:%s"' % self.replica_project['name'])
        for info in infos:
            recomb_active_branches.append(info['branch'])
        log.debugvar('recomb_active_branches')
        recomb_stale_branches = list(set(recomb_all_branches) - set(recomb_active_branches))
        log.debugvar('recomb_stale_branches')
        self.underlayer.delete_remote_branches('replica', recomb_stale_branches)

import sys
import os
import yaml
import re
from colorlog import log


class DecodeError(Exception):
    pass

class UploadError(Exception):
    pass

class SubmitError(Exception):
    pass

class PushMergeError(Exception):
    pass

class AttemptError(Exception):
    pass

class Change(object):

    def __init__(self, remote=None, infos=None):
        if infos:
            self.revision = infos['revision']
            self.branch = infos['branch']
            if 'id' in infos:
                self.uuid = infos['id']
            elif 'uuid' in infos:
                self.uuid = infos['uuid']
            self.parent = infos['parent']
            self.previous_commit = infos['parent']
            if 'number' in infos:
                self.number = infos['number']
            if 'status' in infos:
                self.status = infos['status']
            if 'subject' in infos:
                self.subject = infos['subject']
            self.project_name = infos['project-name']
            if 'topic' in infos:
                self.topic = infos['topic']
            if 'patchset_number' in infos:
                self.patchset_number = infos['patchset_number']
            if 'patchset_revision' in infos:
                self.patchset_revision = infos['patchset_revision']
        else:
            self.branch = None
            self.topic = None

        self.remote = None
        if remote:
            self.remote = remote

    def submit(self):
        return self.remote.submit_change(self.number, self.patchset_number)

    def approve(self):
        return self.remote.approve_change(self.number, self.patchset_number)

    def reject(self):
        return self.remote.reject_change(self.number, self.patchset_number)

    def upload(self):
        result_change = self.remote.upload_change(self.branch, self.topic)
        if result_change:
            self.number = result_change.number
            self.uuid = result_change.uuid
            self.status = result_change.status
            log.info("Recombination with Change-Id %s uploaded in replica gerrit with number %s" % (self.uuid, self.number))
        else:
            return False
        return True


class Recombination(Change):

    def __init__(self, underlayer, recomb_type=None, remote=None, replica_remote=None, original_remote=None, patches_remote=None, infos=None):
        self.underlayer = underlayer
        self.removed_commits = None
        if original_remote:
            self.original_remote = original_remote
        if replica_remote:
            self.replica_remote = replica_remote
        if patches_remote:
            self.patches_remote = patches_remote
        if infos:
            super(Recombination, self).__init__(remote=remote, infos=infos)
            self.decode_subject(original_remote=original_remote, replica_remote=replica_remote, patches_remote=patches_remote)
        else:
            super(Recombination, self).__init__(remote=remote)
            self.recomb_type = recomb_type
            self.subject = None
            self.patches_queue = None
            self.own_merge_commit = None
            self.replica_revision = None
            if self.recomb_type == 'replica-mutation':
                try:
                    self.replica_change = Change(remote=replica_remote)
                    self.mutation_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            elif self.recomb_type == 'original-diversity':
                try:
                    self.original_change = Change(remote=original_remote)
                    self.diversity_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            elif self.recomb_type == 'evolution-diversity':
                try:
                    self.evolution_change = Change(remote=original_remote)
                    self.diversity_change = Change(remote=patches_remote)
                except NameError:
                    raise MissingInfoError
            self.strategy = strategy


    def decode_subject(self, original_remote=None, replica_remote=None, patches_remote=None):
        log.debug(self.subject)
        try:
            recomb_data = yaml.load(self.subject)
        except ValueError:
            log.error("Subject not in yaml")
            raise DecodeError

        recomb_sources = recomb_data['sources']
        header = recomb_data['Recombination']

        recomb_header = header.split('/')[0]
        self.recomb_type = re.sub(':[a-zA-Z0-9]{6}', '',recomb_header)
        self.replication_strategy = recomb_data['replication-strategy']
        if self.recomb_type == 'replica-mutation':
            self.replica_change = self.underlayer.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            self.mutation_change = self.patches_remote.get_changes_by_id([recomb_sources['patches']['id']])[recomb_sources['patches']['id']]
        elif self.recomb_type == 'original-diversity':
            self.original_change = self.original_remote.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            # Set real commit as revision
            self.original_change.revision = recomb_sources['main']['revision']
            self.diversity_change = self.underlayer.get_changes_by_id([recomb_sources['patches']['id']], branch=recomb_sources['patches']['branch'])[recomb_sources['patches']['id']]
        elif self.recomb_type == 'evolution-diversity':
            self.evolution_change = self.original_remote.get_changes_by_id([recomb_sources['main']['id']], branch=recomb_sources['main']['branch'])[recomb_sources['main']['id']]
            # Set real commit as revision
            self.evolution_change.revision = recomb_sources['main']['revision']
            self.diversity_change = self.underlayer.get_changes_by_id([recomb_sources['patches']['id']], branch=recomb_sources['patches']['branch'])[recomb_sources['patches']['id']]

        if self.replication_strategy == 'change-by-change':
            if 'target-replacement-branch' not in recomb_data:
                recomb_data['target-replacement-branch'] = re.sub('recomb', 'target', self.branch)
            self.target_replacement_branch = recomb_data['target-replacement-branch']

        self.set_recomb_data()

    def set_recomb_data(self):
        if self.recomb_type == 'original-diversity':
            main_source = self.original_change
            patches_source = self.diversity_change
            main_source_name = 'original'
            patches_source_name = 'diversity'
        elif self.recomb_type == 'replica-mutation':
            main_source = self.replica_change
            patches_source = self.mutation_change
            main_source_name = 'replica'
            patches_source_name = 'mutation'
        if self.recomb_type == 'evolution-diversity':
            main_source = self.evolution_change
            patches_source = self.diversity_change
            main_source_name = 'evolution'
            patches_source_name = 'diversity'
        else:
            log.critical("Unknown Recombination type")
            raise RecombinationTypeError

        self.recomb_data = {
            "sources": {
                "main": {
                    "name": main_source_name,
                    "branch": main_source.branch,
                    "revision": main_source.revision,
                    "id": main_source.uuid
                },
                "patches" : {
                    "name": patches_source_name,
                    "branch": patches_source.branch,
                    "revision": patches_source.revision,
                    "id": patches_source.uuid
                }
            }
        }
        if self.target_replacement_branch:
            self.recomb_data['target-replacement-branch'] = self.target_replacement_branch
        self.recomb_data['strategy'] = self.strategy

    def attempt(self):
        # patches_revision = self.project.get_revision(self.patches.revision)
        try:
            self.set_recomb_data()
            self.underlayer.recombine(self.recomb_data, self.branch)
            log.debug("Merge check with master-patches successful, ready to create review")
        except AttemptError:
            raise AttemptError

    def sync_replica(self, replica_branch):
        if self.recomb_type == 'original-diversity':
            log.info("Advancing replica branch %s to %s " % (replica_branch, self.original_change.revision))
            self.underlayer.sync_replica(replica_branch, self.original_change.revision)
        else:
            raise RecombinationTypeError

    def handle_status(self):
        if self.status == "MISSING":
            try:
                self.attempt()
            except AttemptError:
                log.error("Recombination attempt unsuccessful")
                raise UploadError
            try:
                self.upload()
            except UploadError:
                log.error("upload of recombination with change %s did not succeed. Exiting" % self.uuid)
                raise UploadError
        if self.status == "APPROVED":
            if self.recomb_type == 'original-diversity'
                try:
                    self.sync_replica(replica_branch)
                except RecombinationSyncReplicaError:
                    log.error("Replica could not be synced")
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
                try:
                    self.submit()
                except RecombinationSubmitError:
                    log.error("Recombination not submitted")
            elif self.recomb_type == 'evolution-diversity':
                if self.backportid:
                    backport = self.patches.get_changes_by_id(backportid)
                    if backport.status == "MERGED":
                        try:
                            self.submit()
                        except RecombinationSubmitError:
                            log.error("Recombination not submitted")
                else:
                    backportid = self.patches.search_backport()
                    if not backportid:
                        try:
                            self.patches_remote.upload()
                        except UploadError:
                            log.error("Mannaggai")
            elif self.recomb_type == 'replica-mutation':
                if self.mutation_change.status != "MERGED":
                    try:
                        self.mutation_change.approve()
                        self.mutation_change.submit()
                    except RecombinationApproveError:
                        log.error("Originating change approval failed")
                    except RecombinationSubmitError:
                        log.error("Originating change submission failed")
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
                if self.status != "MERGED":
                    self.submit()
                else:
                    log.warning("Recombination already submitted")
                # update existing recombination from upstream changes
                # for change in midstream_gerrit.gather_current_merges(patches_revision):
                #    local_repo.merge_fortests(change['upstream_revision'], patches_revision)
                #    upload new patchset with updated master-patches and updated message on midstream changes with old master_patches
        if self.status == "MERGED":
            if self.replication_type == "change-by-change":
                log.warning("branch is out of sync with original")
                self.sync_replica(replica_branch)
                self.underlayer.update_target_branch(self.target_replacement_branch, self.target_branch)
            elif self.replication_type == "lock-and-backports":
                pass
        elif self.status == "PRESENT"
            pass

# Performs sanity check for midstream
import json
import pprint
import re
import os
from ..colorlog import log
from collections import OrderedDict
from shellcommand import shell
from ..datastructures import Change, Recombination


class Gerrit(object):

    def __init__(self, name, host, project_name):
        self.host = host
        self.name = name
        self.project_name = project_name
        self.url = "ssh://%s/%s" % (host, project_name)

    def query_changes_json(self, query):
        changes_infos = list()
        cmd = shell('ssh %s gerrit query --current-patch-set --format json %s' % (self.host,query))
        log.debug(pprint.pformat(cmd.output))
        for change_json in cmd.output:
            if change_json !='':
                change = json.loads(change_json)
                if "type" not in change or change['type'] != 'stats':
                    changes_infos.append(change)

        log.debug("end query json")
        return changes_infos

    def approve_change(self, number, patchset):
        shell('ssh %s gerrit review --code-review 2 --verified 1 %s,%s' % (self.host, number, patchset))

    def reject_change(self, number, patchset):
        shell('ssh %s gerrit review --code-review -2 --verified -1 %s,%s' % (self.host, number, patchset))

    def submit_change(self, number, patchset):
        shell('ssh %s gerrit review --publish --project %s %s,%s' % (self.host, self.project_name, number, patchset))
        shell('ssh %s gerrit review --submit --project %s %s,%s' % (self.host, self.project_name, number, patchset))
        cmd = shell('ssh %s gerrit query --format json "change:%s AND status:merged"' % (self.host, number))
        if cmd.output[:-1]:
            return True
        return False

    def upload_change(self, branch, topic):
        shell('git checkout %s' % branch)
        cmd = shell('git review -D -r %s -t "%s" %s' % (self.name, topic, branch))
        for line in cmd.output:
            if 'Nothing to do' in line:
                log.debug("trying alternative upload method")
                shell("git push %s HEAD:refs/drafts/%s/%s" % (self.name, branch, topic))
                break
        cmd = shell('ssh %s gerrit query --current-patch-set --format json "topic:%s AND status:open"' % (self.host, topic))
        shell('git checkout parking')
        log.debug(pprint.pformat(cmd.output))
        if not cmd.output[:-1]:
            shell('git push replica :%s' % branch)
            return None
        gerrit_infos = json.loads(cmd.output[:-1][0])
        infos = self.normalize_infos(gerrit_infos)
        change = Change(infos=infos)
        return change

    def get_query_string(self, criteria, ids, branch=None):
        query_string = '\(%s:%s' % (criteria, ids[0])
        for change in ids[1:]:
            query_string = query_string + " OR %s:%s" % (criteria,change)
        query_string = query_string + "\) AND project:%s AND NOT status:abandoned" % (self.project_name)
        if branch:
            query_string = query_string + " AND branch:%s " % branch
        log.debug("search in upstream gerrit: %s" % query_string)
        return query_string

    @staticmethod
    def approved(infos):
        if not infos['approvals']:
            code_review = 0
            verified = 0
        else:
            code_review = -2
            verified = -1
            for approval in range(0, len(infos['approvals'])):
                patchset_approval = infos['approvals'][approval]
                if patchset_approval['type'] == 'Code-Review':
                    code_review = max(code_review, int(patchset_approval['value']))
                if patchset_approval['type'] == 'Verified':
                    verified = max(verified, int(patchset_approval['value']))
        log.debug("change %s max approvals: CR: %d, V: %d" % (infos['id'], code_review, verified))
        if code_review >= 2 and verified >= 1:
           log.debug("change %s approved for submission if all precedent are approved too")
           return True
        return False

    def normalize_infos(self, gerrit_infos):
        infos = {}
        infos['revision'] = gerrit_infos['currentPatchSet']['revision']
        infos['parent'] = gerrit_infos['currentPatchSet']['parents'][0]
        infos['patchset_number'] = gerrit_infos['currentPatchSet']['number']
        infos['patchset_revision'] = gerrit_infos['currentPatchSet']['revision']
        infos['project-name'] = gerrit_infos['project']
        infos['branch'] = gerrit_infos['branch']
        infos['id'] = gerrit_infos['id']
        infos['previous-commit'] = infos['parent']
        infos['subject'] = gerrit_infos['commitMessage']
        if 'topic' in gerrit_infos:
            infos['topic'] = gerrit_infos['topic']
        infos['number'] = gerrit_infos['number']
        infos['status'] = gerrit_infos['status']
        infos['approvals'] = None
        if 'approvals' in gerrit_infos['currentPatchSet']:
            infos['approvals'] = gerrit_infos['currentPatchSet']['approvals']
        if gerrit_infos['status'] == 'NEW' or gerrit_infos['status'] == 'DRAFT':
            infos['status'] = 'PRESENT'
        if gerrit_infos['status'] != "MERGED" and self.approved(infos):
            infos['status'] = "APPROVED"

        return infos

    def get_changes_info(self, search_values, search_field='change', key_field='id', branch=None):
        infos = dict()
        query_string = self.get_query_string(search_field, search_values, branch=branch)
        changes_infos = self.query_changes_json(query_string)

        for gerrit_infos in changes_infos:
            norm_infos = self.normalize_infos(gerrit_infos)
            infos[norm_infos[key_field]] = norm_infos

        return infos

    def get_changes_by_id(self, search_values, search_field='change', key_field='id', branch=None):
        changes = dict()
        query_string = self.get_query_string(search_field, search_values, branch=branch)
        changes_infos = self.query_changes_json(query_string)

        for gerrit_infos in changes_infos:
            infos = self.normalize_infos(gerrit_infos)
            change = Change(infos=infos, remote=self)
            changes[infos[key_field]] = change

        return changes

    def get_recombinations_by_id(self, search_values, search_field='change', key_field='id', branch=None):
        recombinations = dict()
        query_string = self.get_query_string(search_field, search_values, branch=branch)
        recombinations_infos = self.query_changes_json(query_string)

        for gerrit_infos in recombinationss_infos:
            infos = self.normalize_infos(gerrit_infos)
            recomb = Recombination(infos=infos, remote=self)
            recombinations[infos[key_field]] = recomb

        return changes

    def get_original_ids(self, commits):
        ids = OrderedDict()
        for commit in commits:
            main_revision = commit['hash']
            # in gerrit, merge commits do not have Change-id
            # if commit is a merge commit, search the second parent for a Change-id
            if len(commit['parents']) != 1:
                commit = commit['subcommits'][0]
            found = False
            for line in commit['body']:
                if re.search('Change-Id: ', line):
                    ids[re.sub(r'\s*Change-Id: ', '', line)] = main_revision
                    found = True
            if not found:
                log.warning("no Change-id found in commit %s or its ancestors" % main_revision)

        return ids

    def get_untested_recombs_infos(self, recomb_id=None, branch=''):
        if recomb_id:
            change_query = 'AND change:%s' % recomb_id
        else:
            change_query = ''
        query = "'owner:self AND project:%s %s AND branch:^recomb-.*-%s.* AND ( NOT label:Code-Review+2 AND NOT label:Verified+1 AND status:open)'"  % (self.project_name, change_query, branch)
        untested_recombs = self.query_changes_json(query)
        log.debugvar('untested_recombs')
        return untested_recombs

    def get_approved_change_infos(self, branch):
        infos = dict()
        query_string = "'owner:self AND project:%s AND branch:^%s AND label:Code-Review+2 AND label:Verified+1 AND status:open'" % (self.project_name, branch)
        changes_infos = self.query_changes_json(query_string)

        for gerrit_infos in changes_infos:
            norm_infos = self.normalize_infos(gerrit_infos)
            infos[norm_infos['number']] = norm_infos

        return infos


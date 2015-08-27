# Performs sanity check for midstream
import re
import sys
import os
from shellcommand import shell
from collections import OrderedDict
from ..datastructures import Change
from gerrit import Gerrit
from ..colorlog import log

class Git(object):

    def get_revision(self, revision_name):
        cmd = shell('git rev-parse %s' % revision_name)
        revision = cmd.output[0].rstrip('\n')
        return revision

    def get_commits(self, revision_start, revision_end):
        log.debug("Interval: %s..%s" % (revision_start, revision_end))

        os.chdir(self.directory)
        shell('git checkout parking')
        cmd = shell('git log --topo-order --reverse --pretty=raw %s..%s --no-merges' % (revision_start, revision_end))

        return cmd.output

    def get_merge_commits(self, revision_start, revision_end):
        merge_commits = []
        cmd = shell('git log --topo-order --reverse --pretty=format:"%%H %%P" %s..%s --merges' % (revision_start, revision_end))
        for line in map(lambda line: line.rstrip('\n'), cmd.output):
            merge = {}
            merge['commit'] = line.split(' ')[0]
            merge['parents'] = line.split(' ')[1:]
            merge_commits.append(merge)

        return merge_commits

    def get_changes_by_id(self, search_values, search_field='commit', key_field='revision', branch=None):
        changes = dict()
        os.chdir(self.directory)
        for revision in search_values:
            infos = {}
            cmd = shell('git show -s --pretty=format:"%%H %%P" %s' % (revision))
            infos['id'], infos['parent'] = cmd.output[0].split(' ')[0:2]
            infos['revision'] = infos['id']
            if not branch:
                log.error("for git repositories you must specify a branch")
                sys.exit(1)
            else:
                infos['branch'] = branch
            infos['project-name'] = self.project_name
            change = Change(infos=infos, repo=self)
            changes[infos[key_field]] = change
        return changes


class LocalRepo(Git):

    def __init__(self, project_name, directory):
        self.directory = directory
        self.project_name = project_name
        self.remotes = {}
        try:
            os.mkdir(self.directory)
        except OSError:
            pass
        os.chdir(self.directory)
        shell('git init')
        shell('git checkout --orphan parking')
        shell('git commit --allow-empty -a -m "parking"')
        shell('scp -p gerrithub:hooks/commit-msg .git/hooks/')

    def addremote(self, name, url):
        os.chdir(self.directory)
        shell('git remote add -f %s %s' % (name, url))

    def add_gerrit_remote(self, name, location, project_name):
        self.remotes[name] = Gerrit(name, location, project_name)
        self.addremote(name, self.remotes[name].url)

    def add_git_remote(self, name, location, project_name):
        self.remotes[name] = RemoteGit(name, location, self.directory, project_name)
        self.addremote(name, self.remotes[name].url)

    def list_branches(self, remote_name, pattern=''):
        cmd = shell('git for-each-ref --format="%%(refname)" refs/remotes/%s/%s | sed -e "s/refs\/remotes\/%s\///"' % (remote_name, pattern, remote_name))
        return cmd.output

    def track_branch(self, branch, remote_branch):
        shell('git checkout parking')
        shell('git branch --track %s %s' % (branch, remote_branch))

    def delete_branch(self, branch):
        shell('git checkout parking')
        cmd = shell('git branch -D %s' % branch)

    def delete_remote_branches(self, remote_name, branches):
        for branch in branches:
            shell('git push %s :%s' % (remote_name,branch))

    def recombine(self, commit_message_filename, pick_branch, recombination_branch, starting_revision, pick_revision, merge_revision):
        shell('git fetch replica')
        shell('git fetch original')
        retry_merge = True
        first_try = True
        while retry_merge:
            shell('git checkout %s' % pick_branch)

            shell('git checkout -B %s %s' % (recombination_branch, starting_revision))

            # TODO: handle exception: two identical changes in row creates no
            # diff, so no commit can be created
            log.info("Creating remote disposable branch on replica")
            shell('git push replica HEAD:%s' % recombination_branch)

            cmd = shell("git merge --squash --no-commit %s %s" % (pick_revision, merge_revision))

            shell('git status')

            if cmd.returncode != 0:
                log.warning("Merge check with master-patches failed")
                resolution = False
                if first_try:
                    log.warning("Trying automatic resolution")
                    resolution = self.resolve_conflicts(cmd.output)
                    first_try = False
                    if not resolution:
                        shell('git push replica :%s' % recombination_branch)
                        log.error("Resolution failed. Exiting")
                        os.unlink(commit_message_filename)
                        sys.exit(1)
                    else:
                        # reset, resolve, and retry
                        shell('git reset --hard %s' % recombination_branch)
                        shell('git checkout %s' % pick_branch)
                        shell('git branch -D %s' % recombination_branch)
                        shell('git push replica :%s' % recombination_branch)
                else:
                    shell('git push replica :%s' % recombination_branch)
                    os.unlink(commit_message_filename)
                    log.critical("Merge failed even after resolution. You're on your own, sorry. Exiting")
                    sys.exit(1)
            else:
                retry_merge = False

        shell("git commit -F %s" % (commit_message_filename))
        os.unlink(commit_message_filename)
        shell('git checkout %s' % pick_branch)

    def sync_replica(self, branch, commit):
        os.chdir(self.directory)
        shell('git fetch replica')
        shell('git branch --track replica-%s remotes/replica/%s' % (branch, branch))
        shell('git checkout replica-%s' % branch)
        cmd = shell('git merge --ff-only %s' % commit)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error merging. Exiting")
            sys.exit(1)
        cmd = shell('git push replica HEAD:%s' % branch)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error pushing the merge. Exiting")
            sys.exit(1)
        shell('git checkout parking')
        shell('git branch -D replica-%s' % branch)
        return True

    def push_merge(self, recombination_attempt):
        # FIXME: checkout from merge commit if it exists, not the simple commit
        branch, starting_revision, merge_revision = recombination_attempt
        shell('git fetch replica')
        shell('git branch --track replica-%s remotes/replica/%s' % (branch, branch))
        shell('git checkout replica-%s' % branch)
        shell('git checkout -B %s-tag %s' % (branch, starting_revision))
        shell("git merge %s" % (merge_revision))

        shell('git push -f replica HEAD:%s-tag' % (branch))

        shell('git checkout parking')
        shell('git branch -D %s-tag' % branch)
        shell('git branch -D replica-%s' % branch)

    def resolve_conflicts(self, output):
        return True


class RemoteGit(Git):

    def __init__(self, name, location, directory, project_name):
        self.name = name
        self.url = "git@%s:%s" % (location, project_name)
        self.directory = directory
        self.project_name = project_name

    def get_recombinations(self, commits):
        recombinations = OrderedDict()
        for line in commits:
            if re.search('^commit ', line):
                recombinations[re.sub(r'^commit ', '', line.rstrip('\n'))] = None

        return recombinations



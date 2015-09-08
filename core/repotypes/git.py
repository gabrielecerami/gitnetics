import sys
import os
import tempfile
import yaml
import shutil
from shellcommand import shell
from collections import OrderedDict
from ..datastructures import Change
from gerrit import Gerrit
from ..colorlog import log, logsummary

class Git(object):

    def get_revision(self, revision_name):
        cmd = shell('git rev-parse %s' % revision_name)
        revision = cmd.output[0].rstrip('\n')
        return revision

    def get_commits(self, revision_start, revision_end, first_parent=True, reverse=True):
        options = ''
        commit_list = list()
        log.debug("Interval: %s..%s" % (revision_start, revision_end))

        os.chdir(self.directory)
        shell('git checkout parking')
        if reverse:
            options = '%s --reverse' % options
        if first_parent:
            options = '%s --first-parent' % options
        cmd = shell('git rev-list %s --pretty="%%H" %s..%s | grep -v ^commit' % (options, revision_start, revision_end))

        for commit_hash in cmd.output:
            commit = dict()
            commit['hash'] = commit_hash
            cmd = shell('git show -s --pretty="%%P" %s' % commit_hash)
            commit['parents'] = cmd.output[0].split(' ')
            cmd = shell('git show -s --pretty="%%B" %s' % commit_hash)
            commit['body'] = cmd.output
            if len(commit['parents']) > 1:
                commit['subcommits'] = self.get_commits(commit['parents'][0], commit['parents'][1], first_parent=False, reverse=False)

            commit_list.append(commit)

        return commit_list

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
            change = Change(infos=infos, remote=self)
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
        # TODO: remove all local branches
        # git for-each-ref --format="%(refname)" refs/heads | sed -e "s/refs\/heads//"
        # for branch in local_branches:
        #    shell('git branch -D %s' % branch)
        cmd = shell('git checkout parking')
        if cmd.returncode != 0:
            shell('git checkout --orphan parking')
            shell('git commit --allow-empty -a -m "parking"')


    def addremote(self, name, url):
        os.chdir(self.directory)
        cmd = shell('git remote | grep ^%s$' % name)
        if cmd.returncode != 0:
            shell('git remote add %s %s' % (name, url))
        cmd = shell('git fetch %s' % (name))
        if cmd.returncode != 0:
            raise RemoteFetchError

    def add_gerrit_remote(self, name, location, project_name):
        self.remotes[name] = Gerrit(name, location, project_name)
        self.addremote(name, self.remotes[name].url)
        shell('git fetch %s +refs/changes/*:refs/remotes/%s/changes/*' % (name, name))
        shell('scp -p %s:hooks/commit-msg .git/hooks/' % location)

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

    def resolve_conflicts(self, output):
        pass
    def recombine(self, recomb_data, recombination_branch):

        shell('git fetch replica')
        shell('git fetch original')

        pick_revision = recomb_data['sources']['main']['revision']
        #pick_branch = main_source.branch
        cmd = shell('git rev-parse %s~1' % pick_revision)
        starting_revision = cmd.output[0]
        merge_revision = recomb_data['sources']['patches']['revision']
        main_source_name = recomb_data['sources']['main']['name']
        patches_source_name = recomb_data['sources']['patches']['name']
        branch = recomb_data['sources']['main']['branch']
        patches_branch = recomb_data['sources']['patches']['branch']

        # Branch prep
        # local patches branch
        shell('git checkout -B replica-%s-base %s' % patches_branch, merge_revision)
        # local recomb branch
        shell('git checkout -B %s %s' % (recombination_branch, starting_revision))
        log.info("Creating remote disposable branch on replica")
        cmd = shell('git push replica HEAD:%s' % recombination_branch)
        if cmd.returncode != 0:
            raise PushError


        attempt_number = 1
        theres_hope = True
        patches_removal_queue = list()

        merge = shell("git merge --stat --squash --no-commit %s %s" % (pick_revision, merge_revision))

        if merge.returncode != 0
            shell("firs attempt at merge failed")
            cmd = shell('git status --porcelain')
            conflict_status = cmd.output
            cmd = shell('git merge-base %s %s' % (pick_revision, merge_revision))
            ancestor = cmd.output[0]
            cmd = shell('git rev-list --reverse --first-parent %s..remotes/replica/%s' % (ancestor, recomb_data['sources']['patches']['branch']))
            patches_removal_queue = cmd.output
            for commit in cmd.output:
                cmd = shell('git show --pretty=format:"" %s' % commit)
                diff = cmd.output.joing('\n)
                patches_commit[hashlib.sha1(diff)] = commit
            if patches_removal_queue:
               log.warning("attempting automatic resolution")
            else:
                log.error("automatic resolution impossible")
        else:
            log.info("Merge successful")

        while merge.returncode != 0 and patches_removal_queue:
            attempt_number += 1

            shell('git reset --hard %s' % recombination_branch)

            shell('git checkout recomb_attempt-%s-base' % patches_branch)
            retry_branch = 'recomb_attempt-%s-retry_%s' % (patches_branch, attempt_number)
            shell('git checkout -b %s' % (retry_branch)
            # Rebasing change all the commits hashes after "commit"
            next_patch_toremove = patches_removal_queue.pop(0)
            shell('git rebase -p --onto %s^ %s' % (next_patch_toremove, next_patch_toremove))
            cmd = shell('git rev-parse %s' % retry_branch)
            retry_merge_revision = cmd.output

            shell('git checkout %s' % recombination_branch)
            merge = shell("git merge --stat --squash --no-commit %s %s" % (pick_revision, retry_merge_revision))

            if merge.returncode != 0:
                log.warning("automatic resolution attempt %d failed" % attempt_number)
                cmd = shell('git status --porcelain')
                conflict_status = cmd.output
                if prev_conflict_status != conflict_status:
                    removed_commits.append(next_patch_toremove)
                    # removing this patch did not solve everything, but did
                    # something nonetheless, keep it removed and try to remove
                    # something else too
                    # change the base, recalculate every patch commit hash since
                    # rebase changed everything
                    shell('git branch -D replica-%s-base')
                    shell('git checkout -B replica-%s-base %s' % patches_branch, retry_merge_revision)
                    cmd = shell('git rev-list --reverse --first-parent %s..%s' % (ancestor, retry_branch))
                    patches_removal_queue = cmd.output
            else:
                logsummary.warning("automatic resolution attempt %d succeeded" % attempt_number)
                removed_commits.append(next_patch_toremove)
                logsummary.info("removed commits")
                logsummary.info(removed_commits)
                logsummary.info("removed commits (commit hash relative to starting patches branch)")
                logsummary.info(removed_commits_deashed)

        if merge.returncode != 0:
            logsummary.error("automatic resolution failed")
            shell('git push replica :%s' % recombination_branch)
        else:
            logsummary("Recombination successful")
            recomb_data['sources']['patches']['removed_commits'] = removed_commits
            fd, commit_message_filename = tempfile.mkstemp(prefix="recomb-", suffix=".yaml", text=True)
            os.close(fd)
            with open(commit_message_filename, 'w') as commit_message_file:
                # We have to be sure this is the first line in yaml document
                commit_message_file.write("Recombination: %s:%s-%s:%s/%s\n\n" % (main_source_name, pick_revision[:6], patches_source_name, merge_revision[:6], recomb_data['sources']['main']['branch']))
                yaml.safe_dump(recomb_data, commit_message_file, default_flow_style=False, indent=4, canonical=False, default_style=False)

            cmd = shell("git commit -F %s" % (commit_message_filename))
            # If two changes with the exact content are merged upstream
            # the above command will succeed but nothing will be committed.
            # and recombination upload will fail due to no change.
            # this assures that we will always commit something to upload
            for line in cmd.output:
                if 'nothing to commit' in line:
                    shell("git commit --allow-empty -F %s" % (commit_message_filename))
                    logsummary.warning('Contents in commit %s have been merged twice in upstream' % pick_revision)
                    break
            os.unlink(commit_message_filename)

        git checkout parking
        git branch -D recombination branch

    def remove_commits(self, branch, removed_commits, remote=''):
        shell('git branch --track %s%s %s' (remote, branch, branch))
        shell('git checkout %s' % branch)
        for commit in removed_commits:
            cmd = shell('git show -s %s' % commit)
            if cmd.output:
                shell('git rebase -p --onto %s^ %s' % (commit, commit))
                log.info('removed commit %s from branch %s' % (commit, branch))
            else:
                break
        if remote:
            shell('git push -f %s HEAD:%s' % (remote, branch))
            log.info('Pushed modified branch on remote')
        shell('git checkout parking')

    def sync_replica(self, replica_branch, revision):
        os.chdir(self.directory)
        shell('git fetch replica')
        shell('git branch --track replica-%s remotes/replica/%s' % (replica_branch, replica_branch))
        shell('git checkout replica-%s' % replica_branch)
        cmd = shell('git merge --ff-only %s' % revision)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error merging. Exiting")
            raise MergeError
        cmd = shell('git push replica HEAD:%s' % replica_branch)
        if cmd.returncode != 0:
            log.debug(cmd.output)
            log.critical("Error pushing the merge. Exiting")
            raise PushError
        shell('git checkout parking')
        shell('git branch -D replica-%s' % replica_branch)

    def update_target_branch(self, replica_branch, patches_branch, target_branch):
        shell('git fetch replica')
        shell('git checkout -B new-%s remotes/replica/%s' % (target_branch, replica_branch))
        shell("git merge remotes/replica/%s" % (patches_branch))

        shell('git push -f replica HEAD:%s' % (target_branch))

        shell('git checkout parking')
        shell('git branch -D new-%s' % target_branch)


    def fetch_recomb(self, fetch_dir, untested_recombs, remote_name):
        dirlist = dict()
        os.chdir(self.directory)
        shell('git checkout parking')
        if not untested_recombs:
            return None
        else:
            for recomb in untested_recombs:
                recomb_dir = "%s/%s" % (fetch_dir, recomb['number'])
                try:
                    os.makedirs(recomb_dir)
                except OSError:
                    pass
                recomb_branch = 'remotes/%s/changes/%s/%s/%s' % (remote_name, recomb['number'][-2:], recomb['number'], recomb['currentPatchSet']['number'])
                shell('git checkout %s' % recomb_branch)
                shell('cp -a . %s' % recomb_dir)
                shutil.rmtree("%s/.git" % recomb_dir, ignore_errors=True)
                shell('git checkout parking')
                dirlist[recomb['number']] = recomb_dir
        return dirlist



class RemoteGit(Git):

    def __init__(self, name, location, directory, project_name):
        self.name = name
        self.url = "git@%s:%s" % (location, project_name)
        self.directory = directory
        self.project_name = project_name

    def get_original_ids(self, commits):
        ids = dict()
        for commit in commits:
            ids[commit['hash']] = commit['hash']
        return ids



import difflib
import hashlib
import sys
import os
import tempfile
import yaml
import shutil
from shellcommand import shell
from ..datastructures import Change
from gerrit import Gerrit
from ..colorlog import log, logsummary

class PushError(Exception):
    pass

class MergeError(Exception):
    pass

class RemoteFetchError(Exception):
    pass

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


    def addremote(self, name, url, fetch=True):
        os.chdir(self.directory)
        cmd = shell('git remote | grep ^%s$' % name)
        if cmd.returncode != 0:
            shell('git remote add %s %s' % (name, url))
        if fetch:
            cmd = shell('git fetch %s' % (name))
            if cmd.returncode != 0:
                raise RemoteFetchError

    def add_gerrit_remote(self, name, location, project_name, fetch=True):
        self.remotes[name] = Gerrit(name, location, project_name)
        self.addremote(name, self.remotes[name].url, fetch=fetch)
        if name == 'original':
            fetch=False
        if fetch:
            shell('git fetch %s +refs/changes/*:refs/remotes/%s/changes/*' % (name, name))
        try:
            os.stat(".git/hooks/commit-msg")
        except OSError:
            shell('scp -p %s:hooks/commit-msg .git/hooks/' % location)

    def add_git_remote(self, name, location, project_name, fetch=True):
        self.remotes[name] = RemoteGit(name, location, self.directory, project_name)
        self.addremote(name, self.remotes[name].url, fetch=fetch)

    def list_branches(self, remote_name, pattern=''):
        os.chdir(self.directory)
        cmd = shell('git for-each-ref --format="%%(refname)" refs/remotes/%s/%s | sed -e "s/refs\/remotes\/%s\///"' % (remote_name, pattern, remote_name))
        return cmd.output

    def track_branch(self, branch, remote_branch):
        os.chdir(self.directory)
        shell('git checkout parking')
        shell('git branch --track %s %s' % (branch, remote_branch))

    def delete_branch(self, branch):
        os.chdir(self.directory)
        shell('git checkout parking')
        shell('git branch -D %s' % branch)

    def delete_remote_branches(self, remote_name, branches):
        os.chdir(self.directory)
        for branch in branches:
            shell('git push %s :%s' % (remote_name,branch))

    def recombine(self, recomb_data, recombination_branch, permanent_patches=None):

        shell('git fetch replica')
        shell('git fetch original')

        pick_revision = recomb_data['sources']['main']['revision']
        #pick_branch = main_source.branch
        cmd = shell('git rev-parse %s~1' % pick_revision)
        starting_revision = cmd.output[0]
        merge_revision = recomb_data['sources']['patches']['revision']
        main_source_name = recomb_data['sources']['main']['name']
        patches_source_name = recomb_data['sources']['patches']['name']
        main_branch = recomb_data['sources']['main']['branch']
        patches_branch = recomb_data['sources']['patches']['branch']
        if recomb_data['strategy'] == "change-by-change":
            target_replacement_branch = recomb_data['target-replacement-branch']


        # Branch prep
        # local patches branch
        shell('git checkout -B recomb_attempt-%s-base %s' % (patches_branch, merge_revision))
        # local recomb branch
        shell('git checkout -B %s %s' % (recombination_branch, starting_revision))
        log.info("Creating remote disposable branch on replica")
        cmd = shell('git push replica HEAD:%s' % recombination_branch)
        if cmd.returncode != 0:
            raise PushError


        patches_removal_queue = list()

        merge = shell("git merge --stat --squash --no-commit %s %s" % (pick_revision, merge_revision))

        if merge.returncode != 0:
            attempt_number = 0
            patches_base = dict()
            removed_commits = list()
            log.error("first attempt at merge failed")
            cmd = shell('git status --porcelain')
            prev_conflict_status = cmd.output
            cmd = shell('git merge-base %s %s' % (pick_revision, merge_revision))
            ancestor = cmd.output[0]
            cmd = shell('git rev-list --reverse --first-parent %s..remotes/replica/%s' % (ancestor, recomb_data['sources']['patches']['branch']))
            patches_removal_queue = cmd.output
            if permament_patches:
                patches_removal_queue = patches_removal_queue - permanent_patches
            for commit in cmd.output:
                cmd = shell('git show --pretty=format:"" %s' % commit, show_stdout=False )
                diff = '\n'.join(cmd.output)
                hash_object = hashlib.sha1(diff)
                patches_base[hash_object.hexdigest()] = commit
            if patches_removal_queue:
               log.warning("attempting automatic resolution")
            else:
                log.error("automatic resolution impossible")
        else:
            log.info("Merge successful")


        retry_branch = None
        while merge.returncode != 0 and patches_removal_queue:
            attempt_number += 1

            shell('git reset --hard %s' % recombination_branch)

            shell('git checkout recomb_attempt-%s-base' % patches_branch)
            retry_branch = 'recomb_attempt-%s-retry_%s' % (patches_branch, attempt_number)
            shell('git checkout -b %s' % (retry_branch))
            # Rebasing changes all the commits hashes after "commit"
            next_patch_toremove = patches_removal_queue.pop(0)
            shell('git rebase -p --onto %s^ %s' % (next_patch_toremove, next_patch_toremove))
            cmd = shell('git rev-parse %s' % retry_branch)
            retry_merge_revision = cmd.output[0]

            shell('git checkout %s' % recombination_branch)
            merge = shell("git merge --stat --squash --no-commit %s %s" % (pick_revision, retry_merge_revision))

            if merge.returncode != 0:
                log.warning("automatic resolution attempt %d failed" % attempt_number)
                cmd = shell('git status --porcelain')
                conflict_status = cmd.output
                diff = difflib.Differ()
                same_status = list(diff.compare(prev_conflict_status, conflict_status))
                if not same_status:
                    removed_commits.append(next_patch_toremove)
                    # removing this patch did not solve everything, but did
                    # something nonetheless, keep it removed and try to remove
                    # something else too
                    # change the base, recalculate every patch commit hash since
                    # rebase changed everything
                    shell('git branch -D recomb_attempt-%s-base' % patches_branch)
                    shell('git checkout -B recomb_attempt-%s-base %s' % patches_branch, retry_merge_revision)
                    cmd = shell('git rev-list --reverse --first-parent %s..%s' % (ancestor, retry_branch))
                    patches_removal_queue = cmd.output
                    prev_conflict_status = conflict_status
                shell('git branch -D %s' % retry_branch)
            else:
                logsummary.warning("automatic resolution attempt %d succeeded" % attempt_number)
                removed_commits.append(next_patch_toremove)
                logsummary.info("removed commits")
                logsummary.info(removed_commits)
                logsummary.info("removed commits (commit hash relative to starting patches branch)")
                logsummary.info('removed_commits_deashed')


        if merge.returncode != 0:
            logsummary.error("automatic resolution failed")
            shell('git push replica :%s' % recombination_branch)
        else:
            logsummary.info("Recombination successful")
            # create new patches-branch
            if retry_branch:
                shell('git push replica :%s' % patches_branch)
                shell('git push replica %s:refs/heads/%s' % (retry_branch, patches_branch))
                shell('git branch -D %s' % retry_branch)

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

            if recomb_data['strategy'] == "change-by-change":
                # Create target branch replacement for this recombination
                shell('git checkout -B %s %s' % (target_replacement_branch, starting_revision))
                cmd = shell("git merge --log --no-edit %s %s" % (pick_revision, retry_merge_revision))
                if cmd.returncode == 0:
                    shell('git push replica HEAD:%s' % target_replacement_branch)

        shell('git checkout parking')
        #shell('git branch -D %s' % recombination_branch)
        shell('git branch -D recomb_attempt-%s-base' % patches_branch)
        if recomb_data['strategy'] == "change-by-change":
            shell('git branch -D %s' % target_replacement_branch)

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

    def update_target_branch(self, target_replacement_branch, target_branch):
        shell('git fetch replica')
        shell('git branch remotes/replica/%s' % (target_replacement_branch))
        shell('git push -f replica HEAD:%s' % (target_branch))
        shell('git checkout parking')
        shell('git push replica :%s ' % target_replacement_branch)

    def fetch_recomb(self, test_basedir, untested_recombs, remote_name):
        dirlist = dict()
        os.chdir(self.directory)
        change_dir = os.getcwd()
        shell('git checkout parking')
        for recomb in untested_recombs:
            recomb_dir = "%s/%s/code" % (self.project_name, recomb['number'])
            recomb_branch = 'remotes/%s/changes/%s/%s/%s' % (remote_name, recomb['number'][-2:], recomb['number'], recomb['currentPatchSet']['number'])
            shell('git checkout %s' % recomb_branch)
            shutil.rmtree(test_basedir + "/" + recomb_dir, ignore_errors=True)
            shutil.copytree(change_dir, test_basedir + "/" + recomb_dir, ignore=shutil.ignore_patterns('.git*'))
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



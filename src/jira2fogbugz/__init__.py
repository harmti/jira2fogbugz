#!/usr/bin/env python
import argparse
import sys
import io
import os
import time
import traceback
import string
import tempfile
from jira.client import JIRA
from jira.exceptions import JIRAError
from fogbugz import FogBugz
from fogbugz import FogBugzLogonError, FogBugzConnectionError

RECENTLY_ADDED_CASES = {}

FOGBUGZ_FIELDS = ('ixBug,ixPersonAssignedTo,ixPersonEditedBy,'
                  'sTitle,sLatestTextSummary,sProject,dtOpened,'
                  'sCategory,ixBugParent,hrsCurrEst,tags')


def fb_create_issue(fb, jira, jis, project, email_map, default_assignee):
    global RECENTLY_ADDED_CASES
    print("fb_create_issue: {}".format(jis.key))
    data = {}
    comments = []
    attachments = {}
    parent_issue = None

    if jis.key in RECENTLY_ADDED_CASES:
        fb_case_id = RECENTLY_ADDED_CASES[jis.key]
        # this case has been added already, so just return the fogbugz id
        print("Jira case {0} already added as Fogbugz case ID {1}".format(jis.key, fb_case_id))
        return fb_case_id

    # used for storing attachments
    tempdir = tempfile.mkdtemp()

    if not getattr(jis.fields, 'assignee', False):
        data['ixPersonAssignedTo'] = default_assignee
    else:
        data['ixPersonAssignedTo'] = email_map[jis.fields.assignee.emailAddress.lower()]
    data['sTitle'] = jis.fields.summary if jis.fields.summary else 'No title'
    description = ''
    if jis.fields.description:
        description = jis.fields.description + "\n\n(imported from jira case " + jis.key +")"
    #data['sEvent'] = description
    data['plugin_customfields_at_fogcreek_com_userxstoryxtextx816'] = description
    data['sProject'] = project
    # TODO: use pytz and convert timezone data properly
    data['dt'] = jis.fields.created.split('.')[0]+'Z'
    data['hrsCurrEst'] = 0
    tags = []
    if getattr(jis.fields, 'fixVersions', []):
        for ver in jis.fields.fixVersions:
            tags.append(ver.name)
    if getattr(jis.fields, 'labels', []):
        for label in jis.fields.labels:
            if label != u'export':
                tags.append(label)
    if tags:
        data['sTags'] = ','.join(tags)
    if getattr(jis.fields, 'timeoriginalestimate'):
        data['hrsCurrEst'] = int(jis.fields.timeoriginalestimate)/60/60
    # TODO: these are custom issue types in JIRA imported from Pivotal Tracker
    #       so you have to make a special mapping
    if jis.fields.issuetype.name in ('Story', 'Improvement', 'Epic', 'Theme', 'Technical task'):
        data['sCategory'] = 'Feature'
    elif jis.fields.issuetype.name in ('Bug'):
        data['sCategory'] = 'Bug'
    elif jis.fields.issuetype.name in ('Sub-task', 'Task'):
        data['sCategory'] = 'Task'
    elif jis.fields.issuetype.name in ('Improvement Item'):
        data['sCategory'] = 'Improvement item'
    elif jis.fields.issuetype.name in ('Documentation Item'):
        data['sCategory'] = 'Improvement item'
    elif jis.fields.issuetype.name in ('Testing Item'):
        data['sCategory'] = 'Testing item'
    else:
        raise Exception("Unknown issue type: {0}".format(jis.fields.issuetype.name))

    data['ixPriority'] = jis.fields.priority.id

    if getattr(jis.fields, 'attachment', None):
        for jira_attachment in jis.fields.attachment:
            attachment_path = tempdir + "/" + jira_attachment.filename
            with io.open(attachment_path, "wb") as f:
                f.write(jira_attachment.get())
            attachments[jira_attachment.filename] = io.open(attachment_path, "rb")

    if getattr(jis.fields, 'comment', None):
        for comment_id in jis.fields.comment.comments:
            comments.append(jira.comment(jis.key, comment_id))
            #print("comment:{}".format(comment.body))

    if getattr(jis.fields, 'parent', None):
        parent = jis.fields.parent
        tmp = jira.search_issues('key={0}'.format(parent.key))
        if len(tmp) != 1:
            raise Exception("Was expecting to find 1 result for key={0}. Got {1}".format(parent.key, len(tmp)))
        print("Creating fb case for the parent (jis.fields.parent) case {}".format(tmp[0].key))
        parent_issue = fb_create_issue(fb, jira, tmp[0], project, email_map, default_assignee)
        data['ixBugParent'] = parent_issue

    if jis.fields.issuelinks:
        for link in jis.fields.issuelinks:
            parent = getattr(link, 'inwardIssue', None)
            child = getattr(link, 'outwardIssue', None)
            if parent:
                tmp = jira.search_issues('key={0}'.format(parent.key))
                if len(tmp) != 1:
                    raise Exception("Was expecting to find 1 result for key={0}. Got {1}".format(parent.key, len(tmp)))
                print("Creating fb case for the parent (inwardIssue) case {}".format(tmp[0].key))
                parent_issue = fb_create_issue(fb, jira, tmp[0],
                                               project,
                                               email_map,
                                               default_assignee)
                data['ixBugParent'] = parent_issue

    sparent_issue = parent_issue if parent_issue else 'n/a'
    print("{0} doesn't exist yet ... parent case {1: >3} Type={2}".format(jis.key, sparent_issue, jis.fields.issuetype.name))
    reporter = getattr(jis.fields, 'reporter', None)
    if reporter:
        data['ixPersonEditedBy'] = email_map[reporter.emailAddress.lower()]
    else:
        data['ixPersonEditedBy'] = default_assignee

    print("Create FB case using data:{}".format(data))
    fbcase=fb.new(**data, Files=attachments)
    print("FB case created {}".format(fbcase))

    for name,f in attachments.items():
        f.close()
        os.remove(f.name)

    for comment in comments:
        fb.edit(ixBug=fbcase.case['ixBug'],
                sEvent="Edited by {} {} \n\n{}".format(comment.updateAuthor.name, comment.updated, comment.body))

    # add a comment about the import
    fb.edit(ixBug=fbcase.case['ixBug'], sEvent="Imported from jira case {}".format(jis.key))

    # resolve the issue if it is already done
    if jis.fields.resolution:
        fb.resolve(ixBug=fbcase.case['ixBug'])

    RECENTLY_ADDED_CASES[jis.key] = int(fbcase.case['ixBug'])
    return int(fbcase.case['ixBug'])

def get_jira_issues(server, query):
    chunk_size = 100
    start_at = 0
    while True:
        issues = server.search_issues(query, startAt=start_at,
                                      maxResults=chunk_size, fields=["*all"])
        if not issues:
            break
        start_at += chunk_size
        for issue in issues:
            yield issue


def run():
    parser = argparse.ArgumentParser(description="JIRA to FogBugz importer")
    parser.add_argument('--jira-server',
                        help="JIRA server URL, ex. http://jira.example.com", required=True)
    parser.add_argument('--jira-username', help="JIRA username", required=True)
    parser.add_argument('--jira-password', help="JIRA password", required=True)
    parser.add_argument('--jira-project', help="Which jira project to read cases", required=True)
    parser.add_argument('--jira-query', help="Jql query filter (in addition to the project)", required=False)
    parser.add_argument('--fogbugz-server',
                        help="FogBugz server URL, ex. http://example.fogbugz.com", required=True)
    parser.add_argument('--fogbugz-token', help="FogBugz access token", required=True)
    parser.add_argument('--fogbugz-project', help="Which FogBugz project to put cases in", required=True)
    parser.add_argument('--default-assignee', help="The email of the default assignee", required=True)
    # TODO: dynamically create projects based on JIRA data
    parser.add_argument('-v', '--verbose',
                        dest="verbose",
                        action="store_true",
                        default=False,
                        help="Get more verbose output")
    args = parser.parse_args()

    try:
        try:
            jira = JIRA(options={'server': args.jira_server},
                        basic_auth=(args.jira_username,
                                    args.jira_password))
        except JIRAError as e:
            if e.status_code == 403:
                sys.stderr.write('Cannot connect to JIRA. Check username/password\n')
                sys.exit(1)
            else:
                msg = "Cannot connect to JIRA  (return code={0})".format(e.status_code)
                if args.verbose:
                    msg += "\n{0}".format('Response from JIRA:\n{0}'.format(e.text))
                sys.stderr.write(msg+'\n')
                sys.exit(1)
        try:
            fb = FogBugz(args.fogbugz_server, token=args.fogbugz_token)
        except FogBugzConnectionError as e:
            sys.stderr.write('Cannot connect to FogBugz {}\n'.format(e))
            sys.exit(1)
        except FobBugzLogonError:
            sys.stderr.write('Cannot login to FogBugz. Check token')
            sys.exit(1)

        # initialize an email to fogbugz User ID mapping
        email_map = {}
        resp = fb.listPeople(fIncludeActive=1, fIncludeNormal=1, fIncludeDeleted=1, fIncludeVirtual=1)
        for person in resp.people.childGenerator():
            #print("person", person)
            #print("person.ixperson", person.ixPerson.string)
            email_map[person.sEmail.string.lower()] = int(person.ixPerson.string)
        try:
            default_assignee = email_map[args.default_assignee.lower()]
        except KeyError:
            parser.error("Default assignee {0} does not exist in FogBugz".format(args.default_assignee))

        #print("email_map: {}".format(email_map))
        query = 'project = "{}"'.format(args.jira_project)
        if args.jira_query:
            query += "AND " + args.jira_query
        print("query: '{}'".format(query))
        issues = get_jira_issues(jira, query)
        for issue in issues:
            print("issue", issue)
            fb_create_issue(fb, jira, issue, args.fogbugz_project, email_map, default_assignee)
    except SystemExit:
        raise
    except:
        sys.stderr.write("Unknown error occurred\n")
        traceback.print_exc(sys.stderr)
        sys.exit(1)
    return sys.exit(0)

if __name__ == '__main__':
    run()
